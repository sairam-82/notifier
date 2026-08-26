"""Main update pipeline: scrape → validate → history → stats → alerts → dashboard."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Allow running as `python scripts/update.py` from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import config  # noqa: E402
from src.alerts import (  # noqa: E402
    AlertState,
    build_failure_message,
    build_validation_failed_message,
    evaluate_alerts,
    load_alert_state,
    save_alert_state,
)
from src.history import HistoryStore  # noqa: E402
from src.outlook import OutlookResult, compute_outlook  # noqa: E402
from src.providers.goodreturns import GoodReturnsProvider  # noqa: E402
from src.scraper import fetch_and_validate  # noqa: E402
from src.statistics import compute_stats  # noqa: E402
from src.telegram import send_telegram_message  # noqa: E402

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def today_ist() -> date:
    return datetime.now(ZoneInfo(config.TIMEZONE)).date()


def publish_dashboard(records_payload: list[dict], stats_payload: dict) -> None:
    """Write site/data JSON consumed by the static dashboard (GitHub Pages)."""
    config.SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with config.SITE_HISTORY_PATH.open("w", encoding="utf-8") as fh:
        json.dump(records_payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    with config.SITE_STATS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(stats_payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # Keep data/history.json and site copy in sync when called after save
    if config.HISTORY_PATH.exists():
        shutil.copy2(config.HISTORY_PATH, config.SITE_HISTORY_PATH)

    logger.info("Dashboard generated: %s and %s", config.SITE_HISTORY_PATH, config.SITE_STATS_PATH)


def maybe_notify_failure(state: AlertState, today: date, message: str, failure_type: str) -> AlertState:
    if state.last_failure_date == today.isoformat() and state.last_failure_type == failure_type:
        logger.info("Failure notification suppressed (already sent today): %s", failure_type)
        return state
    sent = send_telegram_message(message)
    logger.info("Telegram failure notice sent=%s", sent)
    state.last_failure_date = today.isoformat()
    state.last_failure_type = failure_type
    return state


def run(offline_html: Path | None = None, skip_telegram: bool = False) -> int:
    setup_logging()
    today = today_ist()
    store = HistoryStore()
    state = load_alert_state()

    existing = store.load()
    previous = store.get_previous(existing, today)
    previous_price = previous.price if previous else None
    # If we already have today's record, compare validation against yesterday still;
    # for suspicious jump detection, prefer last stored price (could be today morning).
    latest = existing[-1] if existing else None
    compare_price = latest.price if latest else previous_price

    provider = GoodReturnsProvider(
        html=offline_html.read_text(encoding="utf-8") if offline_html else None
    )

    # Bootstrap historical rows when history is empty / sparse
    try:
        hist_rows = provider.fetch_historical_prices()
        if hist_rows:
            merged, added = store.merge_bootstrap(
                [(h.date, h.price, h.source) for h in hist_rows]
            )
            if added:
                store.save(merged)
                existing = merged
                logger.info("Bootstrap imported %d historical days", added)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Historical bootstrap failed (continuing): %s", exc)

    existing = store.load()
    previous = store.get_previous(existing, today)
    previous_price = previous.price if previous else None
    latest = existing[-1] if existing else None
    compare_price = latest.price if latest else previous_price

    try:
        quote, validation = fetch_and_validate(provider, previous_price=compare_price)
    except Exception as exc:  # noqa: BLE001
        logger.error("Fetch failed: %s", exc)
        last_price = latest.price if latest else None
        last_updated = latest.fetched_at if latest else None
        if not skip_telegram:
            state = maybe_notify_failure(
                state,
                today,
                build_failure_message(last_price, last_updated),
                "FETCH_FAILURE",
            )
            save_alert_state(state)
        # Still regenerate dashboard from existing data
        stats = compute_stats(existing, as_of=today if existing else None)
        _publish(existing, stats, today)
        return 1

    if quote is None or not validation.ok:
        detail = validation.reason
        logger.error("Validation failed — not saving: %s", detail)
        if not skip_telegram:
            state = maybe_notify_failure(
                state,
                today,
                build_validation_failed_message(detail, compare_price),
                "VALIDATION_FAILED",
            )
            save_alert_state(state)
        stats = compute_stats(existing, as_of=today if existing else None)
        _publish(existing, stats, today)
        return 2

    records, changed, _created = store.upsert(
        day=today,
        price=quote.price,
        source=quote.source,
        fetched_at=quote.fetched_at,
    )
    if changed:
        store.save(records)
        logger.info("History updated")
    else:
        logger.info("History not updated (no material change)")

    stats = compute_stats(records, as_of=today)
    logger.info(
        "Statistics: today=%.2f position=%s class=%s daily=%s",
        stats.today_price or -1,
        stats.position_30d,
        stats.classification,
        stats.daily_change_percent,
    )

    outlook = compute_outlook(records, stats, as_of=today)
    publish_dashboard([r.to_dict() for r in records], _stats_dict(stats, outlook))

    alert = evaluate_alerts(records, stats, state, today, outlook=outlook)
    if alert and not skip_telegram:
        sent = send_telegram_message(alert.message)
        logger.info("Telegram sent=%s type=%s", sent, alert.alert_type)
        if sent:
            state.last_alert_date = today.isoformat()
            state.last_alert_type = alert.alert_type
            state.last_alert_price = alert.price
            # Clear failure latch on successful data day
            state.last_failure_date = None
            state.last_failure_type = None
            save_alert_state(state)
    elif alert and skip_telegram:
        logger.info("Alert would send (skip_telegram): %s", alert.alert_type)
    else:
        logger.info("Telegram not sent (no alert)")

    return 0


def _stats_dict(stats, outlook: OutlookResult | None = None) -> dict:
    payload = stats.to_dict()
    payload["city"] = config.CITY
    payload["karat"] = config.KARAT
    payload["source"] = config.SOURCE_NAME
    payload["source_url"] = config.SOURCE_URL
    payload["timezone"] = config.TIMEZONE
    payload["currency"] = config.CURRENCY
    payload["unit"] = config.UNIT
    if outlook is not None:
        payload["outlook"] = outlook.to_dict()
    return payload


def _publish(records, stats, today: date) -> None:
    outlook = compute_outlook(records, stats, as_of=today)
    publish_dashboard([r.to_dict() for r in records], _stats_dict(stats, outlook))


def main() -> None:
    parser = argparse.ArgumentParser(description="Update Hyderabad 22K gold price tracker")
    parser.add_argument(
        "--html",
        type=Path,
        default=None,
        help="Offline HTML file (skip live fetch; for tests/debug)",
    )
    parser.add_argument(
        "--skip-telegram",
        action="store_true",
        help="Do not send Telegram messages",
    )
    args = parser.parse_args()
    raise SystemExit(run(offline_html=args.html, skip_telegram=args.skip_telegram))


if __name__ == "__main__":
    main()
