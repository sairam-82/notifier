"""Goodreturns Hyderabad gold-rate provider."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

from src import config
from src.providers.base import GoldPriceProvider, HistoricalPrice, PriceQuote

logger = logging.getLogger(__name__)

PRICE_RE = re.compile(
    r"(?:₹|Rs\.?|INR)?\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
METAL_PRICES_JS_RE = re.compile(
    r"currentMetalPrices\s*=\s*\{([^}]+)\}",
    re.IGNORECASE | re.DOTALL,
)
KARAT_IN_JS_RE = re.compile(r"['\"]22['\"]\s*:\s*([0-9]+(?:\.[0-9]+)?)")
DATE_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})$",
    re.IGNORECASE,
)
MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_inr_amount(text: str) -> Optional[float]:
    """Parse an INR amount from text like '₹13,220' or '₹13,220 (0)'."""
    if not text:
        return None
    # Strip change annotations like "(+25)" / "(-35)" / "(0)"
    cleaned = re.sub(r"\([^)]*\)", "", text).strip()
    match = PRICE_RE.search(cleaned)
    if not match:
        return None
    number = match.group(1).replace(",", "")
    try:
        return float(number)
    except ValueError:
        return None


def parse_history_date(text: str, year_hint: Optional[int] = None) -> Optional[date]:
    """Parse dates like 'Aug 03, 2026'."""
    text = (text or "").strip()
    match = DATE_RE.match(text)
    if not match:
        return None
    month = MONTHS[match.group(1).lower()[:3]]
    day = int(match.group(2))
    year = int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


class GoodReturnsProvider(GoldPriceProvider):
    """
    Scrapes https://www.goodreturns.in/gold-rates/hyderabad.html

    Extraction strategies (tried in order for current price):
      1. span#22K-price price card
      2. JS currentMetalPrices['22']
      3. Today per-gram table (Gram=1, column 22K)
      4. Latest row of last-10-days table (22K column)

    Historical bootstrap uses the "Last 10 Days" table when present.

    Note: robots.txt User-agent:* does not disallow /gold-rates/.
    The /*-rate* disallow applies to Googlebot-News only (verified 2026-08).
    """

    name = "goodreturns"

    def __init__(
        self,
        url: str = config.SOURCE_URL,
        session: Optional[requests.Session] = None,
        html: Optional[str] = None,
    ) -> None:
        self.url = url
        self.session = session or requests.Session()
        self._html = html
        self._soup: Optional[BeautifulSoup] = None
        self._fetched_at: Optional[datetime] = None

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(config.TIMEZONE))

    def _load_html(self) -> str:
        if self._html is not None:
            self._fetched_at = self._now()
            logger.info("Using provided HTML (len=%d)", len(self._html))
            return self._html

        logger.info("Fetch started: %s", self.url)
        headers = {"User-Agent": config.HTTP_USER_AGENT, "Accept-Language": "en-IN,en;q=0.9"}
        response = self.session.get(
            self.url,
            headers=headers,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        logger.info("HTTP status: %s", response.status_code)
        response.raise_for_status()
        self._fetched_at = self._now()
        self._html = response.text
        return self._html

    def _soupify(self) -> BeautifulSoup:
        if self._soup is None:
            html = self._load_html()
            self._soup = BeautifulSoup(html, "html.parser")
        return self._soup

    def fetch_current_price(self) -> PriceQuote:
        soup = self._soupify()
        fetched_at = self._fetched_at or self._now()

        strategies = [
            ("price_card_22k_id", self._from_price_card),
            ("js_current_metal_prices", self._from_js_metal_prices),
            ("today_per_gram_table", self._from_per_gram_table),
            ("history_table_latest", self._from_history_latest),
        ]

        errors: list[str] = []
        for strategy_name, fn in strategies:
            try:
                price, raw = fn(soup)
            except Exception as exc:  # noqa: BLE001 - defensive multi-strategy
                errors.append(f"{strategy_name}: {exc}")
                logger.debug("Strategy %s failed: %s", strategy_name, exc)
                continue
            if price is None:
                errors.append(f"{strategy_name}: no value")
                continue
            logger.info(
                "Price extracted via strategy=%s source=%s price=%.2f raw=%r",
                strategy_name,
                self.name,
                price,
                raw,
            )
            return PriceQuote(
                price=price,
                currency=config.CURRENCY,
                karat=config.KARAT,
                city=config.CITY,
                unit=config.UNIT,
                source=self.name,
                fetched_at=fetched_at,
                strategy=strategy_name,
                raw_text=raw,
            )

        raise ValueError(
            "Unable to extract Hyderabad 22K gold price from Goodreturns. "
            f"Tried strategies; details: {'; '.join(errors)}"
        )

    def fetch_historical_prices(self) -> list[HistoricalPrice]:
        soup = self._soupify()
        table = self._find_history_table(soup)
        if table is None:
            logger.info("No historical table found on page")
            return []

        headers = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
        try:
            date_idx = next(i for i, h in enumerate(headers) if "DATE" in h)
            k22_idx = next(i for i, h in enumerate(headers) if h in {"22K", "22"})
        except StopIteration as exc:
            raise ValueError(f"History table missing Date/22K columns: {headers}") from exc

        results: list[HistoricalPrice] = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells or len(cells) <= max(date_idx, k22_idx):
                continue
            d = parse_history_date(cells[date_idx].get_text(" ", strip=True))
            price = parse_inr_amount(cells[k22_idx].get_text(" ", strip=True))
            if d is None or price is None:
                continue
            results.append(
                HistoricalPrice(
                    date=d,
                    price=price,
                    source=self.name,
                    strategy="history_table_10d",
                )
            )

        logger.info("Historical rows extracted: %d", len(results))
        return results

    def _from_price_card(self, soup: BeautifulSoup) -> tuple[Optional[float], str]:
        # IDs like "22K-price" are invalid in CSS selectors (leading digit),
        # so use find(id=...) instead of select_one("#22K-price").
        el = soup.find(id="22K-price")
        if el is None:
            # Fallback: find card labeled 22K
            for card in soup.select(".gr-price-card"):
                label = card.select_one(".gr-price-card-label, .gold-common-head")
                if label and re.search(r"22\s*K", label.get_text(" ", strip=True), re.I):
                    value = card.select_one(".gr-price-card-value")
                    raw = (value or card).get_text(" ", strip=True)
                    return parse_inr_amount(raw), raw
            return None, ""
        raw = el.get_text(" ", strip=True)
        return parse_inr_amount(raw), raw

    def _from_js_metal_prices(self, soup: BeautifulSoup) -> tuple[Optional[float], str]:
        for script in soup.find_all("script"):
            text = script.string or script.get_text() or ""
            block = METAL_PRICES_JS_RE.search(text)
            if not block:
                continue
            karat = KARAT_IN_JS_RE.search(block.group(0))
            if karat:
                raw = karat.group(0)
                return float(karat.group(1)), raw
        return None, ""

    def _from_per_gram_table(self, soup: BeautifulSoup) -> tuple[Optional[float], str]:
        for table in soup.find_all("table"):
            headers = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
            if "GRAM" not in headers or "22K" not in headers:
                continue
            gram_idx = headers.index("GRAM")
            k22_idx = headers.index("22K")
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if not cells or len(cells) <= max(gram_idx, k22_idx):
                    continue
                gram_text = cells[gram_idx].get_text(" ", strip=True).replace(",", "")
                if gram_text != "1":
                    continue
                raw = cells[k22_idx].get_text(" ", strip=True)
                return parse_inr_amount(raw), raw
        return None, ""

    def _from_history_latest(self, soup: BeautifulSoup) -> tuple[Optional[float], str]:
        table = self._find_history_table(soup)
        if table is None:
            return None, ""
        headers = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
        try:
            k22_idx = next(i for i, h in enumerate(headers) if h in {"22K", "22"})
        except StopIteration:
            return None, ""
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells or len(cells) <= k22_idx:
                continue
            raw = cells[k22_idx].get_text(" ", strip=True)
            price = parse_inr_amount(raw)
            if price is not None:
                return price, raw
        return None, ""

    @staticmethod
    def _find_history_table(soup: BeautifulSoup) -> Optional[Tag]:
        # Prefer table whose headers are Date / 24K / 22K
        for table in soup.find_all("table"):
            headers = [th.get_text(" ", strip=True).upper() for th in table.find_all("th")]
            if any("DATE" in h for h in headers) and "22K" in headers:
                return table
        # Heading-based fallback
        for heading in soup.find_all(["h2", "h3", "h4", "p", "div"]):
            text = heading.get_text(" ", strip=True).lower()
            if "last 10 days" in text and "gold" in text:
                table = heading.find_next("table")
                if isinstance(table, Tag):
                    return table
        return None
