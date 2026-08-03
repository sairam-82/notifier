"""Abstract gold price provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PriceQuote:
    """A single validated (or candidate) gold price observation."""

    price: float
    currency: str
    karat: str
    city: str
    unit: str
    source: str
    fetched_at: datetime
    strategy: str
    raw_text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoricalPrice:
    """A historical daily price from a provider (bootstrap)."""

    date: date
    price: float
    source: str
    strategy: str = "history_table"


class GoldPriceProvider(ABC):
    """Abstraction so the app is not coupled to one website's HTML."""

    name: str

    @abstractmethod
    def fetch_current_price(self) -> PriceQuote:
        """Fetch today's current 22K price for the configured city."""

    @abstractmethod
    def fetch_historical_prices(self) -> list[HistoricalPrice]:
        """
        Fetch any publicly exposed historical daily prices.

        May return an empty list if none are available.
        Must not invent or interpolate values.
        """
