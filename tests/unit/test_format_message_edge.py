"""Adversarial / property edge tests for the pure HTML builders in ``notify.format``.

The bar these defend: a message handed to Telegram with ``parse_mode=HTML`` must be (a) injection
safe — no caller-controlled angle bracket / ampersand / quote ever survives un-escaped, and (b)
well-formed — the ``<b>`` tag is balanced and no truncation ever splits an ``&…;`` HTML entity
(Telegram answers malformed HTML with a 400 and the qualifying notification is silently dropped).

These intentionally avoid re-asserting the line-coverage cases in ``test_format.py`` /
``test_format_exhaustive.py``; they add boundary tables, the ``_safe_truncate`` primitive in
isolation, and a structural "no un-escaped metacharacter survives" property over hostile inputs.
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
    _safe_truncate,
    build_health_alert,
    build_heartbeat,
    build_project_message,
    html_escape,
    relative_since,
)

NOW = utcnow()

# Matches a single well-formed HTML entity (named or numeric) that ``html.escape`` can emit.
_ENTITY = re.compile(r"&(?:amp|lt|gt|quot|#x27|#\d+|#x[0-9a-fA-F]+);")


def _strip_entities(text: str) -> str:
    """Remove every complete HTML entity; what remains must contain no bare metacharacter.

    A leftover ``<`` / ``>`` means an un-escaped tag survived; a leftover ``&`` means an entity was
    split (truncated mid-``&…;``) or a raw ampersand leaked. Either is an injectable/invalid payload.
    """
    return _ENTITY.sub("", text)


def _project(**overrides) -> Project:
    base = dict(
        mostaql_id="proj-edge",
        title="عنوان",
        url="https://mostaql.com/project/proj-edge",
        category="تطوير",
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
        mostaql_id="derived:edge",
        name="عميل",
        hiring_rate=50.0,
        last_refreshed_at=NOW,
        first_seen_at=NOW,
        raw={},
    )
    base.update(overrides)
    return Client(**base)


# ==================================================================================================
# html_escape — None sentinel + a "no un-escaped metacharacter survives" property
# ==================================================================================================
def test_html_escape_none_is_empty_string():
    assert html_escape(None) == ""


@pytest.mark.parametrize(
    "char,expected",
    [("<", "&lt;"), (">", "&gt;"), ("&", "&amp;"), ('"', "&quot;"), ("'", "&#x27;")],
)
def test_html_escape_neutralises_each_metacharacter(char, expected):
    out = html_escape(char)
    assert out == expected  # each metacharacter maps to exactly its entity
    assert _strip_entities(out) == ""  # nothing but a complete entity remains


@pytest.mark.parametrize(
    "hostile",
    [
        '<script>alert("xss")</script>',
        "'; DROP TABLE projects;--",
        "&amp; pre-escaped should double-escape",
        "<b>not your bold</b>",
        '<a href="evil">x</a>',
        "mixed < > & \" ' all at once",
    ],
)
def test_html_escape_leaves_no_bare_metacharacter(hostile):
    """Property: after escaping, removing all valid entities leaves NO ``<``, ``>`` or ``&``."""
    out = html_escape(hostile)
    residue = _strip_entities(out)
    assert "<" not in residue and ">" not in residue and "&" not in residue
    assert "<script>" not in out  # the canonical injection never survives intact


# ==================================================================================================
# _safe_truncate — the entity-aware backup primitive (used by build_health_alert)
# ==================================================================================================
def test_safe_truncate_returns_input_unchanged_when_within_limit():
    assert _safe_truncate("hello", 10) == "hello"
    assert _safe_truncate("abcdef", 6) == "abcdef"  # exactly at the limit is untouched (no ellipsis)


def test_safe_truncate_appends_ellipsis_on_a_plain_cut():
    # No ampersand near the cut → a straight slice plus the ellipsis.
    assert _safe_truncate("abcdefghij", 5) == "abcd…"


def test_safe_truncate_backs_up_before_a_half_written_entity():
    # Cutting "ab&amp;cd" at limit 6 would land inside "&amp;" → must drop the partial entity, not split it.
    out = _safe_truncate("ab&amp;cd", 6)
    assert out == "ab…"
    assert "&" not in out  # no dangling ampersand


def test_safe_truncate_keeps_a_complete_preceding_entity():
    # "&amp;&amp;XYZ" cut at 8: the first "&amp;" is whole and kept; the second (partial) is dropped.
    assert _safe_truncate("&amp;&amp;XYZ", 8) == "&amp;…"


def test_safe_truncate_preserves_a_terminated_entity_when_semicolon_is_inside_the_cut():
    # "a&amp; bcdef" cut at 8: the cut already includes the ';' so the entity is complete — keep it.
    out = _safe_truncate("a&amp; bcdef", 8)
    assert out == "a&amp; …"
    assert _strip_entities(out) == "a …"  # the only '&' belonged to a complete entity


def test_safe_truncate_never_splits_an_entity_across_a_run_of_ampersands():
    # A long run of '&' escaped to '&amp;' — every cut length must leave a clean (un-split) result.
    text = "&amp;" * 50
    for limit in range(1, len(text)):
        out = _safe_truncate(text, limit)
        body = out[:-1] if out.endswith("…") else out
        assert not re.search(r"&[a-zA-Z]{0,4}$", body) or body.endswith("&amp;"), (limit, out[-8:])


# ==================================================================================================
# relative_since — full boundary table (future clamp through multi-day)
# ==================================================================================================
@pytest.mark.parametrize(
    "delta,expected",
    [
        (None, "unknown"),
        (timedelta(hours=-3), "0m ago"),  # FUTURE dt → clamp to 0, never a negative age
        (timedelta(seconds=30), "0m ago"),
        (timedelta(minutes=59), "59m ago"),
        (timedelta(minutes=60), "1h ago"),  # the minute→hour boundary
        (timedelta(hours=23), "23h ago"),
        (timedelta(hours=24), "1d ago"),  # the hour→day boundary
        (timedelta(days=10), "10d ago"),  # several days
    ],
)
def test_relative_since_boundary_table(delta, expected):
    if delta is None:
        assert relative_since(None, NOW) == expected
    else:
        assert relative_since(NOW - delta, NOW) == expected


# ==================================================================================================
# _fmt_decimal — None passthrough + never exponent form for large magnitudes
# ==================================================================================================
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (Decimal("250.00"), "250"),
        (Decimal("250.50"), "250.5"),
        (Decimal("250"), "250"),
        (Decimal("250000000"), "250000000"),  # large integer must NOT become "2.5E+8"
    ],
)
def test_fmt_decimal_cases(value, expected):
    assert _fmt_decimal(value) == expected


@pytest.mark.parametrize("k", range(0, 18))
def test_fmt_decimal_large_integers_are_never_exponential(k):
    """Property: a round power of ten of any magnitude renders as plain digits, never ``E`` notation."""
    out = _fmt_decimal(Decimal(10) ** k)
    assert "E" not in out and "e" not in out
    assert out == "1" + "0" * k


# ==================================================================================================
# _budget_text — every bound/currency combination
# ==================================================================================================
@pytest.mark.parametrize(
    "lo,hi,cur,expected",
    [
        (None, None, None, "unknown"),  # both bounds + currency absent → bare sentinel, stripped
        (None, None, "USD", "unknown USD"),  # unknown body, currency still appended
        (Decimal("250"), Decimal("250"), "USD", "250 USD"),  # equal bounds collapse to one value
        (Decimal("100"), Decimal("500"), "USD", "100–500 USD"),  # full range with en-dash
        (Decimal("100"), None, "USD", "100 USD"),  # only the min known
        (None, Decimal("900"), "USD", "900 USD"),  # only the max known
        (Decimal("100"), Decimal("200"), "  SAR  ", "100–200 SAR"),  # currency padding stripped
        (Decimal("100"), Decimal("200"), "   ", "100–200"),  # whitespace-only currency → no trailing space
    ],
)
def test_budget_text_cases(lo, hi, cur, expected):
    out = _budget_text(_project(budget_min=lo, budget_max=hi, currency=cur))
    assert out == expected
    assert out == out.strip()  # never leaks a leading/trailing space


# ==================================================================================================
# build_project_message — injection safety + structure + fail-loud timezone
# ==================================================================================================
def test_message_no_caller_metacharacter_survives_unescaped():
    """The ONLY raw tags allowed in the output are our own ``<b>`` / ``</b>`` on line 1; every
    caller-controlled field (title/category/url) must be fully escaped. Strip our bold tags and the
    message must contain no remaining ``<`` or ``>`` at all."""
    project = _project(
        title='<script>alert("x")</script> & <b>nope</b>',
        category="<cat> & 'more'",
        url='https://m.com/p?q=<b>&x="y"',
    )
    msg = build_project_message(project, _client(), now_utc=NOW, owner_tz="Africa/Cairo")

    # No injected script / tags survive intact.
    assert "<script>" not in msg
    assert msg.count("<b>") == 1 and msg.count("</b>") == 1  # exactly our bold pair
    without_bold = msg.replace("<b>", "").replace("</b>", "")
    assert "<" not in without_bold and ">" not in without_bold
    # And no entity was left split anywhere.
    assert "&" not in _strip_entities(without_bold)


def test_message_each_labelled_field_is_on_its_own_line():
    msg = build_project_message(_project(), _client(), now_utc=NOW, owner_tz="Africa/Cairo")
    lines = msg.split("\n")
    assert len(lines) == 7
    assert lines[0].startswith("<b>") and lines[0].endswith("</b>")
    for line, marker in zip(lines[1:], ["💰", "📈", "🧮", "🕒", "🏷️", "🔗"], strict=True):
        assert line.startswith(marker)


@pytest.mark.parametrize(
    "overrides,client_kw,needle",
    [
        ({"tier": None}, {}, "Tier ?"),  # missing tier → '?'
        ({}, {"hiring_rate": None}, "Hiring rate: unknown"),  # null hiring rate
        ({"bids_count": None}, {}, "Bids: unknown"),  # null bids
    ],
)
def test_message_missing_fields_render_unknown_sentinels(overrides, client_kw, needle):
    msg = build_project_message(
        _project(**overrides), _client(**client_kw), now_utc=NOW, owner_tz="Africa/Cairo"
    )
    assert needle in msg


def test_message_missing_client_object_is_unknown_hiring_rate():
    msg = build_project_message(_project(), None, now_utc=NOW, owner_tz="Africa/Cairo")
    assert "Hiring rate: unknown" in msg


@pytest.mark.parametrize("hostile_title", ["<" * 5000, "&" * 5000, "A" * 5000])
def test_message_over_length_title_stays_valid_html_under_the_cap(hostile_title):
    """An oversized, entity-dense title must yield a message that: fits the 4096 cap, keeps the bold
    tag balanced, ends the (truncated) title with an ellipsis, and never splits an HTML entity. The
    link line still follows the title, so the whole MESSAGE does not end with '…' — only the title
    line does (mirrors the design verified in test_format_exhaustive)."""
    msg = build_project_message(
        _project(title=hostile_title), _client(), now_utc=NOW, owner_tz="Africa/Cairo"
    )
    assert len(msg) <= _MAX_LEN
    assert msg.count("<b>") == msg.count("</b>") == 1  # balanced
    lines = msg.split("\n")
    assert lines[0].endswith("…</b>")  # the truncated title carries the ellipsis
    assert "…" in msg
    # No entity split anywhere in the message (strip our bold tags first, then all valid entities).
    residue = _strip_entities(msg.replace("<b>", "").replace("</b>", ""))
    assert "&" not in residue
    assert "<" not in residue and ">" not in residue


def test_message_invalid_timezone_raises_fail_loud():
    """An unparseable owner_tz must raise (fail-loud) rather than silently mis-display."""
    from zoneinfo import ZoneInfoNotFoundError

    with pytest.raises(ZoneInfoNotFoundError):
        build_project_message(_project(), _client(), now_utc=NOW, owner_tz="Bad/Zone")


# ==================================================================================================
# build_health_alert / build_heartbeat — one combined-hostile test each
# ==================================================================================================
def test_health_alert_escapes_every_field_including_string_counts():
    out = build_health_alert(
        kind="block<er>",
        detail="det&ail <here>",
        action='do "this" & that',
        found="<n>",
        new="&",
        updated=0,
        errors="x>y",
    )
    lines = out.split("\n")
    assert lines[0] == "<b>⚠️ Health alert: block&lt;er&gt;</b>"
    assert lines[1] == "det&amp;ail &lt;here&gt;"
    assert lines[2] == "Action: do &quot;this&quot; &amp; that"
    assert lines[3] == "Counts — found &lt;n&gt;, new &amp;, updated 0, errors x&gt;y"
    # No raw metacharacter survives anywhere except our own single <b>…</b> pair.
    body = out.replace("<b>", "").replace("</b>", "")
    assert "<" not in body and ">" not in body
    assert "&" not in _strip_entities(body)


def test_heartbeat_escapes_metacharacters_and_renders_three_lines():
    out = build_heartbeat(last_poll_iso="2026<06>23 & later", active_floor="<floor>")
    lines = out.split("\n")
    assert lines[0] == "<b>💚 Heartbeat</b>"
    assert lines[1] == "Last poll: 2026&lt;06&gt;23 &amp; later"
    assert lines[2] == "Active budget floor: &lt;floor&gt;"
    assert not out.endswith("\n")
    body = out.replace("<b>", "").replace("</b>", "")
    assert "<" not in body and ">" not in body
    assert "&" not in _strip_entities(body)
