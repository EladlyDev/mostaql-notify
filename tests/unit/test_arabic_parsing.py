"""Table-driven tests for the pure Arabic parsers (parsing/arabic.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mostaql_notifier.parsing.arabic import (
    normalize_text,
    parse_budget,
    parse_hiring_rate,
    parse_relative_time,
)

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- normalize_text
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("٢٥٠", "250"),                    # Arabic-Indic digits -> 250
        ("۲۵۰", "250"),                    # Persian (extended) digits -> 250
        ("1٬000", "1000"),                           # Arabic thousands sep U+066C removed
        ("12٫5", "12.5"),                            # Arabic decimal sep U+066B -> "."
        ("50٪", "50%"),                              # Arabic percent U+066A -> "%"
        ("10,000", "10000"),                              # ASCII comma between digits removed
        ("a‏‎ b", "a b"),                       # RLM/LRM bidi marks stripped
        ("ــabc", "abc"),                       # tatweel U+0640 removed
        ("x y", "x y"),                              # NBSP U+00A0 -> space
        ("  spaced   out  ", "spaced out"),               # whitespace collapsed + trimmed
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


# --------------------------------------------------------------------------- parse_budget
@pytest.mark.parametrize(
    "raw, lo, hi, ccy",
    [
        ("$250.00 - $500.00", Decimal("250.00"), Decimal("500.00"), "USD"),
        ("$10,000.00", Decimal("10000.00"), Decimal("10000.00"), "USD"),
        ("$25.00", Decimal("25.00"), Decimal("25.00"), "USD"),
        ("250 إلى 500 دولار",  # "250 إلى 500 دولار"
         Decimal("250"), Decimal("500"), "USD"),
        ("250 الى 500", Decimal("250"), Decimal("500"), None),  # "الى", no ccy
        ("100 – 200", Decimal("100"), Decimal("200"), None),  # en-dash
        ("100 — 200", Decimal("100"), Decimal("200"), None),  # em-dash
        ("٢٥٠", Decimal("250"), Decimal("250"), None),  # Arabic-Indic 250
        ("۲۵۰", Decimal("250"), Decimal("250"), None),  # Persian 250
        ("غير محدد", None, None, None),  # "غير محدد"
        ("دولار فقط", None, None, "USD"),  # "دولار فقط"
    ],
)
def test_parse_budget(raw: str, lo, hi, ccy) -> None:
    assert parse_budget(raw) == (lo, hi, ccy)


def test_parse_budget_unrecognized_returns_none_pair() -> None:
    assert parse_budget("لا يوجد") == (None, None, None)  # "لا يوجد"


# --------------------------------------------------------------------------- parse_hiring_rate
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("50.00%", 50.0),
        ("0.00%", 0.0),                              # distinct from None
        ("75 %", 75.0),
        ("100%", 100.0),
        ("٥٠%", 50.0),                     # Arabic-Indic digits "٥٠%"
        ("لم يحسب", None),  # "لم يحسب"
        ("لم يحسب بعد", None),  # "لم يحسب بعد"
        ("بدون نسبة", None),  # "بدون نسبة" (unparseable)
    ],
)
def test_parse_hiring_rate(raw: str, expected) -> None:
    assert parse_hiring_rate(raw) == expected


def test_parse_hiring_rate_zero_is_not_none() -> None:
    result = parse_hiring_rate("0.00%")
    assert result == 0.0
    assert result is not None


@pytest.mark.parametrize(
    "raw",
    [
        "لم يحسب",            # "لم يحسب"
        "لم يحسب بعد",  # "لم يحسب بعد"
        "لم يُحسَب بعد",  # diacritic variant (harakat) — guard must still fire
    ],
)
def test_parse_hiring_rate_yuhsab_is_none(raw: str) -> None:
    assert parse_hiring_rate(raw) is None


# --------------------------------------------------------------------------- parse_relative_time
@pytest.mark.parametrize(
    "raw, seconds",
    [
        ("منذ 12 دقيقة", 12 * 60),   # "منذ 12 دقيقة"
        ("منذ ساعتين", 2 * 3600),  # "منذ ساعتين"
        ("منذ ساعة", 3600),               # "منذ ساعة"
        ("منذ 3 ساعات", 3 * 3600),   # "منذ 3 ساعات"
        ("منذ يوم", 86400),                    # "منذ يوم"
        ("منذ يومين", 2 * 86400),    # "منذ يومين"
        ("منذ شهرين", 2 * 2592000),  # "منذ شهرين"
        ("منذ أسبوع", 604800),       # "منذ أسبوع"
        ("منذ ثانيتين", 2),  # "منذ ثانيتين"
        ("قبل 5 دقائق", 5 * 60),     # "قبل 5 دقائق"
        ("منذ عامين", 2 * 31536000),  # "منذ عامين"
        ("منذ سنة", 31536000),                 # "منذ سنة"
    ],
)
def test_parse_relative_time(raw: str, seconds: int) -> None:
    assert parse_relative_time(raw, NOW) == NOW - timedelta(seconds=seconds)


def test_parse_relative_time_arabic_indic_number() -> None:
    # "منذ ١٢ دقيقة" -> 12 minutes
    raw = "منذ ١٢ دقيقة"
    assert parse_relative_time(raw, NOW) == NOW - timedelta(minutes=12)


@pytest.mark.parametrize(
    "raw",
    [
        "كلام غير معروف",  # gibberish
        "منذ",   # "منذ" with no unit
        "غدا",   # "غدا" (tomorrow) — not a past offset
        "",
    ],
)
def test_parse_relative_time_unrecognized_returns_none(raw: str) -> None:
    assert parse_relative_time(raw, NOW) is None
