"""Tests for Goodreturns HTML parsing (offline fixtures only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.providers.goodreturns import GoodReturnsProvider, parse_inr_amount
from src.scraper import validate_price

FIXTURE = Path(__file__).parent / "fixtures" / "goodreturns_sample.html"


@pytest.fixture
def provider() -> GoodReturnsProvider:
    html = FIXTURE.read_text(encoding="utf-8")
    return GoodReturnsProvider(html=html)


def test_extract_hyderabad_22k_price(provider: GoodReturnsProvider) -> None:
    quote = provider.fetch_current_price()
    assert quote.price == 13220
    assert quote.karat == "22K"
    assert quote.city == "Hyderabad"
    assert quote.source == "goodreturns"
    assert quote.strategy == "price_card_22k_id"


def test_extract_historical_table(provider: GoodReturnsProvider) -> None:
    rows = provider.fetch_historical_prices()
    assert len(rows) == 10
    assert rows[0].date.isoformat() == "2026-08-03"
    assert rows[0].price == 13220
    assert rows[-1].date.isoformat() == "2026-07-25"
    assert rows[-1].price == 13285
    # Ensure we did not pick 24K column (14422)
    assert all(r.price < 14000 for r in rows)


def test_parse_inr_with_change_annotation() -> None:
    assert parse_inr_amount("₹13,220 (-35)") == 13220
    assert parse_inr_amount("₹13,255 (+25)") == 13255


def test_invalid_missing_price() -> None:
    html = "<html><body><p>No gold prices here</p></body></html>"
    provider = GoodReturnsProvider(html=html)
    with pytest.raises(ValueError, match="Unable to extract"):
        provider.fetch_current_price()


def test_unexpected_html_wrong_karat_only() -> None:
    html = """
    <html><body>
      <span id="24K-price">₹14,422</span>
      <span id="18K-price">₹10,816</span>
      <table><tr><th>Gram</th><th>24K</th><th>18K</th></tr>
      <tr><td>1</td><td>₹14,422</td><td>₹10,816</td></tr></table>
    </body></html>
    """
    provider = GoodReturnsProvider(html=html)
    with pytest.raises(ValueError):
        provider.fetch_current_price()


def test_validation_rejects_non_positive() -> None:
    provider = GoodReturnsProvider(html=FIXTURE.read_text(encoding="utf-8"))
    quote = provider.fetch_current_price()
    bad = quote.__class__(
        price=-1,
        currency=quote.currency,
        karat=quote.karat,
        city=quote.city,
        unit=quote.unit,
        source=quote.source,
        fetched_at=quote.fetched_at,
        strategy=quote.strategy,
    )
    result = validate_price(bad)
    assert result.ok is False
    assert result.suspicious is True


def test_validation_rejects_large_jump() -> None:
    provider = GoodReturnsProvider(html=FIXTURE.read_text(encoding="utf-8"))
    quote = provider.fetch_current_price()
    result = validate_price(quote, previous_price=5000)
    assert result.ok is False
    assert "suspicious daily change" in result.reason


def test_js_strategy_fallback() -> None:
    html = """
    <html><body>
    <script>
      let currentMetalPrices = { '24': 14422, '22': 13220, '18': 10816 };
    </script>
    </body></html>
    """
    quote = GoodReturnsProvider(html=html).fetch_current_price()
    assert quote.price == 13220
    assert quote.strategy == "js_current_metal_prices"
