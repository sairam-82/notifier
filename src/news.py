"""Global gold-related headlines via public RSS feeds (no API key)."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import quote_plus

import requests

from src import config

logger = logging.getLogger(__name__)

# Google News RSS — aggregates Reuters, Bloomberg, CNBC, etc.
GOLD_NEWS_RSS = (
    "https://news.google.com/rss/search?q="
    + quote_plus("gold price OR gold market OR bullion")
    + "&hl=en-US&gl=US&ceid=US:en"
)

BULLISH = re.compile(
    r"\b("
    r"surge|rally|soar|jump|rise|rising|gain|gains|record high|safe.?haven|"
    r"geopolitical|inflation|rate cut|weaker dollar|demand rise|escalat"
    r")\b",
    re.I,
)
BEARISH = re.compile(
    r"\b("
    r"fall|falls|drop|drops|decline|slip|slide|plunge|lower|weak|"
    r"stronger dollar|rate hike|profit.?taking|correction|retreat"
    r")\b",
    re.I,
)


# Recognised publishers (Google News aggregates these globally).
TRUSTED_SOURCES = frozenset(
    s.lower()
    for s in (
        "Reuters",
        "Bloomberg",
        "CNBC",
        "Financial Times",
        "Wall Street Journal",
        "MarketWatch",
        "Kitco",
        "Investing.com",
        "Economic Times",
        "Moneycontrol",
        "Business Standard",
        "Livemint",
        "The Hindu BusinessLine",
        "BBC",
        "Associated Press",
        "AP News",
    )
)


def _is_reliable(source: str, title: str = "") -> bool:
    blob = f"{source} {title}".lower()
    return any(name in blob for name in TRUSTED_SOURCES)


@dataclass
class NewsHeadline:
    title: str
    source: str
    link: str
    published: str
    tone: str  # bullish | bearish | neutral
    reliable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _tone(title: str) -> str:
    b = len(BULLISH.findall(title))
    s = len(BEARISH.findall(title))
    if b > s:
        return "bullish"
    if s > b:
        return "bearish"
    return "neutral"


def fetch_gold_headlines(limit: int = 5) -> list[NewsHeadline]:
    """Fetch recent global gold headlines; returns empty list on failure."""
    try:
        logger.info("Fetching gold news RSS")
        resp = requests.get(
            GOLD_NEWS_RSS,
            timeout=config.HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": config.HTTP_USER_AGENT},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []
        out: list[NewsHeadline] = []
        for item in channel.findall("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            source_el = item.find("source")
            if title_el is None or not (title_el.text or "").strip():
                continue
            title = (title_el.text or "").strip()
            # Google News titles often "Headline - Publisher"
            source = (source_el.text if source_el is not None else "") or "News"
            if " - " in title and source == "News":
                parts = title.rsplit(" - ", 1)
                if len(parts) == 2:
                    title, source = parts[0].strip(), parts[1].strip()
            out.append(
                NewsHeadline(
                    title=title[:200],
                    source=source[:80],
                    link=(link_el.text or "").strip() if link_el is not None else "",
                    published=(pub_el.text or "").strip() if pub_el is not None else "",
                    tone=_tone(title),
                    reliable=_is_reliable(source, title),
                )
            )
            if len(out) >= limit * 2:
                break
        # Prefer headlines from recognised global/India finance publishers.
        out.sort(key=lambda h: (not h.reliable, h.title))
        out = out[:limit]
        logger.info("Gold news headlines: %d (%d reliable)", len(out), sum(h.reliable for h in out))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gold news fetch failed: %s", exc)
        return []


def news_sentiment_score(headlines: list[NewsHeadline]) -> tuple[float, str]:
    """Simple headline tone score in roughly -20..+20."""
    if not headlines:
        return 0.0, "No recent headlines fetched"
    bull = sum(1 for h in headlines if h.tone == "bullish")
    bear = sum(1 for h in headlines if h.tone == "bearish")
    score = (bull - bear) * 5.0
    score = max(-20.0, min(20.0, score))
    if bull > bear:
        label = f"Global headlines lean bullish ({bull}/{len(headlines)})"
    elif bear > bull:
        label = f"Global headlines lean bearish ({bear}/{len(headlines)})"
    else:
        label = "Global headlines mixed/neutral"
    rel = sum(1 for h in headlines if h.reliable)
    if rel:
        label += f" · {rel} from recognised sources"
    return score, label
