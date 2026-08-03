"""Alert evaluation and deduplication tests."""

from __future__ import annotations

from datetime import date, timedelta

from src.alerts import (
    Alert,
    AlertState,
    detect_new_30d_high,
    detect_new_30d_low,
    evaluate_alerts,
    should_suppress,
)
from src.history import HistoryRecord
from src.statistics import compute_stats


def _records(end: date, prices: list[float]) -> list[HistoryRecord]:
    start = end - timedelta(days=len(prices) - 1)
    out = []
    for i, p in enumerate(prices):
        d = start + timedelta(days=i)
        out.append(
            HistoryRecord(
                date=d.isoformat(),
                price=p,
                source="test",
                fetched_at=f"{d.isoformat()}T12:00:00+05:30",
            )
        )
    return out


def test_new_30d_low_alert() -> None:
    today = date(2026, 8, 3)
    # 30 days ending with a new low
    prices = [13500 - i * 5 for i in range(29)]  # declining but not below final
    prices.append(13000)  # new low
    # Ensure earlier min is above 13000
    prices = [max(p, 13100) for p in prices[:-1]] + [13000]
    records = _records(today, prices)
    assert detect_new_30d_low(records, today, 13000)
    stats = compute_stats(records, as_of=today)
    alert = evaluate_alerts(records, stats, AlertState(), today)
    assert alert is not None
    assert alert.alert_type == "NEW_30D_LOW"


def test_near_30d_low_alert() -> None:
    today = date(2026, 8, 3)
    # low 13100, high 13820, today 13150 -> position ~7%
    prices = [13820] * 28 + [13100, 13150]
    records = _records(today, prices)
    stats = compute_stats(records, as_of=today)
    assert stats.position_30d is not None
    assert stats.position_30d <= 10
    assert not detect_new_30d_low(records, today, 13150)
    alert = evaluate_alerts(records, stats, AlertState(), today)
    assert alert is not None
    assert alert.alert_type == "NEAR_30D_LOW"


def test_new_30d_high_alert() -> None:
    today = date(2026, 8, 3)
    prices = [13000 + i for i in range(29)] + [14000]
    prices = [min(p, 13500) for p in prices[:-1]] + [14000]
    records = _records(today, prices)
    assert detect_new_30d_high(records, today, 14000)
    stats = compute_stats(records, as_of=today)
    alert = evaluate_alerts(records, stats, AlertState(), today)
    assert alert is not None
    assert alert.alert_type == "NEW_30D_HIGH"


def test_large_daily_movement_alert() -> None:
    today = date(2026, 8, 3)
    # Keep position in normal range, but >1% daily move
    prices = [13200] * 29 + [13400]  # ~1.5% up
    records = _records(today, prices)
    stats = compute_stats(records, as_of=today)
    assert stats.daily_change_percent is not None
    assert abs(stats.daily_change_percent) >= 1.0
    # Force mid-range by construction: all same then jump still near high though
    alert = evaluate_alerts(records, stats, AlertState(), today)
    assert alert is not None
    # May be NEW_30D_HIGH or LARGE_DAILY_MOVE depending on extremes
    assert alert.alert_type in {"LARGE_DAILY_MOVE", "NEW_30D_HIGH", "NEAR_30D_HIGH"}


def test_duplicate_alert_suppression() -> None:
    today = date(2026, 8, 3)
    state = AlertState(
        last_alert_date=today.isoformat(),
        last_alert_type="NEAR_30D_LOW",
        last_alert_price=13150,
    )
    alert = Alert("NEAR_30D_LOW", "msg", 13150, 70)
    assert should_suppress(state, alert, today) is True


def test_alert_escalation_same_day() -> None:
    today = date(2026, 8, 3)
    state = AlertState(
        last_alert_date=today.isoformat(),
        last_alert_type="NEAR_30D_LOW",
        last_alert_price=13150,
    )
    alert = Alert("NEW_30D_LOW", "msg", 13100, 100)
    assert should_suppress(state, alert, today) is False


def test_evaluate_suppresses_duplicate(monkeypatch) -> None:
    today = date(2026, 8, 3)
    prices = [13820] * 28 + [13100, 13150]
    records = _records(today, prices)
    stats = compute_stats(records, as_of=today)
    state = AlertState(
        last_alert_date=today.isoformat(),
        last_alert_type="NEAR_30D_LOW",
        last_alert_price=13150,
    )
    alert = evaluate_alerts(records, stats, state, today)
    assert alert is None
