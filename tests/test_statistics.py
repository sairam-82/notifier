"""Statistics and classification tests."""

from __future__ import annotations

from datetime import date, timedelta

from src.history import HistoryRecord
from src.statistics import classify_position, compute_stats, range_position


def _series(start: date, prices: list[float]) -> list[HistoryRecord]:
    out: list[HistoryRecord] = []
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


def test_30_day_low_high_average() -> None:
    start = date(2026, 7, 5)
    # 30 prices: low 12900, high 13500, last 13020
    prices = [12900 + (i % 7) * 100 for i in range(29)]
    prices[0] = 12900
    prices[10] = 13500
    prices.append(13020)
    records = _series(start, prices)
    stats = compute_stats(records, as_of=start + timedelta(days=29))
    assert stats.period_30d.low == 12900
    assert stats.period_30d.high == 13500
    assert stats.period_30d.average is not None
    assert stats.today_price == 13020


def test_range_position_example() -> None:
    # (13020 - 12900) / (13500 - 12900) = 120/600 = 0.2 -> 20%
    assert range_position(13020, 12900, 13500) == 20.0


def test_equal_high_low_handling() -> None:
    assert range_position(13000, 13000, 13000) == 50.0
    code, label = classify_position(50.0)
    assert code == "NORMAL_RANGE"
    assert label == "NORMAL RANGE"


def test_classification_bands() -> None:
    assert classify_position(0)[0] == "D30_LOW"
    assert classify_position(7)[0] == "NEAR_30D_LOW"
    assert classify_position(20)[0] == "LOW_RANGE"
    assert classify_position(50)[0] == "NORMAL_RANGE"
    assert classify_position(80)[0] == "HIGH_RANGE"
    assert classify_position(95)[0] == "NEAR_30D_HIGH"
    assert classify_position(100)[0] == "D30_HIGH"


def test_daily_change() -> None:
    records = _series(date(2026, 8, 1), [13100, 13220])
    stats = compute_stats(records, as_of=date(2026, 8, 2))
    assert stats.yesterday_price == 13100
    assert stats.daily_change == 120
    assert stats.daily_direction == "up"
    assert stats.daily_change_percent is not None
    assert abs(stats.daily_change_percent - (120 / 13100 * 100)) < 0.01
