"""
Optional live smoke check against Goodreturns.

Not run in default pytest suite (network-dependent).

Usage:
  python scripts/live_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.providers.goodreturns import GoodReturnsProvider  # noqa: E402
from src.scraper import validate_price  # noqa: E402


def main() -> int:
    provider = GoodReturnsProvider()
    quote = provider.fetch_current_price()
    hist = provider.fetch_historical_prices()
    result = validate_price(quote)
    print(f"price={quote.price} strategy={quote.strategy} validation={result.reason}")
    print(f"history_rows={len(hist)}")
    if hist:
        print(f"history_span={hist[-1].date} .. {hist[0].date}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
