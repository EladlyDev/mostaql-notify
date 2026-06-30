"""Unit tests for the mostaql HTML parsers against captured fixtures."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mostaql_notifier.db.models import ProjectStatus
from mostaql_notifier.scraper.mostaql import (
    ParseError,
    parse_listing,
    parse_profile_page,
    parse_project_page,
)
from tests.conftest import read_fixture

# ---------------------------------------------------------------------------
# parse_listing
# ---------------------------------------------------------------------------


def test_parse_listing_returns_25_projects():
    rows = parse_listing(read_fixture("listing.html"))
    assert len(rows) == 25


def test_parse_listing_ids_are_numeric_strings():
    rows = parse_listing(read_fixture("listing.html"))
    assert rows, "expected at least one row"
    for r in rows:
        assert isinstance(r["mostaql_id"], str)
        assert r["mostaql_id"].isdigit()


def test_parse_listing_urls_contain_project_segment():
    rows = parse_listing(read_fixture("listing.html"))
    for r in rows:
        assert "/project/" in r["url"]


def test_parse_listing_extracts_title_and_client_name():
    rows = parse_listing(read_fixture("listing_small.html"))
    assert len(rows) == 2
    first = rows[0]
    assert first["mostaql_id"] == "9001"
    assert first["title"] == "مشروع مؤهل للتجربة"
    assert first["client_name"] == "Acme Corp"


def test_parse_listing_empty_html_yields_no_rows():
    assert parse_listing("<html><body></body></html>") == []


# ---------------------------------------------------------------------------
# parse_project_page — real fixture (project_page.html)
# ---------------------------------------------------------------------------


def test_parse_project_real_status_open():
    p = parse_project_page(read_fixture("project_page.html"))
    assert p["site_status"] is ProjectStatus.open


def test_parse_project_real_budget_and_currency():
    p = parse_project_page(read_fixture("project_page.html"))
    assert p["budget_min"] == Decimal("25")
    assert p["budget_max"] == Decimal("50")
    assert p["currency"] == "USD"
    assert isinstance(p["budget_min"], Decimal)
    assert isinstance(p["budget_max"], Decimal)


def test_parse_project_real_hiring_rate_is_none():
    # "لم يحسب بعد" -> unknown -> None (distinct from a real 0.0)
    p = parse_project_page(read_fixture("project_page.html"))
    assert p["client"]["hiring_rate"] is None


def test_parse_project_real_posted_at_is_aware_utc():
    p = parse_project_page(read_fixture("project_page.html"))
    posted = p["posted_at"]
    assert isinstance(posted, datetime)
    assert posted.tzinfo is not None
    assert posted.utcoffset() == timezone.utc.utcoffset(None)
    assert posted == datetime(2026, 6, 23, 12, 37, 21, tzinfo=timezone.utc)


def test_parse_project_real_title_and_category():
    p = parse_project_page(read_fixture("project_page.html"))
    assert p["title"] == "تعديل وإضافة ملاحظات أو تحسينات لتطبيق"
    assert p["category"] == "development"


def test_parse_project_real_client_fields():
    p = parse_project_page(read_fixture("project_page.html"))
    client = p["client"]
    assert client["name"] == "Nojoom C."
    assert client["projects_open"] == 1
    assert client["member_since"] == "22 يونيو 2026"
    assert client["raw"]["in_progress"] == 0


def test_parse_project_real_skills_are_deduped_list():
    p = parse_project_page(read_fixture("project_page.html"))
    skills = p["skills"]
    assert isinstance(skills, list)
    assert all(isinstance(s, str) for s in skills)
    assert len(skills) == len(set(skills))  # no mobile-panel duplicates
    assert "PHP" in skills


def test_parse_project_real_bids_count():
    # The real page carries one [data-bid-item] card per public offer inside
    # #bidsCollection-panel; this fixture has exactly 8. (Regression guard: the old
    # span.count selector silently returned None on every real page.)
    p = parse_project_page(read_fixture("project_page.html"))
    assert p["bids_count"] == 8


def test_parse_project_real_description_is_nonempty_text():
    # Description lives in #projectDetailsTab > div.text-wrapper-div on the real page.
    p = parse_project_page(read_fixture("project_page.html"))
    desc = p["description"]
    assert isinstance(desc, str)
    assert len(desc) > 50
    assert "flutter" in desc.lower()


# ---------------------------------------------------------------------------
# parse_project_page — synthetic qualifying fixture
# ---------------------------------------------------------------------------


def test_parse_project_qualifying_budget_max():
    p = parse_project_page(read_fixture("project_qualifying.html"))
    assert p["budget_max"] == Decimal("500")
    assert p["budget_min"] == Decimal("300")


def test_parse_project_qualifying_hiring_rate():
    p = parse_project_page(read_fixture("project_qualifying.html"))
    assert p["client"]["hiring_rate"] == 75.0


def test_parse_project_qualifying_status_open():
    p = parse_project_page(read_fixture("project_qualifying.html"))
    assert p["site_status"] is ProjectStatus.open


def test_parse_project_qualifying_skills_and_bids():
    p = parse_project_page(read_fixture("project_qualifying.html"))
    assert p["skills"] == ["لارافيل", "PHP"]
    assert p["bids_count"] == 4


def test_parse_project_qualifying_posted_at_aware_utc():
    p = parse_project_page(read_fixture("project_qualifying.html"))
    assert p["posted_at"] == datetime(2026, 6, 23, 12, 50, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# fail-closed / structure-change
# ---------------------------------------------------------------------------


def test_parse_project_without_meta_raises_parse_error():
    html = '<html><body><div data-type="employer_widget"></div></body></html>'
    with pytest.raises(ParseError):
        parse_project_page(html)


def test_parse_project_without_employer_widget_raises_parse_error():
    html = (
        '<html><body>'
        '<div class="meta-label">حالة المشروع</div>'
        '<div class="meta-value"><bdi class="label label-prj-open">مفتوح</bdi></div>'
        '</body></html>'
    )
    with pytest.raises(ParseError):
        parse_project_page(html)


def test_parse_project_without_hiring_row_raises_parse_error():
    html = (
        '<html><body>'
        '<div class="meta-label">حالة المشروع</div>'
        '<div class="meta-value"><bdi class="label label-prj-open">مفتوح</bdi></div>'
        '<div data-type="employer_widget">'
        '<h5 class="profile__name"><bdi>X</bdi></h5>'
        '<table class="table-meta"><tbody>'
        '<tr><td>تاريخ التسجيل</td><td><time>2024</time></td></tr>'
        '</tbody></table></div>'
        '</body></html>'
    )
    with pytest.raises(ParseError):
        parse_project_page(html)


def test_parse_project_unknown_status_fails_closed():
    html = (
        '<html><body>'
        '<div class="meta-label">حالة المشروع</div>'
        '<div class="meta-value"><bdi class="label">???</bdi></div>'
        '<div data-type="employer_widget">'
        '<h5 class="profile__name"><bdi>X</bdi></h5>'
        '<table class="table-meta"><tbody>'
        '<tr><td>معدل التوظيف</td><td><label>لم يحسب بعد</label></td></tr>'
        '</tbody></table></div>'
        '</body></html>'
    )
    p = parse_project_page(html)
    assert p["site_status"] is ProjectStatus.unknown


# ---------------------------------------------------------------------------
# parse_profile_page (tolerant best-effort)
# ---------------------------------------------------------------------------


def test_parse_profile_page_tolerates_missing_fields():
    result = parse_profile_page("<html><body></body></html>")
    assert result["rating"] is None
    assert result["reviews"] is None
    assert result["total_spent"] is None
    assert result["country"] is None
    assert result["verified"] is False
