"""Tests for IBJA PDF text parsers (no network)."""

from __future__ import annotations

from datetime import date

from scripts.backfill_ibja import (
    parse_30day_pdf_text,
    parse_daily_report_text,
    parse_ibja_date,
    per10g_to_per_gram,
)


def test_parse_ibja_date() -> None:
    assert parse_ibja_date("26-Aug-26") == date(2026, 8, 26)
    assert parse_ibja_date("25/08/2026") == date(2026, 8, 25)


def test_per10g_to_per_gram() -> None:
    # 148533 / 10 = 14853.3
    assert per10g_to_per_gram(148533) == 14853.3


def test_parse_30day_pdf_row() -> None:
    text = (
        "26-Aug-26 161431 161337 160785 160691 147871 147785 "
        "121073 121003 94437 94382 244147 242959\n"
        "22-Aug-26 SAT\n"
        "21-Aug-26 159499 160620 158860 159977 146101 147128 "
        "119624 120465 93307 93963 244389 246630\n"
    )
    rows = parse_30day_pdf_text(text)
    assert len(rows) == 2
    assert rows[0] == (date(2026, 8, 26), 14778.5)  # PM 147785 / 10
    assert rows[1][0] == date(2026, 8, 21)
    assert rows[1][1] == 14712.8  # PM 147128 / 10


def test_parse_daily_report_916() -> None:
    text = """
    Daily Bullion Physical Market Report Date: 25 th August 2026
    Description Purity AM PM
    Gold 999 162603 162154
    Gold 995 161952 161505
    Gold 916 148944 148533
    Gold 750 121952 121616
    """
    row = parse_daily_report_text(text, fallback_date=date(2026, 8, 25))
    assert row is not None
    assert row[0] == date(2026, 8, 25)
    assert row[1] == 14853.3  # PM / 10
