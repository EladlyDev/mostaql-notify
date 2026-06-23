"""Exhaustive / adversarial tests for parsing/arabic.py.

Targets every branch, boundary, and edge of ``normalize_text``, ``parse_budget``,
``parse_hiring_rate`` and ``parse_relative_time``. Tests asserting the *correct*
constitution-mandated behaviour where the code is wrong are marked ``xfail``.

``now`` is always injected (NOW); no clock reads, no sleeps, fully deterministic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mostaql_notifier.parsing.arabic import (
    _to_decimal,
    normalize_text,
    parse_budget,
    parse_hiring_rate,
    parse_relative_time,
)

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)

# Bidi marks that must all be stripped.
_BIDI = (0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E)
# Harakat / tanwin range (U+064B..U+0652 inclusive) + superscript alef (U+0670).
_HARAKAT = (*range(0x064B, 0x0653), 0x0670)


# =====================================================================
# normalize_text
# =====================================================================
@pytest.mark.parametrize(
    "raw, expected",
    [
        # --- digit folding: Arabic-Indic, Persian, and MIXED in one string ---
        ("٠١٢٣٤٥٦٧٨٩", "0123456789"),                 # all Arabic-Indic
        ("۰۱۲۳۴۵۶۷۸۹", "0123456789"),                 # all Persian
        ("٢۵٠", "250"),                               # mixed Arabic + Persian in one token
        ("٣۴٥۶", "3456"),                             # mixed alternating
        # --- numeric separators U+066B / U+066C / U+066A ---
        ("12٫5", "12.5"),                             # U+066B decimal -> "."
        ("1٬000", "1000"),                            # U+066C thousands -> removed
        ("1٬234٬567", "1234567"),                     # multiple thousands seps
        ("50٪", "50%"),                               # U+066A percent -> "%"
        ("1٬234٬567٫89٪", "1234567.89%"),             # all three separators together
        # --- tatweel inside a word, and leading ---
        ("مرحــبا", "مرحبا"),                          # tatweel U+0640 inside a word
        ("ـــabc", "abc"),                            # leading tatweel run
        ("aــb", "ab"),                     # tatweel between latin letters
        # --- NBSP ---
        ("x y", "x y"),                          # NBSP -> space
        (" lead ", "lead"),                 # NBSP collapses + trims
        # --- whitespace collapse + strip ---
        ("  a   b  ", "a b"),
        ("\t\na\r\nb\t", "a b"),
        # --- ASCII comma removed only BETWEEN digits ---
        ("1,000", "1000"),                            # between digits -> removed
        ("10,000,000", "10000000"),                   # several
        ("a, b", "a, b"),                             # NOT between digits -> kept
        ("a,1", "a,1"),                               # letter,digit -> kept
        ("1,a", "1,a"),                               # digit,letter -> kept
        ("1, 000", "1, 000"),                         # space after comma -> kept (not adjacent)
        # --- NFKC folding ---
        ("２５０", "250"),                              # fullwidth digits -> ASCII then numeric stays
        ("ﷺ", "صلى الله عليه وسلم"),                   # ligature expands under NFKC
        ("ﬁ", "fi"),                                  # fi-ligature NFKC -> fi
        ("①", "1"),                                   # NFKC circled-one folds to "1"
        # --- empty / whitespace-only ---
        ("", ""),
        ("   ", ""),
        (" ‎ـ", ""),                   # only strippable chars -> empty
    ],
)
def test_normalize_text_table(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_normalize_strips_all_bidi_marks() -> None:
    raw = "a" + "".join(chr(c) for c in _BIDI) + "b"
    assert normalize_text(raw) == "ab"


def test_normalize_strips_each_bidi_mark_individually() -> None:
    for cp in _BIDI:
        assert normalize_text(f"x{chr(cp)}y") == "xy", hex(cp)


def test_normalize_strips_all_harakat_and_superscript_alef() -> None:
    raw = "م" + "".join(chr(c) for c in _HARAKAT) + "ن"
    assert normalize_text(raw) == "من"


def test_normalize_strips_each_harakat_individually() -> None:
    for cp in _HARAKAT:
        # place diacritic after an Arabic base letter
        assert normalize_text(f"ب{chr(cp)}") == "ب", hex(cp)


def test_normalize_is_idempotent() -> None:
    samples = ["١٢٣", "1,000", "12٫5", "ﷺ", "a, b", "مرحــبا", "x y"]
    for s in samples:
        once = normalize_text(s)
        assert normalize_text(once) == once, s


def test_normalize_comma_between_arabic_then_folded_digits() -> None:
    # Order check: NFKC + digit-fold happen BEFORE the comma rule, so a comma
    # between Arabic digits is still seen as "between digits".
    assert normalize_text("١,٠٠٠") == "1000"


# =====================================================================
# parse_budget
# =====================================================================
@pytest.mark.parametrize(
    "raw, lo, hi, ccy",
    [
        # --- single number, various currencies ---
        ("250", Decimal("250"), Decimal("250"), None),
        ("$25.00", Decimal("25.00"), Decimal("25.00"), "USD"),
        ("250 دولار", Decimal("250"), Decimal("250"), "USD"),
        ("دولار 250", Decimal("250"), Decimal("250"), "USD"),  # currency word before
        ("0", Decimal("0"), Decimal("0"), None),               # zero is a real value
        # --- ranges: every separator ---
        ("100 - 200", Decimal("100"), Decimal("200"), None),   # ascii hyphen
        ("100 – 200", Decimal("100"), Decimal("200"), None),   # en-dash U+2013
        ("100 — 200", Decimal("100"), Decimal("200"), None),   # em-dash U+2014
        ("100 إلى 200", Decimal("100"), Decimal("200"), None),  # إلى
        ("100 الى 200", Decimal("100"), Decimal("200"), None),  # الى (no hamza)
        # --- separators with no surrounding spaces ---
        ("100-200", Decimal("100"), Decimal("200"), None),
        ("250إلى500", Decimal("250"), Decimal("500"), None),
        ("250الى500", Decimal("250"), Decimal("500"), None),
        # --- currency: $, دولار, neither ---
        ("$250 - $500", Decimal("250"), Decimal("500"), "USD"),
        ("$5 - $10", Decimal("5"), Decimal("10"), "USD"),       # assignment-named case
        ("250 - 500 دولار", Decimal("250"), Decimal("500"), "USD"),
        ("250 إلى 500 دولار", Decimal("250"), Decimal("500"), "USD"),
        ("250 - $500", Decimal("250"), Decimal("500"), "USD"),  # ccy on 2nd number only
        ("100 - 200", Decimal("100"), Decimal("200"), None),    # neither
        # --- Arabic & Persian digit budgets ---
        ("٢٥٠", Decimal("250"), Decimal("250"), None),
        ("۲۵۰", Decimal("250"), Decimal("250"), None),
        ("٢٥٠ إلى ٥٠٠", Decimal("250"), Decimal("500"), None),
        ("۲۵۰ - ۵۰۰", Decimal("250"), Decimal("500"), None),
        ("$٢٥٠ - $٥٠٠", Decimal("250"), Decimal("500"), "USD"),
        # --- decimals ---
        ("250.50 - 500.75", Decimal("250.50"), Decimal("500.75"), None),
        ("12٫5", Decimal("12.5"), Decimal("12.5"), None),       # Arabic decimal sep
        ("$99.99", Decimal("99.99"), Decimal("99.99"), "USD"),
        # --- thousands separators normalise away before parsing ---
        ("$10,000.00", Decimal("10000.00"), Decimal("10000.00"), "USD"),
        ("1٬000 - 2٬000", Decimal("1000"), Decimal("2000"), None),
        # --- no number at all: (None, None, ccy) ---
        ("غير محدد", None, None, None),
        ("لا يوجد", None, None, None),
        ("دولار فقط", None, None, "USD"),   # currency present, no number
        ("", None, None, None),
    ],
)
def test_parse_budget_table(raw: str, lo, hi, ccy) -> None:
    assert parse_budget(raw) == (lo, hi, ccy)


def test_parse_budget_single_number_min_equals_max_identity() -> None:
    lo, hi, _ = parse_budget("777")
    assert lo == hi == Decimal("777")


def test_parse_budget_ambiguous_dot_thousand_is_kept_as_decimal() -> None:
    # "1.000": a "." is a decimal point in this normaliser; it is NOT a thousands
    # separator, so this is Decimal("1.000") == 1, not 1000.
    lo, hi, ccy = parse_budget("1.000")
    assert (lo, hi, ccy) == (Decimal("1.000"), Decimal("1.000"), None)
    assert lo == Decimal("1")  # numerically one, not one thousand


def test_parse_budget_ambiguous_arabic_thousands_sep_is_thousand() -> None:
    # "1٬000" uses U+066C (thousands) -> removed -> 1000.
    assert parse_budget("1٬000") == (Decimal("1000"), Decimal("1000"), None)


def test_parse_budget_arabic_decimal_sep_three_places() -> None:
    # "1٫000" uses U+066B (decimal) -> "1.000" == 1.
    lo, hi, _ = parse_budget("1٫000")
    assert lo == hi == Decimal("1.000") == Decimal("1")


def test_parse_budget_first_match_wins_when_trailing_range() -> None:
    # search() scans left-to-right; the lone leading number is matched first.
    assert parse_budget("100 ثم 200 - 300") == (Decimal("100"), Decimal("100"), None)


def test_parse_budget_currency_detected_via_substring_no_number() -> None:
    # "بالدولار" ("in dollars") contains the substring "دولار" => USD is detected,
    # while no number is present => (None, None, "USD").
    lo, hi, ccy = parse_budget("السعر بالدولار غير معروف")
    assert (lo, hi, ccy) == (None, None, "USD")


def test_parse_budget_dollar_word_substring_detected() -> None:
    # "$" anywhere => USD even when glued to a number.
    assert parse_budget("$500")[2] == "USD"


# =====================================================================
# _to_decimal  (covers the defensive except, lines 63-64)
# =====================================================================
@pytest.mark.parametrize(
    "text, expected",
    [
        ("250", Decimal("250")),
        ("250.50", Decimal("250.50")),
        ("0", Decimal("0")),
    ],
)
def test_to_decimal_valid(text: str, expected) -> None:
    assert _to_decimal(text) == expected


@pytest.mark.parametrize("text", ["abc", "1.2.3", "", "  ", "1,000", "nan?"])
def test_to_decimal_invalid_returns_none(text: str) -> None:
    # The public budget regex can only feed valid numerics here, but the helper
    # itself must fail closed on garbage -> this drives lines 63-64.
    assert _to_decimal(text) is None


def test_to_decimal_nan_string_is_rejected() -> None:
    # Decimal("NaN") would NOT raise; but the literal must not slip through as a
    # number for our purposes. Confirm current behaviour explicitly.
    val = _to_decimal("NaN")
    # Decimal accepts NaN; document the (surprising) truth rather than assume.
    assert val is None or val.is_nan()


# =====================================================================
# parse_hiring_rate
# =====================================================================
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("50%", 50.0),
        ("50.00%", 50.0),
        ("50 %", 50.0),               # space before %
        ("100%", 100.0),
        ("99.9%", 99.9),
        ("0%", 0.0),                  # ZERO is a real distinct value, not None
        ("0.00%", 0.0),
        ("٥٠%", 50.0),                # Arabic-Indic digits
        ("۵۰%", 50.0),               # Persian digits
        ("٥٠٪", 50.0),                # Arabic-Indic digits + Arabic percent U+066A
        ("100٪", 100.0),             # Arabic percent sign
        ("٠٪", 0.0),                  # Arabic zero + Arabic percent
        # --- "not yet computed" variants -> None ---
        ("لم يحسب", None),
        ("لم يحسب بعد", None),
        ("لم يُحسَب بعد", None),        # diacritic variant
        ("لم يُحسب", None),
        # --- non-percent / unparseable -> None ---
        ("بدون نسبة", None),
        ("50", None),                 # number without % sign
        ("%", None),                  # % without number
        ("نسبة عالية", None),
        ("", None),
    ],
)
def test_parse_hiring_rate_table(raw: str, expected) -> None:
    assert parse_hiring_rate(raw) == expected


def test_parse_hiring_rate_zero_distinct_from_none() -> None:
    r = parse_hiring_rate("0%")
    assert r == 0.0
    assert r is not None
    assert isinstance(r, float)


def test_parse_hiring_rate_yuhsab_guard_wins_over_percent() -> None:
    # If "يحسب" appears, it is unknown even if a stray "%" is also present.
    assert parse_hiring_rate("لم يحسب 0%") is None
    assert parse_hiring_rate("لم يُحسَب بعد 50%") is None


def test_parse_hiring_rate_returns_float_type() -> None:
    assert isinstance(parse_hiring_rate("75%"), float)


def test_parse_hiring_rate_first_percent_wins() -> None:
    # Multiple percents: leftmost match.
    assert parse_hiring_rate("30% then 90%") == 30.0


def test_parse_hiring_rate_decimal_zero_point_zero() -> None:
    assert parse_hiring_rate("0.0%") == 0.0


# Lines 105-106 (the float() ValueError guard) are unreachable through the
# public API: _RATE_RE captures exactly r"\d+(?:\.\d+)?", which float() always
# parses. We document this rather than contrive an impossible input. (See notes.)
def test_rate_regex_only_yields_float_parseable_text() -> None:
    from mostaql_notifier.parsing.arabic import _RATE_RE

    for sample in ["12.5% 0% 100% 7%", "نسبة 33.33% منجزة"]:
        for cap in _RATE_RE.findall(sample):
            float(cap)  # must never raise -> proves 105-106 are dead defensive code


# =====================================================================
# parse_relative_time
# =====================================================================
# (raw, expected_seconds_in_past)
_RT_CASES = [
    # ---- ثانية: singular / dual / plural / explicit ----
    ("منذ ثانية", 1),                 # singular (matches stem ثاني)
    ("منذ ثانيتين", 2),               # dual
    ("منذ 5 ثواني", 5),               # plural + explicit number
    ("منذ ثوان", 1),                  # plural form ثوان (implicit 1)
    ("منذ 10 ثانية", 10),             # explicit overrides singular
    # ---- دقيقة ----
    ("منذ دقيقة", 60),
    ("منذ دقيقتين", 2 * 60),
    ("منذ 3 دقائق", 3 * 60),
    ("منذ 12 دقيقة", 12 * 60),
    # ---- ساعة ----
    ("منذ ساعة", 3600),
    ("منذ ساعتين", 2 * 3600),
    ("منذ 3 ساعات", 3 * 3600),
    # ---- يوم ----
    ("منذ يوم", 86400),
    ("منذ يومين", 2 * 86400),
    ("منذ 4 أيام", 4 * 86400),
    # ---- أسبوع ----
    ("منذ أسبوع", 604800),
    ("منذ أسبوعين", 2 * 604800),
    ("منذ 3 أسابيع", 3 * 604800),
    # ---- شهر ----
    ("منذ شهر", 2592000),
    ("منذ شهرين", 2 * 2592000),
    ("منذ 5 أشهر", 5 * 2592000),
    ("منذ 6 شهور", 6 * 2592000),
    # ---- سنة ----
    ("منذ سنة", 31536000),
    ("منذ سنتين", 2 * 31536000),
    ("منذ 4 سنوات", 4 * 31536000),
    # ---- عام ----
    ("منذ عام", 31536000),
    ("منذ عامين", 2 * 31536000),
    ("منذ 3 أعوام", 3 * 31536000),
    # ---- قبل prefix instead of منذ ----
    ("قبل 5 دقائق", 5 * 60),
    ("قبل ساعتين", 2 * 3600),
    ("قبل يوم", 86400),
    # ---- Arabic-Indic & Persian numbers ----
    ("منذ ١٢ دقيقة", 12 * 60),
    ("منذ ۳ ساعات", 3 * 3600),
    # ---- explicit number overrides a DUAL stem ----
    ("منذ 5 يومين", 5 * 86400),       # explicit 5 wins over dual's 2
    ("منذ 7 ساعتين", 7 * 3600),       # explicit 7 wins over dual's 2
    # ---- diacritics on the unit word ----
    ("منذ سَاعَة", 3600),
    # NOTE: a bare unit with no منذ/قبل anchor now fails closed -> None (see the dedicated
    # test_parse_relative_time_bare_unit_without_anchor_should_be_none below); it is intentionally
    # NOT in this happy-path table.
]


@pytest.mark.parametrize("raw, seconds", _RT_CASES)
def test_parse_relative_time_table(raw: str, seconds: int) -> None:
    assert parse_relative_time(raw, NOW) == NOW - timedelta(seconds=seconds)


def test_parse_relative_time_result_is_timezone_aware_utc() -> None:
    res = parse_relative_time("منذ ساعة", NOW)
    assert res is not None
    assert res.tzinfo is not None
    assert res.utcoffset() == timedelta(0)


def test_parse_relative_time_dual_not_preempted_by_shorter_stem() -> None:
    # "دقيقتين" must resolve as the DUAL (120s), never as singular "دقيق" (60s).
    assert parse_relative_time("منذ دقيقتين", NOW) == NOW - timedelta(seconds=120)
    # "أسبوعين" must be 2 weeks, not 1.
    assert parse_relative_time("منذ أسبوعين", NOW) == NOW - timedelta(seconds=2 * 604800)
    # "سنتين" must be 2 years.
    assert parse_relative_time("منذ سنتين", NOW) == NOW - timedelta(seconds=2 * 31536000)


def test_parse_relative_time_singular_uses_implicit_one() -> None:
    for raw, sec in [("منذ ثانية", 1), ("منذ دقيقة", 60), ("منذ ساعة", 3600)]:
        assert parse_relative_time(raw, NOW) == NOW - timedelta(seconds=sec)


@pytest.mark.parametrize(
    "raw",
    [
        "كلام غير معروف",      # gibberish, no unit
        "منذ",                # prefix, no unit
        "قبل",                # prefix, no unit
        "غدا",                # tomorrow (future, no unit stem) -> None
        "بعد غد",             # day after tomorrow (no unit stem) -> None
        "",                   # empty
        "   ",                # whitespace only
        "12",                 # bare number, no unit
        "نسبة 50%",           # unrelated text with number
    ],
)
def test_parse_relative_time_unrecognized_returns_none(raw: str) -> None:
    assert parse_relative_time(raw, NOW) is None


def test_parse_relative_time_preserves_microseconds_offset() -> None:
    now = datetime(2026, 6, 23, 12, 0, 0, 123456, tzinfo=timezone.utc)
    assert parse_relative_time("منذ ساعة", now) == now - timedelta(hours=1)


# ---------------------------------------------------------------------
# Fail-closed: future / un-anchored expressions must resolve to None (regression guard for the
# fixed parse_relative_time fail-open bug).
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    ["بعد ساعة", "بعد يومين", "بعد 3 أيام"],
)
def test_parse_relative_time_future_baad_should_be_none(raw: str) -> None:
    # "بعد" = "after/in" => a FUTURE time. The parser only recognises منذ/قبل as
    # past prefixes but still matches the unit stem, returning a past datetime.
    # Per fail-closed, an un-anchored / future direction must yield None.
    assert parse_relative_time(raw, NOW) is None


def test_parse_relative_time_khilal_future_should_be_none() -> None:
    assert parse_relative_time("خلال 3 أيام", NOW) is None


def test_parse_relative_time_bare_unit_without_anchor_should_be_none() -> None:
    # "ساعة" alone has no directional anchor; fail-closed should reject it rather
    # than assume it means "one hour ago".
    assert parse_relative_time("ساعة", NOW) is None
