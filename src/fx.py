"""USD/INR rates via Frankfurter (free, no API key)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import requests

from src import config

logger = logging.getLogger(__name__)

FRANKFURTER_BASE = "https://api.frankfurter.dev/v1"


@dataclass
class UsdInrSnapshot:
    rate: float
    as_of: str
    daily_change_pct: Optional[float]
    change_7d_pct: Optional[float]


def fetch_usd_inr(as_of: date) -> Optional[UsdInrSnapshot]:
    """
    Fetch USD/INR and approximate 1-day / 7-day percentage changes.

    Uses ECB-sourced daily rates from Frankfurter (weekends/holidays may lag).
    """
    session = requests.Session()
    session.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    try:
        latest_url = f"{FRANKFURTER_BASE}/latest?from=USD&to=INR"
        logger.info("Fetching USD/INR: %s", latest_url)
        resp = session.get(latest_url, timeout=config.HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        latest = resp.json()
        rate = float(latest["rates"]["INR"])
        rate_date = str(latest.get("date", as_of.isoformat()))

        daily_pct = None
        d1 = date.fromisoformat(rate_date) - timedelta(days=1)
        prev = _rate_on(session, d1)
        if prev and prev > 0:
            daily_pct = round((rate - prev) / prev * 100.0, 3)

        d7 = date.fromisoformat(rate_date) - timedelta(days=7)
        week = _rate_on(session, d7)
        week_pct = None
        if week and week > 0:
            week_pct = round((rate - week) / week * 100.0, 3)

        return UsdInrSnapshot(
            rate=round(rate, 4),
            as_of=rate_date,
            daily_change_pct=daily_pct,
            change_7d_pct=week_pct,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("USD/INR fetch failed: %s", exc)
        return None


def _rate_on(session: requests.Session, day: date) -> Optional[float]:
    """Single-day USD/INR; walks back up to 5 calendar days for holidays."""
    for offset in range(6):
        d = day - timedelta(days=offset)
        url = f"{FRANKFURTER_BASE}/{d.isoformat()}?from=USD&to=INR"
        try:
            resp = session.get(url, timeout=config.HTTP_TIMEOUT_SECONDS)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            return float(data["rates"]["INR"])
        except Exception:
            continue
    return None
