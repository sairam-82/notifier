"""Statistics and buyer-oriented price classification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

from src import config
from src.history import HistoryRecord


@dataclass
class PeriodStats:
    low: Optional[float]
    high: Optional[float]
    average: Optional[float]
    change: Optional[float]
    change_percent: Optional[float]
    count: int


@dataclass
class MarketStats:
    today_price: Optional[float]
    yesterday_price: Optional[float]
    daily_change: Optional[float]
    daily_change_percent: Optional[float]
    daily_direction: str  # up | down | flat | unknown
    position_30d: Optional[float]  # 0-100
    classification: str
    classification_label: str
    period_7d: PeriodStats
    period_30d: PeriodStats
    period_90d: PeriodStats
    period_365d: PeriodStats
    history_days: int
    as_of_date: Optional[str]
    last_updated: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _records_in_window(
    records: list[HistoryRecord],
    end: date,
    days: int,
) -> list[HistoryRecord]:
    start = end - timedelta(days=days - 1)
    start_s, end_s = start.isoformat(), end.isoformat()
    return [r for r in records if start_s <= r.date <= end_s]


def _period_stats(
    window: list[HistoryRecord],
    include_change: bool = False,
) -> PeriodStats:
    if not window:
        return PeriodStats(None, None, None, None, None, 0)
    prices = [r.price for r in window]
    low = min(prices)
    high = max(prices)
    avg = sum(prices) / len(prices)
    change = change_pct = None
    if include_change and len(window) >= 2:
        first = window[0].price
        last = window[-1].price
        change = last - first
        change_pct = (change / first * 100.0) if first else None
    return PeriodStats(
        low=low,
        high=high,
        average=round(avg, 2),
        change=change,
        change_percent=None if change_pct is None else round(change_pct, 2),
        count=len(window),
    )


def range_position(today: float, low: float, high: float) -> float:
    """
    Position of today inside [low, high] as 0–100%.

    When high == low, returns 50.0 (undefined spread).
    """
    if high == low:
        return 50.0
    return max(0.0, min(100.0, (today - low) / (high - low) * 100.0))


def classify_position(position: Optional[float]) -> tuple[str, str]:
    """
    Buyer-oriented classification.

    GREEN-ish codes = relatively cheap; RED-ish = relatively expensive.
    """
    if position is None:
        return "UNKNOWN", "Insufficient history"

    tol = config.EXACT_BOUND_TOLERANCE
    if position <= tol:
        return "D30_LOW", "30D LOW"
    if position >= 100 - tol:
        return "D30_HIGH", "30D HIGH"
    if position <= config.NEAR_LOW_PERCENT:
        return "NEAR_30D_LOW", "NEAR 30D LOW"
    if position <= config.LOW_RANGE_PERCENT:
        return "LOW_RANGE", "LOW RANGE"
    if position < config.HIGH_RANGE_PERCENT:
        return "NORMAL_RANGE", "NORMAL RANGE"
    if position < config.NEAR_HIGH_PERCENT:
        return "HIGH_RANGE", "HIGH RANGE"
    return "NEAR_30D_HIGH", "NEAR 30D HIGH"


def is_buyer_favorable(code: str) -> bool:
    return code in {"D30_LOW", "NEAR_30D_LOW", "LOW_RANGE"}


def compute_stats(records: list[HistoryRecord], as_of: Optional[date] = None) -> MarketStats:
    if not records:
        empty = PeriodStats(None, None, None, None, None, 0)
        return MarketStats(
            today_price=None,
            yesterday_price=None,
            daily_change=None,
            daily_change_percent=None,
            daily_direction="unknown",
            position_30d=None,
            classification="UNKNOWN",
            classification_label="No data",
            period_7d=empty,
            period_30d=empty,
            period_90d=empty,
            period_365d=empty,
            history_days=0,
            as_of_date=None,
            last_updated=None,
        )

    ordered = sorted(records, key=lambda r: r.date)
    if as_of is None:
        as_of = date.fromisoformat(ordered[-1].date)

    today_rec = next((r for r in reversed(ordered) if r.date <= as_of.isoformat()), None)
    if today_rec is None:
        today_rec = ordered[-1]
        as_of = date.fromisoformat(today_rec.date)

    today_price = today_rec.price
    prior = [r for r in ordered if r.date < today_rec.date]
    yesterday = prior[-1] if prior else None
    yesterday_price = yesterday.price if yesterday else None

    daily_change = daily_pct = None
    direction = "unknown"
    if yesterday_price is not None:
        daily_change = today_price - yesterday_price
        daily_pct = (daily_change / yesterday_price * 100.0) if yesterday_price else None
        if abs(daily_change) < 1e-9:
            direction = "flat"
        elif daily_change > 0:
            direction = "up"
        else:
            direction = "down"

    w7 = _records_in_window(ordered, as_of, 7)
    w30 = _records_in_window(ordered, as_of, 30)
    w90 = _records_in_window(ordered, as_of, 90)
    w365 = _records_in_window(ordered, as_of, 365)

    p7 = _period_stats(w7, include_change=True)
    p30 = _period_stats(w30, include_change=True)
    p90 = _period_stats(w90, include_change=False)
    p365 = _period_stats(w365, include_change=False)

    position = None
    if p30.low is not None and p30.high is not None and p30.count > 0:
        position = round(range_position(today_price, p30.low, p30.high), 2)

    code, label = classify_position(position)

    return MarketStats(
        today_price=today_price,
        yesterday_price=yesterday_price,
        daily_change=None if daily_change is None else round(daily_change, 2),
        daily_change_percent=None if daily_pct is None else round(daily_pct, 2),
        daily_direction=direction,
        position_30d=position,
        classification=code,
        classification_label=label,
        period_7d=p7,
        period_30d=p30,
        period_90d=p90,
        period_365d=p365,
        history_days=len(ordered),
        as_of_date=today_rec.date,
        last_updated=today_rec.fetched_at,
    )


def format_inr(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    # Indian-style grouping for display
    neg = amount < 0
    n = abs(amount)
    if n == int(n):
        s = f"{int(n):,}"
    else:
        s = f"{n:,.2f}"
    # Convert Western thousands to a simple comma form (good enough for UI)
    return f"{'-' if neg else ''}₹{s}"


def format_daily_movement(stats: MarketStats) -> str:
    if stats.daily_change is None or stats.daily_change_percent is None:
        return "— ₹0 (0.00%)"
    ch = stats.daily_change
    pct = stats.daily_change_percent
    if stats.daily_direction == "up":
        return f"▲ +₹{abs(ch):,.0f} (+{pct:.2f}%)"
    if stats.daily_direction == "down":
        return f"▼ -₹{abs(ch):,.0f} ({pct:.2f}%)"
    return "— ₹0 (0.00%)"
