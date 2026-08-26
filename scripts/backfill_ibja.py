"""
Free one-shot backfill: IBJA India Gold 916 (≈22K) rates.

Sources (no API key):
  1) ibjarates.com rolling ~30-day PDF
  2) ibja.co daily bullion report PDFs (best-effort archive)

Rates are IBJA benchmark INR **per 10 grams** → stored as INR **per gram** (/10).
Prefer PM (closing) session; fall back to AM.

These are India-wide 916 rates, NOT Hyderabad Goodreturns retail.
Existing history days are not overwritten (gap-fill only).

Usage:
  python scripts/backfill_ibja.py --dry-run
  python scripts/backfill_ibja.py
  python scripts/backfill_ibja.py --days 365
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import config  # noqa: E402
from src.history import HistoryStore  # noqa: E402

logger = logging.getLogger(__name__)

SOURCE = "ibja_916"
IBJARATES_HOME = "https://ibjarates.com/"
IBJA_UPLOAD = "https://ibja.co/Upload/"
USER_AGENT = "Mozilla/5.0 (compatible; PersonalGoldTracker/1.0; IBJA backfill)"

# 26-Aug-26 161431 161337 160785 160691 147871 147785 ...
ROW_30D_RE = re.compile(
    r"^(\d{1,2}-[A-Za-z]{3}-\d{2})\s+"
    r"(\d+)\s+(\d+)\s+"  # 999 AM PM
    r"(\d+)\s+(\d+)\s+"  # 995 AM PM
    r"(\d+)\s+(\d+)\b"  # 916 AM PM
)
# Gold 916 148944 148533
GOLD_916_LINE_RE = re.compile(
    r"Gold\s*916\s+(\d{4,7})\s+(\d{4,7})",
    re.IGNORECASE,
)
MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def parse_ibja_date(text: str) -> Optional[date]:
    """Parse dates like 26-Aug-26 or 25/08/2026."""
    text = text.strip()
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2})$", text)
    if m:
        day = int(m.group(1))
        month = MONTHS[m.group(2).lower()]
        year = 2000 + int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def per10g_to_per_gram(value: float) -> Optional[float]:
    per_g = round(float(value) / 10.0, 2)
    if per_g < config.MIN_PRICE_INR or per_g > config.MAX_PRICE_INR:
        logger.warning("Out-of-range after /10: raw=%s per_g=%s", value, per_g)
        return None
    return per_g


def extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise SystemExit(
            "pypdf is required for IBJA PDF backfill. Run: pip install pypdf"
        ) from exc
    from io import BytesIO

    reader = PdfReader(BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def parse_30day_pdf_text(text: str) -> list[tuple[date, float]]:
    """Parse ibjarates rolling 30-day opening/closing PDF."""
    out: list[tuple[date, float]] = []
    for line in text.splitlines():
        line = " ".join(line.split())
        m = ROW_30D_RE.match(line)
        if not m:
            continue
        d = parse_ibja_date(m.group(1))
        if d is None:
            continue
        am_916 = float(m.group(6))
        pm_916 = float(m.group(7))
        raw = pm_916 if pm_916 > 0 else am_916
        per_g = per10g_to_per_gram(raw)
        if per_g is not None:
            out.append((d, per_g))
    return out


def parse_daily_report_text(text: str, fallback_date: date) -> Optional[tuple[date, float]]:
    """Parse ibja.co daily bullion report for Gold 916 PM (else AM)."""
    m = GOLD_916_LINE_RE.search(text)
    if not m:
        return None
    am = float(m.group(1))
    pm = float(m.group(2))
    raw = pm if pm > 0 else am
    per_g = per10g_to_per_gram(raw)
    if per_g is None:
        return None
    d = fallback_date
    month_header = re.search(
        r"Date:\s*(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})",
        text,
        re.IGNORECASE,
    )
    if month_header:
        day = int(month_header.group(1))
        mon = MONTHS.get(month_header.group(2)[:3].lower())
        year = int(month_header.group(3))
        if mon:
            try:
                d = date(year, mon, day)
            except ValueError:
                pass
    return d, per_g


def find_30day_pdf_url(session: requests.Session) -> Optional[str]:
    resp = session.get(IBJARATES_HOME, timeout=60)
    resp.raise_for_status()
    # href may be relative: ../UploadedFiles/30DaysPdf/...
    m = re.search(
        r'href="([^"]*30DaysPdf[^"]+\.pdf)"',
        resp.text,
        re.IGNORECASE,
    )
    if not m:
        return None
    href = m.group(1).replace("&amp;", "&")
    if href.startswith("http"):
        return href
    # Resolve relative to site root
    if href.startswith("../"):
        href = href[3:]
    if not href.startswith("/"):
        href = "/" + href
    return "https://ibjarates.com" + href


def fetch_30day_history(session: requests.Session) -> list[tuple[date, float]]:
    url = find_30day_pdf_url(session)
    if not url:
        logger.warning("Could not find 30-day PDF link on ibjarates.com")
        return []
    # Encode path segments with spaces
    parts = url.split("/")
    url = "/".join(parts[:-1] + [quote(parts[-1])])
    logger.info("Downloading 30-day PDF: %s", url)
    resp = session.get(url, timeout=120)
    resp.raise_for_status()
    text = extract_pdf_text(resp.content)
    rows = parse_30day_pdf_text(text)
    logger.info("Parsed %d days from 30-day PDF", len(rows))
    return rows


def daily_report_url(day: date) -> str:
    name = f"IBJA_Bullion Daily Report - {day.strftime('%d-%m-%Y')}.pdf"
    return IBJA_UPLOAD + quote(name)


def fetch_daily_report(
    session: requests.Session,
    day: date,
) -> Optional[tuple[date, float]]:
    url = daily_report_url(day)
    resp = session.get(url, timeout=60)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    if "pdf" not in (resp.headers.get("content-type") or "").lower() and not resp.content.startswith(
        b"%PDF"
    ):
        return None
    text = extract_pdf_text(resp.content)
    return parse_daily_report_text(text, fallback_date=day)


def collect_archive(
    session: requests.Session,
    start: date,
    end: date,
    *,
    sleep_s: float,
    already: set[str],
) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    day = start
    checked = found = 0
    while day <= end:
        if day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        if day.isoformat() in already:
            day += timedelta(days=1)
            continue
        checked += 1
        try:
            row = fetch_daily_report(session, day)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skip %s: %s", day, exc)
            row = None
        if row:
            out.append(row)
            found += 1
            logger.info("Archive %s → ₹%.2f/g", row[0], row[1])
        time.sleep(sleep_s)
        day += timedelta(days=1)
        if checked % 25 == 0:
            logger.info("Archive progress checked=%d found=%d", checked, found)
    logger.info("Archive done checked=%d found=%d", checked, found)
    return out


def publish_site(records: list) -> None:
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
            "history_note": (
                "Some older days may be IBJA India 916 benchmark (per gram), "
                "not Hyderabad Goodreturns retail."
            ),
        }
    )
    config.SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with config.SITE_HISTORY_PATH.open("w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in records], fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with config.SITE_STATS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill IBJA 916 gold history (free)")
    parser.add_argument("--days", type=int, default=365, help="Look-back window (default 365)")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (default today IST)")
    parser.add_argument("--skip-archive", action="store_true", help="Only use 30-day PDF")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.25)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)

    tz = ZoneInfo(config.TIMEZONE)
    today = datetime.now(tz).date()
    end = date.fromisoformat(args.end) if args.end else today
    start = end - timedelta(days=args.days - 1)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    by_date: dict[str, float] = {}

    # 1) Rolling 30-day PDF
    for d, p in fetch_30day_history(session):
        by_date[d.isoformat()] = p

    # 2) Daily archive PDFs for remaining gaps
    if not args.skip_archive:
        archive_rows = collect_archive(
            session,
            start,
            end,
            sleep_s=args.sleep,
            already=set(by_date),
        )
        for d, p in archive_rows:
            by_date.setdefault(d.isoformat(), p)

    rows = [(date.fromisoformat(k), v) for k, v in sorted(by_date.items())]
    rows = [r for r in rows if start <= r[0] <= end]
    logger.info("Collected %d IBJA 916 daily prices in range %s..%s", len(rows), start, end)
    if not rows:
        logger.error("No IBJA prices collected")
        return 1

    for d, p in rows[:3] + rows[-3:]:
        logger.info("Sample %s → ₹%.2f/g", d, p)

    store = HistoryStore()
    existing = store.load()
    merged, added = store.merge_bootstrap([(d, p, SOURCE) for d, p in rows])
    logger.info(
        "Gap-fill: add %d days (existing=%d after=%d)",
        added,
        len(existing),
        len(merged),
    )

    if args.dry_run:
        logger.info("Dry run — not writing files")
        return 0

    store.save(merged)
    publish_site(merged)
    logger.info("Done. Push data/history.json and site/data/* to GitHub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
