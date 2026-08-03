"""Event-driven alert evaluation with deduplication."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

from src import config
from src.history import HistoryRecord
from src.statistics import MarketStats, format_daily_movement, format_inr, is_buyer_favorable

logger = logging.getLogger(__name__)

# Higher number = higher priority (can escalate same day)
ALERT_PRIORITY: dict[str, int] = {
    "NEW_30D_LOW": 100,
    "NEW_30D_HIGH": 100,
    "NEAR_30D_LOW": 70,
    "NEAR_30D_HIGH": 70,
    "LARGE_DAILY_MOVE": 60,
    "FETCH_FAILURE": 50,
    "VALIDATION_FAILED": 50,
    "DAILY_SUMMARY": 10,
}


@dataclass
class Alert:
    alert_type: str
    message: str
    price: float
    priority: int


@dataclass
class AlertState:
    last_alert_date: Optional[str] = None
    last_alert_type: Optional[str] = None
    last_alert_price: Optional[float] = None
    last_failure_date: Optional[str] = None
    last_failure_type: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AlertState":
        return cls(
            last_alert_date=data.get("last_alert_date"),
            last_alert_type=data.get("last_alert_type"),
            last_alert_price=data.get("last_alert_price"),
            last_failure_date=data.get("last_failure_date"),
            last_failure_type=data.get("last_failure_type"),
        )


def load_alert_state(path: Path = config.ALERT_STATE_PATH) -> AlertState:
    if not path.exists():
        return AlertState()
    with path.open(encoding="utf-8") as fh:
        return AlertState.from_dict(json.load(fh))


def save_alert_state(state: AlertState, path: Path = config.ALERT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state.to_dict(), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    logger.info("Alert state saved: %s", path)


def detect_new_30d_low(records: list[HistoryRecord], as_of: date, today_price: float) -> bool:
    from datetime import timedelta

    start = (as_of - timedelta(days=29)).isoformat()
    end = as_of.isoformat()
    window = [r for r in records if start <= r.date <= end]
    if len(window) < 2:
        return False
    low = min(r.price for r in window)
    if abs(today_price - low) > 1e-6:
        return False
    earlier = [r for r in window if r.date < end]
    if not earlier:
        return False
    return today_price < min(r.price for r in earlier) - 1e-9


def detect_new_30d_high(records: list[HistoryRecord], as_of: date, today_price: float) -> bool:
    from datetime import timedelta

    start = (as_of - timedelta(days=29)).isoformat()
    end = as_of.isoformat()
    window = [r for r in records if start <= r.date <= end]
    if len(window) < 2:
        return False
    high = max(r.price for r in window)
    if abs(today_price - high) > 1e-6:
        return False
    earlier = [r for r in window if r.date < end]
    if not earlier:
        return False
    return today_price > max(r.price for r in earlier) + 1e-9


def should_suppress(state: AlertState, alert: Alert, today: date) -> bool:
    """Deduplicate unless material escalation / price change."""
    if state.last_alert_date != today.isoformat():
        return False
    if state.last_alert_type is None:
        return False

    prev_pri = ALERT_PRIORITY.get(state.last_alert_type, 0)
    # Escalation always allowed
    if alert.priority > prev_pri:
        return False
    # Same type + same price => suppress
    if (
        alert.alert_type == state.last_alert_type
        and state.last_alert_price is not None
        and abs(alert.price - state.last_alert_price) < 0.5
    ):
        return True
    # Lower or equal priority same day without meaningful price change
    if alert.priority <= prev_pri:
        if state.last_alert_price is not None and abs(alert.price - state.last_alert_price) < 0.5:
            return True
        # Material price change with same/lower priority: allow only if type differs
        if alert.alert_type == state.last_alert_type:
            return abs(alert.price - (state.last_alert_price or 0)) < 1.0
    return False


def build_buy_alert(stats: MarketStats, alert_type: str) -> str:
    price = stats.today_price or 0
    move = format_daily_movement(stats)
    pos = stats.position_30d
    low = stats.period_30d.low
    high = stats.period_30d.high
    favorable = is_buyer_favorable(stats.classification) or alert_type in {
        "NEW_30D_LOW",
        "NEAR_30D_LOW",
    }
    emoji = "🟢" if favorable else "🔴"

    pos_line = f"Current position: {pos:.0f}%" if pos is not None else "Current position: n/a"

    if alert_type == "NEW_30D_LOW":
        return (
            f"{emoji} GOLD BUY ALERT\n\n"
            f"22K Gold · {config.CITY}\n\n"
            f"{format_inr(price)}/g\n\n"
            f"🔥 NEW 30-DAY LOW\n\n"
            f"{move}\n\n"
            f"30D Range\n"
            f"Low: {format_inr(low)}\n"
            f"High: {format_inr(high)}\n\n"
            f"{pos_line}"
        )

    if alert_type == "NEAR_30D_LOW":
        return (
            f"{emoji} GOLD PRICE ALERT\n\n"
            f"22K {config.CITY}\n"
            f"{format_inr(price)}/g\n\n"
            f"Near 30-Day Low\n\n"
            f"{pos_line}\n\n"
            f"30D Low: {format_inr(low)}\n"
            f"30D High: {format_inr(high)}"
        )

    if alert_type == "NEW_30D_HIGH":
        return (
            f"{emoji} GOLD PRICE ALERT\n\n"
            f"22K {config.CITY}\n"
            f"{format_inr(price)}/g\n\n"
            f"New 30-Day High"
        )

    if alert_type == "NEAR_30D_HIGH":
        return (
            f"{emoji} GOLD PRICE ALERT\n\n"
            f"22K {config.CITY}\n"
            f"{format_inr(price)}/g\n\n"
            f"Near 30-Day High\n\n"
            f"{pos_line}\n\n"
            f"30D Low: {format_inr(low)}\n"
            f"30D High: {format_inr(high)}"
        )

    if alert_type == "LARGE_DAILY_MOVE":
        pos_pct = f"{pos:.0f}%" if pos is not None else "n/a"
        return (
            f"⚡ GOLD PRICE ALERT\n\n"
            f"22K {config.CITY}\n"
            f"{format_inr(price)}/g\n\n"
            f"Large daily move\n"
            f"{move}\n\n"
            f"Buyer status: {stats.classification_label}\n"
            f"Position: {pos_pct} of 30-day range"
        )

    # Daily summary
    pos_pct = f"{pos:.0f}%" if pos is not None else "n/a"
    return (
        f"📊 GOLD DAILY SUMMARY\n\n"
        f"22K {config.CITY}\n"
        f"{format_inr(price)}/g\n\n"
        f"{move}\n"
        f"{'🟢' if favorable else '🔴'} {stats.classification_label}\n"
        f"Position: {pos_pct} of 30-day range\n\n"
        f"30D Low: {format_inr(low)}\n"
        f"30D High: {format_inr(high)}"
    )


def evaluate_alerts(
    records: list[HistoryRecord],
    stats: MarketStats,
    state: AlertState,
    today: date,
) -> Optional[Alert]:
    """Pick the highest-priority actionable alert, respecting dedupe."""
    if stats.today_price is None:
        return None

    candidates: list[Alert] = []
    price = stats.today_price

    is_new_low = detect_new_30d_low(records, today, price)
    is_new_high = detect_new_30d_high(records, today, price)

    if is_new_low:
        candidates.append(
            Alert(
                "NEW_30D_LOW",
                build_buy_alert(stats, "NEW_30D_LOW"),
                price,
                ALERT_PRIORITY["NEW_30D_LOW"],
            )
        )
    elif (
        stats.position_30d is not None
        and stats.position_30d <= config.NEAR_LOW_PERCENT
    ):
        candidates.append(
            Alert(
                "NEAR_30D_LOW",
                build_buy_alert(stats, "NEAR_30D_LOW"),
                price,
                ALERT_PRIORITY["NEAR_30D_LOW"],
            )
        )

    if is_new_high:
        candidates.append(
            Alert(
                "NEW_30D_HIGH",
                build_buy_alert(stats, "NEW_30D_HIGH"),
                price,
                ALERT_PRIORITY["NEW_30D_HIGH"],
            )
        )
    elif (
        stats.position_30d is not None
        and stats.position_30d >= config.NEAR_HIGH_PERCENT
    ):
        candidates.append(
            Alert(
                "NEAR_30D_HIGH",
                build_buy_alert(stats, "NEAR_30D_HIGH"),
                price,
                ALERT_PRIORITY["NEAR_30D_HIGH"],
            )
        )

    if (
        stats.daily_change_percent is not None
        and abs(stats.daily_change_percent) >= config.DAILY_MOVE_ALERT_PERCENT
    ):
        candidates.append(
            Alert(
                "LARGE_DAILY_MOVE",
                build_buy_alert(stats, "LARGE_DAILY_MOVE"),
                price,
                ALERT_PRIORITY["LARGE_DAILY_MOVE"],
            )
        )

    if config.SEND_DAILY_SUMMARY:
        candidates.append(
            Alert(
                "DAILY_SUMMARY",
                build_buy_alert(stats, "DAILY_SUMMARY"),
                price,
                ALERT_PRIORITY["DAILY_SUMMARY"],
            )
        )

    if not candidates:
        logger.info("Alert classification: none")
        return None

    candidates.sort(key=lambda a: a.priority, reverse=True)
    chosen = candidates[0]
    logger.info(
        "Alert classification: type=%s priority=%s position=%s",
        chosen.alert_type,
        chosen.priority,
        stats.position_30d,
    )

    if should_suppress(state, chosen, today):
        logger.info(
            "Alert suppressed (dedupe): type=%s price=%s",
            chosen.alert_type,
            chosen.price,
        )
        return None
    return chosen


def build_failure_message(last_price: Optional[float], last_updated: Optional[str]) -> str:
    price_line = format_inr(last_price) if last_price is not None else "unavailable"
    return (
        "⚠️ Gold Tracker\n\n"
        f"Unable to retrieve today's Hyderabad 22K gold rate.\n\n"
        f"Last successful price:\n{price_line}\n\n"
        f"Last updated: {last_updated or 'unknown'}"
    )


def build_validation_failed_message(detail: str, last_price: Optional[float]) -> str:
    return (
        "⚠️ Gold Tracker\n\n"
        "Data validation failed — suspicious or invalid price not saved.\n\n"
        f"{detail}\n\n"
        f"Last valid price: {format_inr(last_price)}"
    )
