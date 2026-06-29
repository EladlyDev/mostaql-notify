"""Unit tests for awarded-status detection in the mostaql project-page parser (Feature 4, T023).

Covers ``ProjectStatus.awarded`` via every default marker (the ``label-prj-awarded`` class token
and both Arabic phrases "تم الترسية" / "مسند"), config-driven custom markers threaded through
``parse_project_page`` / ``_parse_status``, the awarded-wins-over-closed precedence, and proves no
regression on plain open / plain closed / ambiguous (fail-closed -> unknown) pages.
"""
from __future__ import annotations

from selectolax.parser import HTMLParser

from mostaql_notifier.db.models import ProjectStatus
from mostaql_notifier.scraper.mostaql import _parse_status, parse_project_page


def _project_html(status_value: str) -> str:
    """A minimal, structurally-valid project page whose status meta-value is ``status_value``.

    Mirrors the inline-fixture style of tests/unit/test_mostaql_parse.py: a single حالة المشروع
    meta row plus an employer widget carrying a hiring-rate row (so parse_project_page does not
    raise ParseError for unrelated structural reasons).
    """
    return (
        "<html><body>"
        '<div class="meta-label">حالة المشروع</div>'
        f'<div class="meta-value">{status_value}</div>'
        '<div data-type="employer_widget">'
        '<h5 class="profile__name"><bdi>Client</bdi></h5>'
        '<table class="table-meta"><tbody>'
        "<tr><td>معدل التوظيف</td><td><label>50%</label></td></tr>"
        "</tbody></table></div>"
        "</body></html>"
    )


# ---------------------------------------------------------------------------
# awarded — one test per default marker
# ---------------------------------------------------------------------------


def test_awarded_via_class_token():
    p = parse_project_page(
        _project_html('<bdi class="label label-prj-awarded">تم الترسية</bdi>')
    )
    assert p["site_status"] is ProjectStatus.awarded


def test_awarded_via_class_token_case_insensitive():
    """Class tokens match case-insensitively (the live DOM casing may differ)."""
    p = parse_project_page(_project_html('<bdi class="label Label-Prj-Awarded">x</bdi>'))
    assert p["site_status"] is ProjectStatus.awarded


def test_awarded_via_arabic_phrase_tamm_altarsiya():
    """Award phrase as plain status text, no special class -> awarded."""
    p = parse_project_page(_project_html('<bdi class="label">تم الترسية</bdi>'))
    assert p["site_status"] is ProjectStatus.awarded


def test_awarded_via_arabic_phrase_musnad():
    p = parse_project_page(_project_html('<bdi class="label">مسند</bdi>'))
    assert p["site_status"] is ProjectStatus.awarded


def test_awarded_arabic_phrase_robust_to_whitespace_and_tatweel():
    """normalize_text folds tatweel (ـ) + collapses whitespace, so the phrase still matches."""
    p = parse_project_page(_project_html('<bdi class="label">تــم   الترسية</bdi>'))
    assert p["site_status"] is ProjectStatus.awarded


def test_awarded_wins_over_copresent_closed_marker():
    """An awarded project is also flagged closed on the site; the award signal must win."""
    p = parse_project_page(
        _project_html(
            '<bdi class="label label-prj-closed">مغلق</bdi>'
            '<bdi class="label label-prj-awarded">تم الترسية</bdi>'
        )
    )
    assert p["site_status"] is ProjectStatus.awarded


# ---------------------------------------------------------------------------
# fail-closed — ambiguous / empty status never guesses awarded
# ---------------------------------------------------------------------------


def test_ambiguous_status_fails_closed_to_unknown():
    p = parse_project_page(_project_html('<bdi class="label">؟؟؟</bdi>'))
    assert p["site_status"] is ProjectStatus.unknown


def test_empty_status_value_fails_closed_to_unknown():
    p = parse_project_page(_project_html("<span></span>"))
    assert p["site_status"] is ProjectStatus.unknown


# ---------------------------------------------------------------------------
# no regression — plain open / plain closed still parse
# ---------------------------------------------------------------------------


def test_plain_open_still_parses_open():
    p = parse_project_page(_project_html('<bdi class="label label-prj-open">مفتوح</bdi>'))
    assert p["site_status"] is ProjectStatus.open


def test_plain_closed_still_parses_closed():
    p = parse_project_page(_project_html('<bdi class="label label-prj-closed">مغلق</bdi>'))
    assert p["site_status"] is ProjectStatus.closed


# ---------------------------------------------------------------------------
# config-driven — markers are threaded, not hard-coded
# ---------------------------------------------------------------------------


def test_custom_awarded_marker_text_is_config_driven():
    """A non-default Arabic marker is honoured only when threaded through parse_project_page."""
    html = _project_html('<bdi class="label">منجز</bdi>')
    assert parse_project_page(html)["site_status"] is ProjectStatus.unknown  # not a default
    assert (
        parse_project_page(html, awarded_markers=["منجز"])["site_status"]
        is ProjectStatus.awarded
    )


def test_parse_status_threads_markers_directly():
    """_parse_status defaults to the data-model markers and accepts a custom (class-token) list."""
    node = HTMLParser(
        '<div class="meta-value"><bdi class="label custom-awarded">x</bdi></div>'
    ).css_first("div.meta-value")
    assert _parse_status(node) is ProjectStatus.unknown  # default markers don't match
    assert _parse_status(node, ["CUSTOM-AWARDED"]) is ProjectStatus.awarded  # case-insensitive


def test_parse_status_none_value_is_unknown():
    assert _parse_status(None) is ProjectStatus.unknown
