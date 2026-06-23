"""Exhaustive branch/boundary/adversarial tests for the mostaql HTML parsers.

Targets the uncovered branches in src/mostaql_notifier/scraper/mostaql.py:
listing skip paths (54, 58), client-name bdi-vs-li.text fallback (76, 82),
meta-label first-wins mobile dedup (148, 153), closed status (159), posted_at
relative-time fallback when <time datetime> is absent/malformed (174-176),
description fallback chain (217-218), _to_int None branch (250), and every
parse_profile_page field (295-297, 302, 307-308, 313).

Determinism: parse_relative_time inside _parse_posted reads utcnow() internally
(not injectable here), so the relative-time fallback is asserted by tz-awareness
and a generous delta window, never an exact instant.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mostaql_notifier.db.models import ProjectStatus
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.scraper.mostaql import (
    ParseError,
    parse_listing,
    parse_profile_page,
    parse_project_page,
)

# ---------------------------------------------------------------------------
# helpers — synthetic HTML builders
# ---------------------------------------------------------------------------


def _wrap_rows(inner: str) -> str:
    """selectolax (html5) drops a bare <tr>; rows must live inside <table><tbody>."""
    return f"<table><tbody>{inner}</tbody></table>"


def _project_html(
    *,
    title: str | None = "Title Here",
    status_value: str = '<bdi class="label label-prj-open">مفتوح</bdi>',
    extra_meta: str = "",
    widget: str | None = None,
    extra_body: str = "",
) -> str:
    """A minimal, structurally-valid project page (meta block + employer widget).

    The widget defaults to one carrying a hiring-rate row so parse_project_page
    does not raise; callers override `widget` to exercise the ParseError paths.
    """
    if widget is None:
        widget = (
            '<div data-type="employer_widget">'
            '<h5 class="profile__name"><bdi>Some Client</bdi></h5>'
            '<table class="table-meta"><tbody>'
            "<tr><td>معدل التوظيف</td><td><label>50%</label></td></tr>"
            "</tbody></table></div>"
        )
    title_html = (
        f'<span data-type="page-header-title">{title}</span>' if title is not None else ""
    )
    return (
        "<html><body>"
        f"{title_html}"
        '<div class="meta-label">حالة المشروع</div>'
        f'<div class="meta-value">{status_value}</div>'
        f"{extra_meta}"
        f"{widget}"
        f"{extra_body}"
        "</body></html>"
    )


# ===========================================================================
# parse_listing — skip paths (lines 54, 58)
# ===========================================================================


def test_listing_row_without_h2_link_is_skipped():
    """A tr.project-row whose card has no `h2 a[href*=/project/]` is dropped (line 54)."""
    html = _wrap_rows(
        '<tr class="project-row"><td><div class="card--title">no link here</div></td></tr>'
        '<tr class="project-row"><td><h2><a href="/project/123-ok">Valid</a></h2></td></tr>'
    )
    rows = parse_listing(html)
    assert [r["mostaql_id"] for r in rows] == ["123"]


def test_listing_row_with_non_numeric_project_href_is_skipped():
    """href matches the `/project/` substring selector but carries no numeric id (line 58)."""
    html = _wrap_rows(
        '<tr class="project-row"><td><h2>'
        '<a href="https://mostaql.com/project/slug-only">No id</a></h2></td></tr>'
    )
    assert parse_listing(html) == []


def test_listing_mixed_skips_keep_only_identifiable_rows():
    html = _wrap_rows(
        '<tr class="project-row"><td><div>no link</div></td></tr>'
        '<tr class="project-row"><td><h2><a href="/project/abc">no id</a></h2></td></tr>'
        '<tr class="project-row"><td><h2><a href="/project/77-good">Good</a></h2></td></tr>'
    )
    rows = parse_listing(html)
    assert len(rows) == 1
    assert rows[0]["mostaql_id"] == "77"
    assert rows[0]["url"] == "/project/77-good"


def test_listing_empty_html_yields_empty_list():
    assert parse_listing("<html><body></body></html>") == []
    assert parse_listing("") == []


def test_listing_id_is_first_numeric_run_in_href():
    html = _wrap_rows(
        '<tr class="project-row"><td><h2>'
        '<a href="/project/42-a-2nd-99-number">T</a></h2></td></tr>'
    )
    rows = parse_listing(html)
    assert rows[0]["mostaql_id"] == "42"


def test_listing_blank_link_text_yields_none_title():
    html = _wrap_rows(
        '<tr class="project-row"><td><h2><a href="/project/55-x">   </a></h2></td></tr>'
    )
    rows = parse_listing(html)
    assert rows[0]["title"] is None


# ===========================================================================
# _listing_client_name — bdi vs li.text fallback (lines 76, 82)
# ===========================================================================


def _listing_row(meta_li: str, project_id: str = "55") -> str:
    return _wrap_rows(
        f'<tr class="project-row"><td>'
        f'<h2><a href="/project/{project_id}-x">T</a></h2>'
        f'<ul class="project__meta">{meta_li}</ul>'
        f"</td></tr>"
    )


def test_client_name_from_bdi_when_present():
    rows = parse_listing(
        _listing_row('<li><i class="fa fa-user"></i> <bdi>Bdi Name</bdi></li>')
    )
    assert rows[0]["client_name"] == "Bdi Name"


def test_client_name_falls_back_to_li_text_without_bdi():
    """fa-user li with no bdi -> li.text() (line 78 fallback path)."""
    rows = parse_listing(_listing_row('<li><i class="fa fa-user"></i> Plain Name</li>'))
    assert rows[0]["client_name"] == "Plain Name"


def test_client_name_skips_li_without_fa_user_icon():
    """A li lacking i.fa-user is skipped (line 76 continue)."""
    rows = parse_listing(_listing_row("<li>no user icon here</li>"))
    assert rows[0]["client_name"] is None


def test_client_name_empty_bdi_returns_none():
    """fa-user present but name normalises to empty -> not returned (line 82 final None)."""
    rows = parse_listing(
        _listing_row('<li><i class="fa fa-user"></i> <bdi>   </bdi></li>')
    )
    assert rows[0]["client_name"] is None


def test_client_name_first_nonempty_fa_user_li_wins():
    rows = parse_listing(
        _listing_row(
            '<li><i class="fa fa-user"></i> <bdi>  </bdi></li>'
            '<li><i class="fa fa-user"></i> <bdi>Second</bdi></li>'
        )
    )
    assert rows[0]["client_name"] == "Second"


def test_client_name_no_project_meta_ul_returns_none():
    html = _wrap_rows(
        '<tr class="project-row"><td><h2><a href="/project/55-x">T</a></h2></td></tr>'
    )
    rows = parse_listing(html)
    assert rows[0]["client_name"] is None


def test_client_name_arabic_indic_digits_in_name_folded():
    rows = parse_listing(
        _listing_row('<li><i class="fa fa-user"></i> <bdi>عميل ٧</bdi></li>')
    )
    assert rows[0]["client_name"] == "عميل 7"


# ===========================================================================
# parse_project_page — status branches (line 153 unknown, 159 closed)
# ===========================================================================


def test_status_open():
    p = parse_project_page(_project_html())
    assert p["site_status"] is ProjectStatus.open


def test_status_closed_via_label_prj_closed():
    """label-prj-closed bdi -> ProjectStatus.closed (line 159)."""
    p = parse_project_page(
        _project_html(status_value='<bdi class="label label-prj-closed">مغلق</bdi>')
    )
    assert p["site_status"] is ProjectStatus.closed


def test_status_unknown_when_value_node_missing_fails_closed():
    """No حالة المشروع meta-value present at all -> value is None -> unknown (line 153)."""
    html = (
        "<html><body>"
        '<div class="meta-label">تاريخ النشر</div>'
        '<div class="meta-value"><time datetime="2026-06-23 12:00:00">x</time></div>'
        '<div data-type="employer_widget">'
        '<h5 class="profile__name"><bdi>C</bdi></h5>'
        '<table class="table-meta"><tbody>'
        "<tr><td>معدل التوظيف</td><td><label>50%</label></td></tr>"
        "</tbody></table></div>"
        "</body></html>"
    )
    p = parse_project_page(html)
    assert p["site_status"] is ProjectStatus.unknown


def test_status_unknown_when_label_unrecognised_fails_closed():
    """An unrecognised status bdi class fails closed -> unknown (constitution)."""
    p = parse_project_page(
        _project_html(status_value='<bdi class="label label-prj-mystery">???</bdi>')
    )
    assert p["site_status"] is ProjectStatus.unknown


def test_status_unknown_when_class_on_non_bdi_node():
    """The open/closed class lives on a non-<bdi> node -> ignored -> unknown (fail-closed)."""
    p = parse_project_page(
        _project_html(status_value='<span class="label-prj-open">مفتوح</span>')
    )
    assert p["site_status"] is ProjectStatus.unknown


# ===========================================================================
# meta first-wins / mobile duplicate (lines 132-133, 148)
# ===========================================================================


def test_mobile_duplicate_meta_label_first_wins():
    """The first (desktop) meta-label/value wins; the mobile duplicate is ignored."""
    extra = (
        '<div class="meta-label">الميزانية</div>'
        '<div class="meta-value"><span dir="rtl">$25 - $50</span></div>'
        '<div class="meta-label">الميزانية</div>'  # mobile duplicate
        '<div class="meta-value"><span dir="rtl">$900 - $9999</span></div>'
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    assert p["budget_min"] == Decimal("25")
    assert p["budget_max"] == Decimal("50")
    assert p["currency"] == "USD"


def test_meta_label_with_blank_key_is_skipped():
    extra = (
        '<div class="meta-label">   </div>'
        '<div class="meta-value">ignored junk</div>'
    )
    # Should not raise and status still parses from the real row.
    p = parse_project_page(_project_html(extra_meta=extra))
    assert p["site_status"] is ProjectStatus.open


def test_meta_label_without_following_value_is_dropped():
    """A meta-label with no sibling div.meta-value contributes nothing (no crash)."""
    extra = '<div class="meta-label">الميزانية</div><p>not a meta-value</p>'
    p = parse_project_page(_project_html(extra_meta=extra))
    # budget label had no value node -> budget all None
    assert p["budget_min"] is None
    assert p["budget_max"] is None


# ===========================================================================
# budget node — span[dir=rtl] vs full meta-value text
# ===========================================================================


def test_budget_from_dir_rtl_span():
    extra = (
        '<div class="meta-label">الميزانية</div>'
        '<div class="meta-value">prefix junk <span dir="rtl">$300 - $500</span> suffix</div>'
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    assert (p["budget_min"], p["budget_max"], p["currency"]) == (
        Decimal("300"),
        Decimal("500"),
        "USD",
    )


def test_budget_falls_back_to_meta_value_text_without_rtl_span():
    extra = (
        '<div class="meta-label">الميزانية</div>'
        '<div class="meta-value">100 - 200</div>'
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    assert p["budget_min"] == Decimal("100")
    assert p["budget_max"] == Decimal("200")
    assert p["currency"] is None  # fail-closed: no $/دولار => no currency guess


def test_budget_arabic_indic_and_persian_digits():
    extra = (
        '<div class="meta-label">الميزانية</div>'
        '<div class="meta-value"><span dir="rtl">٣٠٠ - ۵۰۰ دولار</span></div>'
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    assert p["budget_min"] == Decimal("300")
    assert p["budget_max"] == Decimal("500")
    assert p["currency"] == "USD"


def test_budget_absent_meta_row_all_none():
    p = parse_project_page(_project_html())
    assert (p["budget_min"], p["budget_max"], p["currency"]) == (None, None, None)


# ===========================================================================
# posted_at — <time datetime> happy path + relative fallback (174-176)
# ===========================================================================


def test_posted_at_from_valid_datetime_attr_is_aware_utc():
    extra = (
        '<div class="meta-label">تاريخ النشر</div>'
        '<div class="meta-value"><time datetime="2026-06-23 12:50:00">منذ 10 دقائق</time></div>'
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    assert p["posted_at"] == datetime(2026, 6, 23, 12, 50, 0, tzinfo=timezone.utc)
    assert p["posted_at"].tzinfo is not None


def test_posted_at_falls_back_to_relative_text_when_datetime_malformed():
    """Malformed <time datetime> -> ValueError -> relative-time fallback (lines 174-176)."""
    before = utcnow()
    extra = (
        '<div class="meta-label">تاريخ النشر</div>'
        '<div class="meta-value"><time datetime="not-a-date">منذ 10 دقائق</time></div>'
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    after = utcnow()
    posted = p["posted_at"]
    assert isinstance(posted, datetime)
    assert posted.tzinfo is not None
    assert posted.utcoffset() == timedelta(0)
    # "منذ 10 دقائق" == 10 minutes ago, resolved against an internal utcnow().
    assert before - timedelta(minutes=10, seconds=5) <= posted <= after - timedelta(
        minutes=10, seconds=-5
    )


def test_posted_at_falls_back_to_relative_text_when_no_time_node():
    """No <time> element -> relative text on the meta-value drives posted_at (line 176)."""
    before = utcnow()
    extra = (
        '<div class="meta-label">تاريخ النشر</div>'
        '<div class="meta-value">منذ ٥ دقائق</div>'  # Arabic-Indic 5
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    after = utcnow()
    posted = p["posted_at"]
    assert posted is not None and posted.tzinfo is not None
    assert before - timedelta(minutes=5, seconds=5) <= posted <= after - timedelta(
        minutes=5, seconds=-5
    )


def test_posted_at_unparseable_relative_text_yields_none():
    """No datetime attr and unrecognised relative text -> None (fail-closed)."""
    extra = (
        '<div class="meta-label">تاريخ النشر</div>'
        '<div class="meta-value">قريباً جداً</div>'
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    assert p["posted_at"] is None


def test_posted_at_absent_meta_row_yields_none():
    p = parse_project_page(_project_html())
    assert p["posted_at"] is None


def test_posted_at_empty_datetime_attr_falls_back_to_relative():
    """An empty datetime="" attribute is falsy -> skip strptime -> relative fallback."""
    extra = (
        '<div class="meta-label">تاريخ النشر</div>'
        '<div class="meta-value"><time datetime="">منذ يومين</time></div>'
    )
    before = utcnow()
    p = parse_project_page(_project_html(extra_meta=extra))
    after = utcnow()
    posted = p["posted_at"]
    assert posted is not None
    assert before - timedelta(days=2, seconds=5) <= posted <= after - timedelta(
        days=2, seconds=-5
    )


# ===========================================================================
# skills — own meta-value vs #project-meta-panel fallback
# ===========================================================================


def test_skills_from_own_meta_value_tags_deduped():
    extra = (
        '<div class="meta-label">المهارات</div>'
        '<div class="meta-value"><ul class="skills__list">'
        '<li><a class="tag"><bdi>لارافيل</bdi></a></li>'
        '<li><a class="tag"><bdi>PHP</bdi></a></li>'
        '<li><a class="tag"><bdi>PHP</bdi></a></li>'  # duplicate -> deduped
        "</ul></div>"
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    assert p["skills"] == ["لارافيل", "PHP"]


def test_skills_tag_without_bdi_uses_tag_text():
    extra = (
        '<div class="meta-label">المهارات</div>'
        '<div class="meta-value"><a class="tag">Django</a></div>'
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    assert p["skills"] == ["Django"]


def test_skills_fall_back_to_project_meta_panel_when_no_tag_in_value():
    """meta-value has no a.tag -> scope falls back to #project-meta-panel (lines 196-197)."""
    panel = (
        '<div id="project-meta-panel">'
        '<div class="meta-label">المهارات</div>'
        '<div class="meta-value"><span>no tags here</span></div>'
        '<a class="tag"><bdi>Vue</bdi></a>'
        '<a class="tag">Nuxt</a>'
        "</div>"
    )
    p = parse_project_page(_project_html(extra_meta=panel))
    assert p["skills"] == ["Vue", "Nuxt"]


def test_skills_fall_back_to_meta_container_when_no_panel():
    """No #project-meta-panel -> fall back to div.meta-container."""
    container = (
        '<div class="meta-container">'
        '<div class="meta-label">المهارات</div>'
        '<div class="meta-value"><span>no tags</span></div>'
        '<a class="tag"><bdi>Go</bdi></a>'
        "</div>"
    )
    p = parse_project_page(_project_html(extra_meta=container))
    assert p["skills"] == ["Go"]


def test_skills_empty_when_no_tags_anywhere():
    extra = (
        '<div class="meta-label">المهارات</div>'
        '<div class="meta-value"><span>none</span></div>'
    )
    p = parse_project_page(_project_html(extra_meta=extra))
    assert p["skills"] == []


# ===========================================================================
# description — chained fallbacks (lines 211-218)
# ===========================================================================


def test_description_from_project_details_data_type():
    extra_body = '<div data-type="project-details">Primary description text</div>'
    p = parse_project_page(_project_html(extra_body=extra_body))
    assert p["description"] == "Primary description text"


def test_description_from_project_brief_fallback():
    extra_body = '<div class="project-brief">Brief fallback text</div>'
    p = parse_project_page(_project_html(extra_body=extra_body))
    assert p["description"] == "Brief fallback text"


def test_description_from_text_wrapper_h_fallback():
    extra_body = '<div class="text-wrapper-h">Wrapper fallback text</div>'
    p = parse_project_page(_project_html(extra_body=extra_body))
    assert p["description"] == "Wrapper fallback text"


def test_description_none_when_no_matching_node():
    p = parse_project_page(_project_html())
    assert p["description"] is None


def test_description_empty_node_normalises_to_none():
    """A matched-but-blank description node yields None (lines 217-218 `text or None`)."""
    extra_body = '<div data-type="project-details">   ‏  </div>'
    p = parse_project_page(_project_html(extra_body=extra_body))
    assert p["description"] is None


# ===========================================================================
# bids count — _parse_bids_count
# ===========================================================================


def test_bids_count_arabic_indic_digits():
    """<span class="count">٤ عروض</span> -> 4."""
    p = parse_project_page(
        _project_html(extra_body='<span class="count">٤ عروض</span>')
    )
    assert p["bids_count"] == 4


def test_bids_count_persian_digits():
    p = parse_project_page(
        _project_html(extra_body='<span class="count">۴ عروض</span>')
    )
    assert p["bids_count"] == 4


def test_bids_count_none_when_no_count_span():
    p = parse_project_page(_project_html())
    assert p["bids_count"] is None


def test_bids_count_none_when_count_has_no_digits():
    p = parse_project_page(
        _project_html(extra_body='<span class="count">عروض</span>')
    )
    assert p["bids_count"] is None


# ===========================================================================
# client widget — fields, _to_int None branch (line 250 single-td skip)
# ===========================================================================


def _client_widget(rows: str, name: str = '<h5 class="profile__name"><bdi>C</bdi></h5>') -> str:
    return (
        '<div data-type="employer_widget">'
        f"{name}"
        f'<table class="table-meta"><tbody>{rows}</tbody></table></div>'
    )


def test_client_full_fields_with_arabic_digits():
    widget = _client_widget(
        "<tr><td>تاريخ التسجيل</td><td><time>10 يناير 2024</time></td></tr>"
        "<tr><td>معدل التوظيف</td><td><label>75.00%</label></td></tr>"
        "<tr><td>المشاريع المفتوحة</td><td>٣</td></tr>"
        "<tr><td>مشاريع قيد التنفيذ</td><td>۲</td></tr>"
    )
    c = parse_project_page(_project_html(widget=widget))["client"]
    assert c["name"] == "C"
    assert c["member_since"] == "10 يناير 2024"
    assert c["hiring_rate"] == 75.0
    assert c["projects_open"] == 3
    assert c["raw"]["in_progress"] == 2


def test_client_hiring_rate_zero_is_real_value_not_none():
    """0% is a REAL distinct value (constitution), never folded to None."""
    widget = _client_widget("<tr><td>معدل التوظيف</td><td><label>0%</label></td></tr>")
    c = parse_project_page(_project_html(widget=widget))["client"]
    assert c["hiring_rate"] == 0.0
    assert c["hiring_rate"] is not None


def test_client_hiring_rate_not_calculated_is_none():
    """"لم يحسب بعد" -> unknown -> None (distinct from 0.0)."""
    widget = _client_widget(
        "<tr><td>معدل التوظيف</td><td><label>لم يحسب بعد</label></td></tr>"
    )
    c = parse_project_page(_project_html(widget=widget))["client"]
    assert c["hiring_rate"] is None


def test_client_single_td_row_skipped_to_int_safe():
    """A header-ish single-<td> row is skipped (line 250) without breaking parsing."""
    widget = _client_widget(
        '<tr><td colspan="2">معلومات المستخدم</td></tr>'
        "<tr><td>معدل التوظيف</td><td><label>90%</label></td></tr>"
        "<tr><td>المشاريع المفتوحة</td><td>غير متوفر</td></tr>"  # _to_int None branch
    )
    c = parse_project_page(_project_html(widget=widget))["client"]
    assert c["hiring_rate"] == 90.0
    assert c["projects_open"] is None  # no digit -> _to_int returns None
    assert c["raw"]["in_progress"] is None


def test_client_name_falls_back_to_h5_without_bdi():
    widget = _client_widget(
        "<tr><td>معدل التوظيف</td><td><label>50%</label></td></tr>",
        name='<h5 class="profile__name">Plain Client</h5>',
    )
    c = parse_project_page(_project_html(widget=widget))["client"]
    assert c["name"] == "Plain Client"


def test_client_name_none_when_no_name_node():
    widget = _client_widget(
        "<tr><td>معدل التوظيف</td><td><label>50%</label></td></tr>", name=""
    )
    c = parse_project_page(_project_html(widget=widget))["client"]
    assert c["name"] is None


# ===========================================================================
# ParseError — structural surprises (fail loud, not silent)
# ===========================================================================


def test_parse_error_when_no_meta_rows():
    html = '<html><body><div data-type="employer_widget"></div></body></html>'
    with pytest.raises(ParseError):
        parse_project_page(html)


def test_parse_error_when_no_employer_widget():
    html = (
        "<html><body>"
        '<div class="meta-label">حالة المشروع</div>'
        '<div class="meta-value"><bdi class="label-prj-open">x</bdi></div>'
        "</body></html>"
    )
    with pytest.raises(ParseError):
        parse_project_page(html)


def test_parse_error_when_widget_has_no_hiring_row():
    widget = _client_widget(
        "<tr><td>تاريخ التسجيل</td><td><time>2024</time></td></tr>"
    )
    with pytest.raises(ParseError):
        parse_project_page(_project_html(widget=widget))


def test_parse_error_when_widget_table_empty():
    widget = '<div data-type="employer_widget"><h5 class="profile__name"><bdi>C</bdi></h5></div>'
    with pytest.raises(ParseError):
        parse_project_page(_project_html(widget=widget))


# ===========================================================================
# parse_project_page — top-level shape & title
# ===========================================================================


def test_project_title_none_when_header_missing():
    p = parse_project_page(_project_html(title=None))
    assert p["title"] is None


def test_project_returns_static_category_and_null_url():
    p = parse_project_page(_project_html())
    assert p["category"] == "development"
    assert p["url"] is None


def test_project_client_is_nested_dict_with_expected_keys():
    p = parse_project_page(_project_html())
    assert set(p["client"]) == {
        "name",
        "member_since",
        "hiring_rate",
        "projects_open",
        "raw",
    }


# ===========================================================================
# parse_profile_page — ALL fields present (295-297, 302, 307-308, 313)
# ===========================================================================


def test_profile_all_fields_present():
    html = (
        "<html><body>"
        '<span class="rating">التقييم 4.8 من 5</span>'
        '<span class="reviews-count">123 تقييم</span>'
        '<div class="total-spent">$1,000 - $5,000</div>'
        '<div class="profile-country">السعودية</div>'
        '<span class="verified-badge"></span>'
        "</body></html>"
    )
    r = parse_profile_page(html)
    assert r["rating"] == 4.8  # lines 295-297
    assert r["reviews"] == 123  # line 302
    assert r["total_spent"] == Decimal("5000")  # lines 307-308 (hi wins)
    assert isinstance(r["total_spent"], Decimal)
    assert r["country"] == "السعودية"  # line 313
    assert r["verified"] is True


def test_profile_rating_via_data_type_attr_with_arabic_digits():
    r = parse_profile_page('<div data-type="rating">٤.٥</div>')
    assert r["rating"] == 4.5


def test_profile_rating_node_present_but_no_number_stays_none():
    """rating node matched, but text has no numeric -> rating stays None (295-297 guard)."""
    r = parse_profile_page('<span class="rating">لا يوجد تقييم</span>')
    assert r["rating"] is None


def test_profile_total_spent_single_number_uses_lo():
    """parse_budget single number => hi is None, so total_spent = hi or lo = lo (line 308)."""
    r = parse_profile_page('<div class="total-spent">$2,000</div>')
    assert r["total_spent"] == Decimal("2000")


def test_profile_total_spent_no_number_is_none():
    r = parse_profile_page('<div class="total-spent">غير محدد</div>')
    assert r["total_spent"] is None


def test_profile_country_blank_node_normalises_to_none():
    """country node present but blank -> None (line 313 `or None`)."""
    r = parse_profile_page('<div class="profile-country">   </div>')
    assert r["country"] is None


def test_profile_verified_via_fa_check_circle():
    r = parse_profile_page('<i class="fa-check-circle"></i>')
    assert r["verified"] is True


def test_profile_verified_via_data_type_attr():
    r = parse_profile_page('<span data-type="verified"></span>')
    assert r["verified"] is True


def test_profile_all_fields_absent_fail_closed_defaults():
    r = parse_profile_page("<html><body></body></html>")
    assert r == {
        "rating": None,
        "reviews": None,
        "total_spent": None,
        "country": None,
        "verified": False,
    }


def test_profile_reviews_arabic_digits():
    r = parse_profile_page('<span data-type="reviews">٤٢ تقييم</span>')
    assert r["reviews"] == 42


def test_profile_reviews_node_present_no_digit_is_none():
    r = parse_profile_page('<span class="reviews-count">لا مراجعات</span>')
    assert r["reviews"] is None
