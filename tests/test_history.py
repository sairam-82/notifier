"""History store tests."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.history import HistoryStore


def test_no_duplicate_daily_records(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    tz = ZoneInfo("Asia/Kolkata")
    t1 = datetime(2026, 8, 3, 9, 30, tzinfo=tz)
    t2 = datetime(2026, 8, 3, 15, 0, tzinfo=tz)

    records, changed, created = store.upsert(date(2026, 8, 3), 13220, "goodreturns", t1)
    store.save(records)
    assert created is True
    assert changed is True

    records, changed, created = store.upsert(date(2026, 8, 3), 13100, "goodreturns", t2)
    store.save(records)
    assert created is False
    assert changed is True

    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].price == 13100
    assert loaded[0].date == "2026-08-03"


def test_update_todays_existing_record(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    tz = ZoneInfo("Asia/Kolkata")
    store.save([])
    records, _, _ = store.upsert(
        date(2026, 8, 1), 13000, "goodreturns", datetime(2026, 8, 1, 9, 0, tzinfo=tz)
    )
    store.save(records)
    records, changed, created = store.upsert(
        date(2026, 8, 1), 13050, "goodreturns", datetime(2026, 8, 1, 15, 0, tzinfo=tz)
    )
    assert created is False
    assert changed is True
    assert len(records) == 1
    assert records[0].price == 13050


def test_merge_bootstrap_does_not_overwrite(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    tz = ZoneInfo("Asia/Kolkata")
    records, _, _ = store.upsert(
        date(2026, 8, 3), 99999, "manual", datetime(2026, 8, 3, 9, 0, tzinfo=tz)
    )
    store.save(records)
    merged, added = store.merge_bootstrap(
        [
            (date(2026, 8, 3), 13220, "goodreturns"),
            (date(2026, 8, 2), 13220, "goodreturns"),
        ]
    )
    assert added == 1
    by_date = {r.date: r.price for r in merged}
    assert by_date["2026-08-03"] == 99999
    assert by_date["2026-08-02"] == 13220
