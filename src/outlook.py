"""
Indicative next-session outlook (NOT a price prediction).

Combines:
  - Local gold price momentum & range position
  - USD/INR (Frankfurter)
  - Global gold headline tone (Google News RSS)
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Optional

from src.fx import UsdInrSnapshot, fetch_usd_inr
from src.history import HistoryRecord
from src.news import NewsHeadline, fetch_gold_headlines, news_sentiment_score
from src.statistics import MarketStats, format_inr

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "Indicative outlook only — not financial advice. "
    "Gold prices depend on many factors; this can be wrong."
)


@dataclass
class OutlookResult:
    bias: str  # SLIGHTLY_UP | SLIGHTLY_DOWN | NEUTRAL | UNCLEAR
    bias_label: str
    confidence: str  # LOW | MEDIUM
    score: float
    band_low: Optional[float]
    band_high: Optional[float]
    usd_inr_rate: Optional[float]
    usd_inr_as_of: Optional[str]
    usd_inr_daily_pct: Optional[float]
    usd_inr_7d_pct: Optional[float]
    factors: list[str]
    news: list[dict[str, Any]]
    disclaimer: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _avg_daily_move(records: list[HistoryRecord], end: date, days: int = 14) -> Optional[float]:
    start = (end - timedelta(days=days - 1)).isoformat()
    end_s = end.isoformat()
    window = [r for r in records if start <= r.date <= end_s]
    if len(window) < 3:
        return None
    moves = [abs(window[i].price - window[i - 1].price) for i in range(1, len(window))]
    return sum(moves) / len(moves) if moves else None


def compute_outlook(
    records: list[HistoryRecord],
    stats: MarketStats,
    as_of: Optional[date] = None,
    *,
    usd_inr: Optional[UsdInrSnapshot] = None,
    headlines: Optional[list[NewsHeadline]] = None,
) -> OutlookResult:
    if as_of is None:
        as_of = date.fromisoformat(stats.as_of_date) if stats.as_of_date else date.today()

    if headlines is None:
        headlines = fetch_gold_headlines(limit=5)
    if usd_inr is None:
        usd_inr = fetch_usd_inr(as_of)

    factors: list[str] = []
    score = 0.0
    signals = 0

    today = stats.today_price
    if today is None:
        return OutlookResult(
            bias="UNCLEAR",
            bias_label="Insufficient data",
            confidence="LOW",
            score=0.0,
            band_low=None,
            band_high=None,
            usd_inr_rate=usd_inr.rate if usd_inr else None,
            usd_inr_as_of=usd_inr.as_of if usd_inr else None,
            usd_inr_daily_pct=usd_inr.daily_change_pct if usd_inr else None,
            usd_inr_7d_pct=usd_inr.change_7d_pct if usd_inr else None,
            factors=["No current gold price"],
            news=[h.to_dict() for h in headlines],
            disclaimer=DISCLAIMER,
        )

    # --- Gold 7-day momentum ---
    p7 = stats.period_7d
    if p7.change_percent is not None and p7.count >= 5:
        ch = p7.change_percent
        mom = max(-35.0, min(35.0, ch * 10.0))
        score += mom
        signals += 1
        if ch > 0.3:
            factors.append(f"7-day gold trend up ({ch:+.2f}%)")
        elif ch < -0.3:
            factors.append(f"7-day gold trend down ({ch:+.2f}%)")
        else:
            factors.append(f"7-day gold trend flat ({ch:+.2f}%)")

    # --- Range position (mean-reversion nudge) ---
    pos = stats.position_30d
    if pos is not None:
        if pos >= 85:
            score -= 12.0
            factors.append(f"Near 30D high ({pos:.0f}%) — possible pause/pullback")
            signals += 1
        elif pos <= 15:
            score += 12.0
            factors.append(f"Near 30D low ({pos:.0f}%) — possible stabilisation/bounce")
            signals += 1

    # --- USD/INR ---
    if usd_inr:
        if usd_inr.daily_change_pct is not None:
            # Rupee weaker (USD/INR up) → INR gold often up
            fx_d = max(-15.0, min(15.0, usd_inr.daily_change_pct * 80.0))
            score += fx_d
            signals += 1
            factors.append(
                f"USD/INR {usd_inr.rate:.2f} ({usd_inr.daily_change_pct:+.2f}% today)"
            )
        if usd_inr.change_7d_pct is not None:
            fx_w = max(-20.0, min(20.0, usd_inr.change_7d_pct * 60.0))
            score += fx_w
            signals += 1
            if abs(usd_inr.change_7d_pct) >= 0.05:
                direction = "weaker ₹" if usd_inr.change_7d_pct > 0 else "stronger ₹"
                factors.append(
                    f"Rupee {direction} vs USD over 7D ({usd_inr.change_7d_pct:+.2f}%)"
                )

    # --- Global news tone ---
    news_score, news_label = news_sentiment_score(headlines)
    if headlines:
        score += news_score
        signals += 1
        factors.append(news_label)

    # --- Bias mapping ---
    if signals < 2:
        bias, label, conf = "UNCLEAR", "Mixed / insufficient signals", "LOW"
    elif score >= 18:
        bias, label, conf = "SLIGHTLY_UP", "Slightly upward bias", "MEDIUM" if signals >= 3 else "LOW"
    elif score <= -18:
        bias, label, conf = "SLIGHTLY_DOWN", "Slightly downward bias", "MEDIUM" if signals >= 3 else "LOW"
    else:
        bias, label, conf = "NEUTRAL", "Neutral / sideways", "MEDIUM" if signals >= 3 else "LOW"

    # --- Indicative band ---
    avg_move = _avg_daily_move(records, as_of, days=14)
    if avg_move is None:
        avg_move = today * 0.004  # ~0.4% fallback
    band_low = round(max(today - avg_move, 0), 0)
    band_high = round(today + avg_move, 0)

    logger.info(
        "Outlook: bias=%s score=%.1f confidence=%s band=%s-%s",
        bias,
        score,
        conf,
        band_low,
        band_high,
    )

    return OutlookResult(
        bias=bias,
        bias_label=label,
        confidence=conf,
        score=round(score, 1),
        band_low=band_low,
        band_high=band_high,
        usd_inr_rate=usd_inr.rate if usd_inr else None,
        usd_inr_as_of=usd_inr.as_of if usd_inr else None,
        usd_inr_daily_pct=usd_inr.daily_change_pct if usd_inr else None,
        usd_inr_7d_pct=usd_inr.change_7d_pct if usd_inr else None,
        factors=factors,
        news=[h.to_dict() for h in headlines],
        disclaimer=DISCLAIMER,
    )


def format_outlook_block(outlook: OutlookResult) -> str:
    """Compact block for Telegram."""
    emoji = {
        "SLIGHTLY_UP": "↗️",
        "SLIGHTLY_DOWN": "↘️",
        "NEUTRAL": "➡️",
        "UNCLEAR": "❔",
    }.get(outlook.bias, "❔")
    lines = [
        f"\n🔮 Indicative outlook {emoji}",
        outlook.bias_label,
        f"Confidence: {outlook.confidence}",
    ]
    if outlook.band_low is not None and outlook.band_high is not None:
        lines.append(f"Possible range: {format_inr(outlook.band_low)} – {format_inr(outlook.band_high)}/g")
    if outlook.usd_inr_rate is not None:
        d = outlook.usd_inr_daily_pct
        w = outlook.usd_inr_7d_pct
        fx = f"USD/INR {outlook.usd_inr_rate:.2f}"
        if d is not None:
            fx += f" ({d:+.2f}% today"
            if w is not None:
                fx += f", {w:+.2f}% 7D"
            fx += ")"
        lines.append(fx)
    for f in outlook.factors[:4]:
        lines.append(f"• {f}")
    if outlook.news:
        lines.append("News:")
        for n in outlook.news[:2]:
            prefix = "★ " if n.get("reliable") else "• "
            src = n.get("source", "")
            title = n.get("title", "")[:85]
            lines.append(f"{prefix}{title}" + (f" ({src})" if src else ""))
    lines.append(f"_{outlook.disclaimer}_")
    return "\n".join(lines)
