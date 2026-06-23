"""Pure Arabic-first parsers for budgets, hiring rates, and relative timestamps.

These functions are I/O-free and deterministic: ``now`` is injected, never read from the clock,
so they are trivially testable. Per constitution they fail closed — any unrecognised or
unparseable input yields ``None`` rather than a guess.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------

# Built once at import: a str.translate table that folds Arabic-Indic (U+0660..U+0669)
# and Persian (U+06F0..U+06F9) digits to ASCII, maps the Arabic numeric separators,
# and strips bidi marks / tatweel / NBSP.
_TRANSLATE: dict[int, str | None] = {}
for _i in range(10):
    _TRANSLATE[0x0660 + _i] = str(_i)  # Arabic-Indic digits
    _TRANSLATE[0x06F0 + _i] = str(_i)  # Persian (extended Arabic-Indic) digits
_TRANSLATE[0x066C] = None   # Arabic thousands separator -> remove
_TRANSLATE[0x066B] = "."    # Arabic decimal separator -> "."
_TRANSLATE[0x066A] = "%"    # Arabic percent sign -> "%"
_TRANSLATE[0x0640] = None   # tatweel (kashida) -> remove
_TRANSLATE[0x00A0] = " "    # NBSP -> space
for _cp in (0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E):
    _TRANSLATE[_cp] = None  # bidi marks/embeddings -> remove
for _cp in (*range(0x064B, 0x0653), 0x0670):
    _TRANSLATE[_cp] = None  # Arabic harakat/tanwin + superscript alef -> remove (diacritic-insensitive)

_WS_RE = re.compile(r"\s+")
_DIGIT_COMMA_DIGIT_RE = re.compile(r"(?<=\d),(?=\d)")


def normalize_text(s: str) -> str:
    """NFKC-normalise, fold Arabic/Persian digits, and tidy separators/whitespace."""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_TRANSLATE)
    s = _DIGIT_COMMA_DIGIT_RE.sub("", s)  # ASCII thousands "," between digits -> remove
    s = _WS_RE.sub(" ", s)
    return s.strip()


# ---------------------------------------------------------------------------
# parse_budget
# ---------------------------------------------------------------------------

_NUM = r"\d+(?:\.\d+)?"
_CCY_SYM = r"[$\s]*(?:دولار)?\s*"  # optional currency symbol/word around the second number
# One number, or two separated by a dash variant or the Arabic word "إلى"/"الى".
_BUDGET_RE = re.compile(
    rf"({_NUM})\s*(?:[-–—]|إلى|الى)\s*{_CCY_SYM}({_NUM})|({_NUM})"
)


def _to_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _currency_of(s: str) -> str | None:
    if "$" in s or "دولار" in s:
        return "USD"
    return None  # fail-closed: do not assume USD


def parse_budget(s: str) -> tuple[Decimal | None, Decimal | None, str | None]:
    """Return (min, max, currency). One number => min == max; no number => (None, None, ccy)."""
    s = normalize_text(s)
    currency = _currency_of(s)
    m = _BUDGET_RE.search(s)
    if m is None:
        return (None, None, currency)
    if m.group(3) is not None:  # single-number branch
        one = _to_decimal(m.group(3))
        return (one, one, currency)
    lo = _to_decimal(m.group(1))
    hi = _to_decimal(m.group(2))
    return (lo, hi, currency)


# ---------------------------------------------------------------------------
# parse_hiring_rate
# ---------------------------------------------------------------------------

_RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_hiring_rate(s: str) -> float | None:
    """Percent as float, or None when "not yet computed" (يحسب) or unparseable."""
    s = normalize_text(s)
    if "يحسب" in s:  # "لم يحسب", "لم يحسب بعد", spacing variants -> unknown
        return None
    m = _RATE_RE.search(s)
    if m is None:
        return None
    try:
        return float(m.group(1))
    except ValueError:  # pragma: no cover - _RATE_RE only ever captures float-parseable digits
        return None


# ---------------------------------------------------------------------------
# parse_relative_time
# ---------------------------------------------------------------------------

# Unit stems mapped to (seconds, implicit_count). Order matters: more specific (longer)
# stems first so "أسبوع" is not pre-empted by a shorter prefix, and duals before singulars.
# Dual forms ("ساعتين", "يومين", …) carry implicit count 2 since they already mean "two".
_UNITS: tuple[tuple[str, int, int], ...] = (
    ("ثانيتين", 1, 2), ("ثواني", 1, 1), ("ثوان", 1, 1), ("ثاني", 1, 1),
    ("دقيقتين", 60, 2), ("دقائق", 60, 1), ("دقيق", 60, 1),
    ("ساعتين", 3600, 2), ("ساع", 3600, 1),
    ("أسبوعين", 604800, 2), ("أسابيع", 604800, 1), ("أسبوع", 604800, 1),
    ("يومين", 86400, 2), ("أيام", 86400, 1), ("يوم", 86400, 1),
    ("شهرين", 2592000, 2), ("أشهر", 2592000, 1), ("شهور", 2592000, 1), ("شهر", 2592000, 1),
    ("سنتين", 31536000, 2), ("سنوات", 31536000, 1), ("سنة", 31536000, 1),
    ("عامين", 31536000, 2), ("أعوام", 31536000, 1), ("عام", 31536000, 1),
)

_PREFIX_RE = re.compile(r"^\s*(?:منذ|قبل)\s*")
_REL_NUM_RE = re.compile(r"(\d+)")


def parse_relative_time(s: str, now_utc: datetime) -> datetime | None:
    """Resolve "منذ N <unit>" against ``now_utc``; unrecognised => None.

    Fail-closed (constitution VII): only an explicit *past* anchor (منذ / قبل) is resolved. A
    future direction (بعد / خلال / غدا …) or a bare unit with no anchor is ambiguous, so we return
    None rather than guess a past offset in the wrong direction — the authoritative source is the
    ``<time datetime>`` attribute; this relative parser is only a best-effort fallback.
    """
    s = normalize_text(s)
    anchor = _PREFIX_RE.match(s)
    if anchor is None:  # no منذ / قبل -> do not guess a direction
        return None
    s = s[anchor.end():]
    m = _REL_NUM_RE.search(s)
    for stem, unit, dual in _UNITS:
        if stem in s:
            count = int(m.group(1)) if m else dual  # explicit number wins; else stem's own count
            return now_utc - timedelta(seconds=count * unit)
    return None
