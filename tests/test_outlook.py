"""Outlook computation tests (no live network)."""

from __future__ import annotations

from datetime import date, timedelta

from src.fx import UsdInrSnapshot
from src.history import HistoryRecord
from src.news import NewsHeadline, _is_reliable, news_sentiment_score
from src.outlook import compute_outlook, format_outlook_block
from src.statistics import compute_stats


def _records(end: date, prices: list[float]) -> list[HistoryRecord]:
    start = end - timedelta(days=len(prices) - 1)
    return [
        HistoryRecord(
            date=(start + timedelta(days=i)).isoformat(),
            price=p,
            source="test",
            fetched_at=f"{(start + timedelta(days=i)).isoformat()}T12:00:00+05:30",
        )
        for i, p in enumerate(prices)
    ]


def test_reliable_source_detection() -> None:
    assert _is_reliable("Reuters")
    assert _is_reliable("Bloomberg Markets")
    assert not _is_reliable("Random Blog")


def test_news_sentiment_bullish() -> None:
    headlines = [
        NewsHeadline("Gold prices surge on safe haven demand", "Reuters", "", "", "bullish", True),
        NewsHeadline("Bullion rally continues", "CNBC", "", "", "bullish", True),
    ]
    score, label = news_sentiment_score(headlines)
    assert score > 0
    assert "bullish" in label
    assert "recognised" in label


def test_compute_outlook_with_mocks() -> None:
    today = date(2026, 8, 26)
    # Rising trend, not at extreme
    prices = [14800 + i * 8 for i in range(30)]
    records = _records(today, prices)
    stats = compute_stats(records, as_of=today)
    usd_inr = UsdInrSnapshot(rate=83.5, as_of="2026-08-26", daily_change_pct=0.12, change_7d_pct=0.35)
    headlines = [
        NewsHeadline("Gold rises on weaker dollar", "Reuters", "https://example.com", "", "bullish", True),
    ]
    outlook = compute_outlook(records, stats, as_of=today, usd_inr=usd_inr, headlines=headlines)
    assert outlook.bias in {"SLIGHTLY_UP", "NEUTRAL", "UNCLEAR"}
    assert outlook.usd_inr_rate == 83.5
    assert outlook.band_low is not None
    assert outlook.band_high is not None
    assert outlook.news[0]["reliable"] is True
    block = format_outlook_block(outlook)
    assert "Indicative outlook" in block
    assert "USD/INR" in block
    assert "★" in block
