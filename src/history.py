"""Historical price storage in JSON (no database)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from src import config

logger = logging.getLogger(__name__)


@dataclass
class HistoryRecord:
    date: str  # YYYY-MM-DD in Asia/Kolkata calendar
    price: float
    source: str
    fetched_at: str  # ISO-8601 with offset

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HistoryRecord":
        return cls(
            date=str(data["date"]),
            price=float(data["price"]),
            source=str(data.get("source", "unknown")),
            fetched_at=str(data.get("fetched_at", "")),
        )


class HistoryStore:
    """One canonical price per calendar day; upserts same-day updates."""

    def __init__(self, path: Path = config.HISTORY_PATH) -> None:
        self.path = path

    def load(self) -> list[HistoryRecord]:
        if not self.path.exists():
            logger.info("History file missing; starting empty: %s", self.path)
            return []
        with self.path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, list):
            raise ValueError(f"history.json must be a list, got {type(raw)}")
        records = [HistoryRecord.from_dict(item) for item in raw]
        records.sort(key=lambda r: r.date)
        return records

    def save(self, records: list[HistoryRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(records, key=lambda r: r.date)
        payload = [r.to_dict() for r in ordered]
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        logger.info("History saved: %d records -> %s", len(ordered), self.path)

    def upsert(
        self,
        day: date,
        price: float,
        source: str,
        fetched_at: datetime,
    ) -> tuple[list[HistoryRecord], bool, bool]:
        """
        Insert or update the record for ``day``.

        Returns (records, changed, created_new).
        """
        records = self.load()
        day_str = day.isoformat()
        fetched_iso = fetched_at.isoformat()
        for idx, rec in enumerate(records):
            if rec.date == day_str:
                if rec.price == price and rec.source == source:
                    # Refresh fetched_at only if price unchanged? Still count as update of metadata.
                    if rec.fetched_at == fetched_iso:
                        logger.info("History not updated (identical record for %s)", day_str)
                        return records, False, False
                    records[idx] = HistoryRecord(
                        date=day_str,
                        price=price,
                        source=source,
                        fetched_at=fetched_iso,
                    )
                    logger.info("History metadata refreshed for %s", day_str)
                    return records, True, False
                records[idx] = HistoryRecord(
                    date=day_str,
                    price=price,
                    source=source,
                    fetched_at=fetched_iso,
                )
                logger.info(
                    "History updated existing day %s: %.2f -> %.2f",
                    day_str,
                    rec.price,
                    price,
                )
                return records, True, False

        records.append(
            HistoryRecord(
                date=day_str,
                price=price,
                source=source,
                fetched_at=fetched_iso,
            )
        )
        logger.info("History created new day %s price=%.2f", day_str, price)
        return records, True, True

    def merge_bootstrap(self, items: list[tuple[date, float, str]]) -> tuple[list[HistoryRecord], int]:
        """
        Import historical daily prices without inventing gaps.

        Does not overwrite an existing day's price if already present
        (scheduled scrape is authoritative for today; bootstrap fills gaps).
        Returns (records, num_added).
        """
        records = self.load()
        by_date = {r.date: r for r in records}
        added = 0
        tz = ZoneInfo(config.TIMEZONE)
        for d, price, source in items:
            key = d.isoformat()
            if key in by_date:
                continue
            # Use noon IST as synthetic fetched_at for bootstrap rows
            fetched = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=tz)
            by_date[key] = HistoryRecord(
                date=key,
                price=float(price),
                source=source,
                fetched_at=fetched.isoformat(),
            )
            added += 1
        merged = sorted(by_date.values(), key=lambda r: r.date)
        logger.info("Bootstrap merge: added=%d total=%d", added, len(merged))
        return merged, added

    def get_previous(self, records: list[HistoryRecord], day: date) -> Optional[HistoryRecord]:
        day_str = day.isoformat()
        prior = [r for r in records if r.date < day_str]
        return prior[-1] if prior else None

    def get_for_day(self, records: list[HistoryRecord], day: date) -> Optional[HistoryRecord]:
        day_str = day.isoformat()
        for r in records:
            if r.date == day_str:
                return r
        return None
