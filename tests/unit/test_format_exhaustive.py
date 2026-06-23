"""Exhaustive, adversarial unit tests for notify.format.

Targets every branch/boundary in _budget_text, _fmt_decimal, build_project_message,
relative_since, build_health_alert and build_heartbeat. Covers previously-uncovered lines
30, 44, 58, 62, 87, 105, 131, 137-142.

No network, no clock reads: ``now`` is injected, decimals are explicit. xfail markers flag
behaviour that violates the correctness bar (truncation that emits invalid HTML).
"""
from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest

from mostaql_notifier.db.models import Client, Project
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.notify.format import (
    _MAX_LEN,
    _budget_text,
    _fmt_decimal,
    build_health_alert,
    build_heartbeat,
    build_project_message,
    html_escape,
    relative_since,
)

# A fixed, timezone-aware reference instant. We never read the wall clock inside an assertion.
NOW = utcnow()


# --------------------------------------------------------------------------- helpers


def _project(**overrides) -> Project:
    base = dict(
        mostaql_id="proj-x",
        title="عنوان",
        url="https://mostaql.com/project/proj-x",
        category="تطوير, برمجة",
        budget_min=Decimal("100"),
        budget_max=Decimal("200"),
        currency="USD",
        bids_count=3,
        posted_at=NOW - timedelta(hours=1),
        scraped_at=NOW,
        tier=1,
        raw={},
    )
    base.update(overrides)
    return Project(**base)


def _client(**overrides) -> Client:
    base = dict(
        mostaql_id="derived:deadbeef",
        name="عميل",
        hiring_rate=50.0,
        last_refreshed_at=NOW,
        first_seen_at=NOW,
        raw={},
    )
    base.update(overrides)
    return Client(**base)


# ===========================================================================
# _fmt_decimal
# ===========================================================================


def test_fmt_decimal_integral_value():
    assert _fmt_decimal(Decimal("250")) == "250"


def test_fmt_decimal_drops_trailing_zeros():
    # 250.50 -> 250.5 (one trailing zero stripped, the meaningful 5 kept)
    assert _fmt_decimal(Decimal("250.50")) == "250.5"


def test_fmt_decimal_exponent_form_is_expanded():
    # normalize() yields 2.5E+2; the integral branch (line 44 region) must re-expand to "250".
    assert _fmt_decimal(Decimal("2.5E+2")) == "250"
    assert "E" not in _fmt_decimal(Decimal("2.5E+2"))


def test_fmt_decimal_none_passes_through():
    # Line 44: None -> None (fail-closed; do not coerce to a string).
    assert _fmt_decimal(None) is None


def test_fmt_decimal_zero_is_string_zero():
    # 0 is a real, distinct value — never None, never "".
    assert _fmt_decimal(Decimal("0")) == "0"
    assert _fmt_decimal(Decimal("0.00")) == "0"


def test_fmt_decimal_large_integer_not_exponential():
    assert _fmt_decimal(Decimal("1000000")) == "1000000"


def test_fmt_decimal_negative_and_fractional():
    assert _fmt_decimal(Decimal("-250.50")) == "-250.5"
    assert _fmt_decimal(Decimal("99.99")) == "99.99"


def test_fmt_decimal_accepts_non_decimal_numeric():
    # The Numeric column can hand back ints/floats/strings depending on backend; line 45 coerces.
    assert _fmt_decimal(250) == "250"
    assert _fmt_decimal("250.50") == "250.5"


# ===========================================================================
# _budget_text
# ===========================================================================


def test_budget_text_single_value_no_dash():
    # lo == hi: a single bound, no en-dash (line 60 region).
    out = _budget_text(_project(budget_min=Decimal("250"), budget_max=Decimal("250"), currency="USD"))
    assert out == "250 USD"
    assert "–" not in out


def test_budget_text_range_uses_en_dash():
    out = _budget_text(_project(budget_min=Decimal("100"), budget_max=Decimal("500"), currency="USD"))
    assert out == "100–500 USD"


def test_budget_text_only_min_known():
    # Line 62: one bound known (max is None) -> use the min.
    out = _budget_text(_project(budget_min=Decimal("100"), budget_max=None, currency="USD"))
    assert out == "100 USD"


def test_budget_text_only_max_known():
    # Line 62: one bound known (min is None) -> use the max.
    out = _budget_text(_project(budget_min=None, budget_max=Decimal("900"), currency="USD"))
    assert out == "900 USD"


def test_budget_text_neither_is_unknown():
    # Line 58: both None -> "unknown" body.
    out = _budget_text(_project(budget_min=None, budget_max=None, currency=None))
    assert out == "unknown"


def test_budget_text_currency_blank_is_stripped():
    out = _budget_text(_project(budget_min=Decimal("100"), budget_max=Decimal("200"), currency="   "))
    assert out == "100–200"
    assert not out.endswith(" ")


def test_budget_text_currency_none_is_stripped():
    out = _budget_text(_project(budget_min=Decimal("100"), budget_max=Decimal("200"), currency=None))
    assert out == "100–200"


def test_budget_text_currency_with_padding_trimmed():
    out = _budget_text(_project(budget_min=Decimal("100"), budget_max=Decimal("200"), currency="  SAR  "))
    assert out == "100–200 SAR"


def test_budget_text_arabic_indic_safe_decimals_unchanged():
    # The formatter renders ASCII digits; budget values are already-parsed Decimals.
    out = _budget_text(_project(budget_min=Decimal("0"), budget_max=Decimal("0"), currency="USD"))
    assert out == "0 USD"  # 0 is a real, distinct value


def test_budget_text_unknown_budget_with_currency_appends_currency():
    # ADVERSARIAL: when budget is unknown but a currency is present, the output reads "unknown USD".
    # That is confusing (a unit with no number) but it is the *intended* behaviour: the unknown
    # sentinel is the body and the currency is appended unconditionally. Documenting it so a future
    # refactor that drops the currency on an unknown budget is caught.
    out = _budget_text(_project(budget_min=None, budget_max=None, currency="USD"))
    assert out == "unknown USD"


# ===========================================================================
# relative_since  (line 30 = future-clamp)
# ===========================================================================


def test_relative_since_none_is_unknown():
    assert relative_since(None, NOW) == "unknown"


def test_relative_since_future_clamps_to_zero():
    # Line 30: now < dt -> negative seconds clamped to 0 -> "0m ago" (never a negative age).
    assert relative_since(NOW + timedelta(hours=5), NOW) == "0m ago"


def test_relative_since_exactly_now_is_zero():
    assert relative_since(NOW, NOW) == "0m ago"


def test_relative_since_59_minutes():
    assert relative_since(NOW - timedelta(minutes=59), NOW) == "59m ago"


def test_relative_since_exactly_60_minutes_is_one_hour():
    assert relative_since(NOW - timedelta(minutes=60), NOW) == "1h ago"


def test_relative_since_just_under_60_seconds_is_zero_minutes():
    assert relative_since(NOW - timedelta(seconds=59), NOW) == "0m ago"


def test_relative_since_exactly_24_hours_is_one_day():
    assert relative_since(NOW - timedelta(hours=24), NOW) == "1d ago"


def test_relative_since_just_under_24_hours_stays_hours():
    assert relative_since(NOW - timedelta(hours=23, minutes=59), NOW) == "23h ago"


def test_relative_since_minute_bucket():
    assert relative_since(NOW - timedelta(minutes=12), NOW) == "12m ago"


def test_relative_since_multi_day():
    assert relative_since(NOW - timedelta(days=3), NOW) == "3d ago"


def test_relative_since_sub_second_future_clamps():
    assert relative_since(NOW + timedelta(milliseconds=500), NOW) == "0m ago"


# ===========================================================================
# build_project_message — branch coverage
# ===========================================================================


def test_message_field_order_and_content():
    msg = build_project_message(_project(), _client(hiring_rate=87.0), now_utc=NOW, owner_tz="Africa/Cairo")
    lines = msg.split("\n")
    assert lines[0].startswith("<b>") and lines[0].endswith("</b>")
    assert lines[1].startswith("💰")
    assert lines[2].startswith("📈")
    assert lines[3].startswith("🧮")
    assert lines[4].startswith("🕒")
    assert lines[5].startswith("🏷️")
    assert lines[6].startswith("🔗")
    assert "Tier 1" in msg
    assert "87%" in msg


def test_message_tier_none_renders_question_mark():
    msg = build_project_message(_project(tier=None), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Tier ?" in msg


def test_message_tier_zero_is_real_value():
    msg = build_project_message(_project(tier=0), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Tier 0" in msg
    assert "Tier ?" not in msg


def test_message_hiring_rate_none_is_unknown():
    # Line 87: hiring_rate None -> "unknown".
    msg = build_project_message(_project(), _client(hiring_rate=None), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Hiring rate: unknown" in msg


def test_message_client_none_is_unknown():
    # Line 87: client None -> "unknown" (no AttributeError on the None client).
    msg = build_project_message(_project(), None, now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Hiring rate: unknown" in msg


def test_message_hiring_rate_zero_is_distinct_not_unknown():
    # 0% is a REAL value (constitution): must render "0%", never "unknown".
    msg = build_project_message(_project(), _client(hiring_rate=0.0), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Hiring rate: 0%" in msg
    assert "Hiring rate: unknown" not in msg


def test_message_hiring_rate_rounds_with_zero_decimals():
    msg = build_project_message(_project(), _client(hiring_rate=66.6), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Hiring rate: 67%" in msg  # :.0f rounds half-to-even/up at .6


def test_message_hiring_rate_100():
    msg = build_project_message(_project(), _client(hiring_rate=100.0), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Hiring rate: 100%" in msg


def test_message_bids_none_is_unknown():
    msg = build_project_message(_project(bids_count=None), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Bids: unknown" in msg


def test_message_bids_zero_is_real_value():
    msg = build_project_message(_project(bids_count=0), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Bids: 0" in msg
    assert "Bids: unknown" not in msg


def test_message_posted_at_none_age_unknown():
    msg = build_project_message(_project(posted_at=None), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Posted: unknown" in msg


def test_message_url_none_renders_unknown_link():
    # Line 101 else-branch: url falsy -> "🔗 unknown".
    msg = build_project_message(_project(url=None), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "🔗 unknown" in msg


def test_message_url_empty_string_renders_unknown_link():
    msg = build_project_message(_project(url=""), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "🔗 unknown" in msg


def test_message_url_present_is_included():
    msg = build_project_message(
        _project(url="https://mostaql.com/project/abc"), _client(), now_utc=NOW, owner_tz="Africa/Cairo"
    )
    assert "https://mostaql.com/project/abc" in msg


def test_message_category_none_is_unknown():
    msg = build_project_message(_project(category=None), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "🏷️ unknown" in msg


def test_message_category_empty_string_is_unknown():
    msg = build_project_message(_project(category=""), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "🏷️ unknown" in msg


def test_message_title_none_escapes_to_empty():
    # html_escape(None) -> "" so the bold line is just "<b></b>" — no crash.
    msg = build_project_message(_project(title=None), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert msg.split("\n")[0] == "<b></b>"


def test_message_invalid_timezone_fails_loud():
    # An unknown owner_tz must raise rather than silently mis-display: ZoneInfo raises
    # ZoneInfoNotFoundError, which is a subclass of KeyError.
    with pytest.raises(KeyError):
        build_project_message(_project(), _client(), now_utc=NOW, owner_tz="Not/AZone")


# ---- HTML escaping ----------------------------------------------------------


def test_message_escapes_angle_brackets_in_title():
    msg = build_project_message(
        _project(title="موقع <ووردبريس>"), _client(), now_utc=NOW, owner_tz="Africa/Cairo"
    )
    assert "<ووردبريس>" not in msg
    assert "&lt;ووردبريس&gt;" in msg
    # our own bold tags survive
    assert "<b>" in msg and "</b>" in msg


def test_message_escapes_ampersand_in_title():
    msg = build_project_message(_project(title="A & B"), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert "&amp;" in msg
    assert "A & B" not in msg


def test_message_escapes_category():
    msg = build_project_message(
        _project(category="<x> & <y>"), _client(), now_utc=NOW, owner_tz="Africa/Cairo"
    )
    assert "&lt;x&gt; &amp; &lt;y&gt;" in msg
    assert "<x>" not in msg


def test_message_escapes_url():
    # A crafted url with HTML metacharacters must be escaped.
    msg = build_project_message(
        _project(url="https://m.com/p?a=<b>&c=d"), _client(), now_utc=NOW, owner_tz="Africa/Cairo"
    )
    assert "<b>&c" not in msg.split("🔗")[1]
    assert "&lt;b&gt;" in msg


def test_message_normal_message_under_limit():
    msg = build_project_message(_project(), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert len(msg) <= _MAX_LEN


# ---- truncation (line 105) --------------------------------------------------


def test_message_truncates_long_title_to_limit():
    # A >4096-char message is truncated to <= _MAX_LEN. The truncation happens on the RAW title
    # (the unbounded field), so the "…" lands inside the still-balanced <b>…</b> and the fixed
    # scaffold (budget/tier/…/link) is preserved rather than the message being sliced mid-HTML.
    msg = build_project_message(_project(title="A" * 5000), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert len(msg) <= _MAX_LEN
    assert "…" in msg                                  # the (truncated) title carries the ellipsis
    assert msg.count("<b>") == msg.count("</b>") == 1  # tags stay balanced
    assert msg.rstrip().endswith("…") is False         # the link line still follows the title


def test_message_at_exactly_limit_is_not_truncated():
    # Construct a title so the full message length is exactly _MAX_LEN (no truncation, no ellipsis).
    probe = build_project_message(_project(title=""), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    pad = _MAX_LEN - len(probe)
    assert pad > 0
    msg = build_project_message(_project(title="A" * pad), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert len(msg) == _MAX_LEN
    assert not msg.endswith("…")  # exactly at the limit, untouched


def test_message_truncated_html_stays_balanced():
    # A long title forces truncation. The bold tag opened on line 1 is never closed once the body is
    # cut, so Telegram's parse_mode=HTML rejects the payload ("can't parse entities") and the
    # qualifying project is never delivered — violating at-least-once. The CORRECT behaviour is a
    # well-formed (balanced) HTML message after truncation.
    msg = build_project_message(_project(title="A" * 5000), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    assert msg.count("<b>") == msg.count("</b>"), "opening <b> must have a matching </b>"


def test_message_truncation_does_not_split_html_entity():
    # A title of many '&' renders to a run of '&amp;'. The char-count slice on line 105 can cut
    # mid-entity (e.g. leaving a trailing '&a'), producing invalid HTML that Telegram rejects.
    # Empirically n=819 lands the boundary inside an entity. The CORRECT behaviour never leaves a
    # dangling '&' fragment.
    msg = build_project_message(_project(title="&" * 819), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    body = msg[:-1] if msg.endswith("…") else msg
    # A trailing '&' optionally followed by a partial entity name with no terminating ';' is broken.
    dangling = re.search(r"&[a-zA-Z]{0,4}$", body)
    assert not (dangling and not body.endswith("&amp;")), f"truncation split an entity: ...{msg[-10:]!r}"


# ===========================================================================
# build_health_alert  (line 131 = truncation)
# ===========================================================================


def test_health_alert_includes_all_lines_and_counts():
    out = build_health_alert(
        kind="blocked", detail="circuit open", action="back off",
        found=10, new=2, updated=3, errors=1,
    )
    lines = out.split("\n")
    assert lines[0] == "<b>⚠️ Health alert: blocked</b>"
    assert lines[1] == "circuit open"
    assert lines[2] == "Action: back off"
    # The counts line (constitution: operator visibility) carries every count.
    assert lines[3] == "Counts — found 10, new 2, updated 3, errors 1"


def test_health_alert_escapes_kind_detail_action():
    out = build_health_alert(
        kind="block<er>", detail="det&ail", action="do <this>",
        found=0, new=0, updated=0, errors=0,
    )
    assert "block&lt;er&gt;" in out
    assert "det&amp;ail" in out
    assert "do &lt;this&gt;" in out
    # No raw metacharacters leaked.
    assert "block<er>" not in out
    assert "<this>" not in out


def test_health_alert_escapes_counts_that_are_strings():
    # found/new/... are typed loosely; a string with metacharacters must also be escaped.
    out = build_health_alert(
        kind="k", detail="d", action="a", found="<n>", new="&", updated=0, errors=0,
    )
    assert "found &lt;n&gt;" in out
    assert "new &amp;" in out


def test_health_alert_truncates_when_too_long():
    # Line 131: an oversized detail forces truncation to _MAX_LEN with a trailing "…".
    out = build_health_alert(
        kind="k", detail="x" * 6000, action="a", found=0, new=0, updated=0, errors=0,
    )
    assert len(out) == _MAX_LEN
    assert out.endswith("…")


def test_health_alert_under_limit_not_truncated():
    out = build_health_alert(
        kind="k", detail="short", action="a", found=0, new=0, updated=0, errors=0,
    )
    assert not out.endswith("…")
    assert len(out) <= _MAX_LEN


def test_health_alert_truncated_html_b_tag_stays_balanced():
    # The alert's only <b>...</b> pair lives entirely on line 1, before the (huge, truncated) detail,
    # so the bold tag remains balanced even after truncation. (Unlike build_project_message, where
    # the bold wraps the title that gets cut — see test_message_truncated_html_stays_balanced.)
    out = build_health_alert(
        kind="k", detail="x" * 6000, action="a", found=0, new=0, updated=0, errors=0,
    )
    assert out.count("<b>") == out.count("</b>") == 1


def test_health_alert_truncation_does_not_split_html_entity():
    # A detail of many '&' renders to a run of '&amp;'. The char-count slice on line 131 can cut
    # mid-entity (empirically n=814 lands inside one), leaving a dangling '&amp' with no ';' —
    # invalid HTML that Telegram rejects, exactly when the operator alert matters most.
    out = build_health_alert(
        kind="k", detail="&" * 814, action="a", found=0, new=0, updated=0, errors=0,
    )
    body = out[:-1] if out.endswith("…") else out
    dangling = re.search(r"&[a-zA-Z]{0,4}$", body)
    assert not (dangling and not body.endswith("&amp;")), f"truncation split an entity: ...{out[-10:]!r}"


# ===========================================================================
# build_heartbeat  (lines 137-142)
# ===========================================================================


def test_heartbeat_includes_last_poll_and_active_floor():
    out = build_heartbeat(last_poll_iso="2026-06-23T00:00:00+00:00", active_floor=250)
    lines = out.split("\n")
    assert lines[0] == "<b>💚 Heartbeat</b>"
    assert lines[1] == "Last poll: 2026-06-23T00:00:00+00:00"
    assert lines[2] == "Active budget floor: 250"


def test_heartbeat_active_floor_zero_is_rendered():
    # 0 is a real floor value, not a missing one.
    out = build_heartbeat(last_poll_iso="2026-06-23T00:00:00+00:00", active_floor=0)
    assert "Active budget floor: 0" in out


def test_heartbeat_escapes_metacharacters():
    out = build_heartbeat(last_poll_iso="2026<06>23 & later", active_floor="<floor>")
    assert "2026&lt;06&gt;23 &amp; later" in out
    assert "&lt;floor&gt;" in out
    assert "<floor>" not in out


def test_heartbeat_no_trailing_newline():
    out = build_heartbeat(last_poll_iso="2026-06-23T00:00:00+00:00", active_floor=250)
    assert not out.endswith("\n")
    assert out.count("\n") == 2  # exactly three lines


# ===========================================================================
# html_escape primitive
# ===========================================================================


def test_html_escape_none_is_empty_string():
    assert html_escape(None) == ""


def test_html_escape_all_metacharacters():
    assert html_escape("<a> & 'b' \"c\"") == "&lt;a&gt; &amp; &#x27;b&#x27; &quot;c&quot;"


def test_html_escape_non_string_coerced():
    assert html_escape(42) == "42"
    assert html_escape(Decimal("250")) == "250"


def test_html_escape_arabic_and_persian_digits_unchanged():
    # Arabic-Indic (٠-٩) and Persian (۰-۹) digits carry no HTML metachars; they must pass through.
    arabic = "٠١٢٣٤٥٦٧٨٩"
    persian = "۰۱۲۳۴۵۶۷۸۹"
    assert html_escape(arabic) == arabic
    assert html_escape(persian) == persian
