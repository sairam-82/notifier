"""
One-shot backfill of Hyderabad 22K gold history via Metals-API free trial.

Usage (PowerShell):
  $env:METALS_API_KEY = "your_key_here"
  python scripts/backfill_metals_api.py --dry-run
  python scripts/backfill_metals_api.py

Then:
  - Review data/history.json
  - Push to GitHub
  - Delete/unset METALS_API_KEY (do not commit it)

Notes:
  - Symbol: HYDE-22k (Hyderabad 22K, per gram, INR via gold-price-india / base=INR)
  - Free plan timeseries max ~30 days per request → script chunks automatically
  - Historical coverage for HYDE-22k starts around 2023-12-14
  - Existing Goodreturns days are NOT overwritten (gap-fill only)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import config  # noqa: E402
from src.history import HistoryStore  # noqa: E402

logger = logging.getLogger(__name__)

API_BASE = "https://metals-api.com/api"
SYMBOL = "HYDE-22k"
SOURCE = "metals_api"
# Free plan typically allows ~30 days per timeseries request
CHUNK_DAYS = 30
# Earliest known HYDE-22k coverage per Metals-API symbol page
EARLIEST = date(2023, 12, 14)


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def normalize_price(raw: float, *, base: str) -> Optional[float]:
    """
    Convert API rate to INR/gram.

    Metals-API: with base=USD, metal rates often need 1/value.
    With base=INR (or gold-price-india), values are already currency units.
    """
    if raw is None or raw != raw or raw == 0:
        return None
    value = float(raw)
    if base.upper() == "USD" and value < 1:
        value = 1.0 / value
    # Sanity: Hyderabad 22K INR/g in recent years
    if value < config.MIN_PRICE_INR or value > config.MAX_PRICE_INR:
        # Try inverse once more if it lands in range
        if value > 0:
            inv = 1.0 / value
            if config.MIN_PRICE_INR <= inv <= config.MAX_PRICE_INR:
                return round(inv, 2)
        logger.warning("Skipping out-of-range price raw=%s normalized=%s", raw, value)
        return None
    return round(value, 2)


def api_get(path: str, key: str, params: dict[str, Any]) -> dict[str, Any]:
    params = {**params, "access_key": key}
    url = f"{API_BASE}/{path.lstrip('/')}"
    # Never log the key
    safe = {k: v for k, v in params.items() if k != "access_key"}
    logger.info("GET %s params=%s", url, safe)
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", True) and data.get("error"):
        raise RuntimeError(f"Metals-API error: {data.get('error')}")
    if data.get("success") is False:
        raise RuntimeError(f"Metals-API failed: {data}")
    return data


def probe_latest(key: str) -> float:
    """Validate symbol/units using India endpoint (always INR per gram)."""
    data = api_get(
        "gold-price-india",
        key,
        {"symbols": SYMBOL},
    )
    rates = data.get("rates") or {}
    if SYMBOL not in rates:
        raise RuntimeError(f"{SYMBOL} missing in gold-price-india response: {list(rates)[:10]}")
    price = normalize_price(float(rates[SYMBOL]), base="INR")
    if price is None:
        raise RuntimeError(f"Could not normalize latest {SYMBOL}={rates[SYMBOL]}")
    logger.info("Probe OK: latest %s ≈ ₹%.2f /g (INR)", SYMBOL, price)
    return price


def fetch_timeseries_chunk(
    key: str,
    start: date,
    end: date,
) -> list[tuple[date, float]]:
    """Fetch up to ~30 days via timeseries with base=INR."""
    data = api_get(
        "timeseries",
        key,
        {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "base": "INR",
            "symbols": SYMBOL,
        },
    )
    rates = data.get("rates") or {}
    out: list[tuple[date, float]] = []
    for day_str, day_rates in sorted(rates.items()):
        if not isinstance(day_rates, dict) or SYMBOL not in day_rates:
            continue
        price = normalize_price(float(day_rates[SYMBOL]), base=str(data.get("base") or "INR"))
        if price is None:
            continue
        out.append((date.fromisoformat(day_str), price))
    return out


def fetch_day_india(key: str, day: date) -> Optional[tuple[date, float]]:
    """Fallback: gold-price-india?date=YYYY-MM-DD"""
    data = api_get(
        "gold-price-india",
        key,
        {"symbols": SYMBOL, "date": day.isoformat()},
    )
    rates = data.get("rates") or {}
    if SYMBOL not in rates:
        return None
    price = normalize_price(float(rates[SYMBOL]), base="INR")
    if price is None:
        return None
    return day, price


def daterange_chunks(start: date, end: date, size: int) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=size - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def collect_history(
    key: str,
    start: date,
    end: date,
    *,
    sleep_s: float,
    use_daily_fallback: bool,
) -> list[tuple[date, float]]:
    collected: dict[str, float] = {}

    # Prefer timeseries chunks (fewer API calls)
    timeseries_ok = True
    for chunk_start, chunk_end in daterange_chunks(start, end, CHUNK_DAYS):
        if not timeseries_ok:
            break
        try:
            rows = fetch_timeseries_chunk(key, chunk_start, chunk_end)
            for d, p in rows:
                collected[d.isoformat()] = p
            logger.info(
                "Timeseries chunk %s..%s → %d points (total %d)",
                chunk_start,
                chunk_end,
                len(rows),
                len(collected),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Timeseries failed (%s); will try daily gold-price-india", exc)
            timeseries_ok = False
            break
        time.sleep(sleep_s)

    if not timeseries_ok or (use_daily_fallback and len(collected) < (end - start).days * 0.5):
        logger.info("Filling with daily gold-price-india calls…")
        day = start
        while day <= end:
            if day.isoformat() in collected:
                day += timedelta(days=1)
                continue
            try:
                row = fetch_day_india(key, day)
                if row:
                    collected[row[0].isoformat()] = row[1]
                    logger.info("Day %s → ₹%.2f", day, row[1])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skip %s: %s", day, exc)
            time.sleep(sleep_s)
            day += timedelta(days=1)

    return [(date.fromisoformat(k), v) for k, v in sorted(collected.items())]


def publish_site(records: list) -> None:
    """Refresh site/data JSON so the dashboard matches history."""
    from src.statistics import compute_stats

    stats = compute_stats(records)
    payload = stats.to_dict()
    payload.update(
        {
            "city": config.CITY,
            "karat": config.KARAT,
            "source": config.SOURCE_NAME,
            "source_url": config.SOURCE_URL,
            "timezone": config.TIMEZONE,
            "currency": config.CURRENCY,
            "unit": config.UNIT,
        }
    )
    config.SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with config.SITE_HISTORY_PATH.open("w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in records], fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with config.SITE_STATS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    logger.info("Dashboard data refreshed under site/data/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill HYDE-22k history from Metals-API")
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="How many days back from --end (default 365)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date YYYY-MM-DD (overrides --days)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: yesterday IST)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report only; do not write history.json",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.35,
        help="Seconds between API calls (rate-limit friendly)",
    )
    parser.add_argument(
        "--force-daily",
        action="store_true",
        help="Also fill missing days via gold-price-india even if timeseries works",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)

    key = __import__("os").environ.get("METALS_API_KEY", "").strip()
    if not key:
        logger.error("Set METALS_API_KEY env var first (do not commit the key).")
        return 2

    tz = ZoneInfo(config.TIMEZONE)
    today = datetime.now(tz).date()
    end = date.fromisoformat(args.end) if args.end else today - timedelta(days=1)
    if args.start:
        start = date.fromisoformat(args.start)
    else:
        start = end - timedelta(days=args.days - 1)
    start = max(start, EARLIEST)
    if start > end:
        logger.error("Invalid range: %s > %s", start, end)
        return 2

    logger.info("Backfill range: %s .. %s (symbol=%s)", start, end, SYMBOL)

    try:
        probe_latest(key)
    except Exception as exc:  # noqa: BLE001
        logger.error("Probe failed — check API key / plan / symbol: %s", exc)
        return 1

    rows = collect_history(
        key,
        start,
        end,
        sleep_s=args.sleep,
        use_daily_fallback=args.force_daily,
    )
    logger.info("Fetched %d daily prices", len(rows))
    if not rows:
        logger.error("No prices fetched")
        return 1

    sample = rows[:3] + rows[-3:]
    for d, p in sample:
        logger.info("Sample %s → ₹%.2f", d, p)

    items = [(d, p, SOURCE) for d, p in rows]
    store = HistoryStore()
    existing = store.load()
    merged, added = store.merge_bootstrap(items)

    logger.info(
        "Would add %d new days (existing=%d, after=%d)",
        added,
        len(existing),
        len(merged),
    )

    if args.dry_run:
        logger.info("Dry run — not writing files. Unset METALS_API_KEY when done.")
        return 0

    store.save(merged)
    publish_site(merged)
    logger.info(
        "Done. history.json updated. Push to GitHub, then delete METALS_API_KEY."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
