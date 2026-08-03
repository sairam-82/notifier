"""Scraping orchestration and price validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src import config
from src.providers.base import GoldPriceProvider, PriceQuote

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    ok: bool
    reason: str
    suspicious: bool = False


def validate_price(
    quote: PriceQuote,
    previous_price: Optional[float] = None,
) -> ValidationResult:
    """Validate scraped financial data before persistence."""
    price = quote.price

    if price is None:  # type: ignore[comparison-overlap]
        return ValidationResult(False, "price is None", suspicious=True)
    if not isinstance(price, (int, float)):
        return ValidationResult(False, f"price not numeric: {type(price)}", suspicious=True)
    if price != price:  # NaN
        return ValidationResult(False, "price is NaN", suspicious=True)
    if price <= 0:
        return ValidationResult(False, f"price not positive: {price}", suspicious=True)
    if price < config.MIN_PRICE_INR or price > config.MAX_PRICE_INR:
        return ValidationResult(
            False,
            f"price {price} outside configured range "
            f"[{config.MIN_PRICE_INR}, {config.MAX_PRICE_INR}]",
            suspicious=True,
        )

    if previous_price is not None and previous_price > 0:
        change_pct = abs(price - previous_price) / previous_price * 100.0
        if change_pct > config.MAX_DAILY_CHANGE_PERCENT:
            return ValidationResult(
                False,
                f"suspicious daily change {change_pct:.2f}% "
                f"(>{config.MAX_DAILY_CHANGE_PERCENT}%) vs previous {previous_price}",
                suspicious=True,
            )

    return ValidationResult(True, "ok", suspicious=False)


def fetch_and_validate(
    provider: GoldPriceProvider,
    previous_price: Optional[float] = None,
) -> tuple[Optional[PriceQuote], ValidationResult]:
    logger.info("Fetch started via provider=%s", provider.name)
    quote = provider.fetch_current_price()
    logger.info(
        "Extracted price=%.2f strategy=%s source=%s",
        quote.price,
        quote.strategy,
        quote.source,
    )
    result = validate_price(quote, previous_price=previous_price)
    logger.info(
        "Validation result: ok=%s suspicious=%s reason=%s",
        result.ok,
        result.suspicious,
        result.reason,
    )
    if not result.ok:
        return None, result
    return quote, result
