"""Pure tests for notify.format — no Telegram network involved."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from mostaql_notifier.db.models import Client, Project
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.notify.format import (
    build_project_message,
    relative_since,
)


def _make_pair(now):
    client = Client(
        mostaql_id="derived:abc123",
        name="عميل تجريبي",
        hiring_rate=87.0,
        last_refreshed_at=now,
        first_seen_at=now,
        raw={},
    )
    project = Project(
        mostaql_id="proj-42",
        title="تطوير موقع <ووردبريس>",  # RTL + an angle bracket to prove escaping
        url="https://mostaql.com/project/proj-42",
        category="تطوير, برمجة, تقنية",
        budget_min=Decimal("250"),
        budget_max=Decimal("500"),
        currency="USD",
        bids_count=7,
        posted_at=now - timedelta(hours=2),
        scraped_at=now,
        tier=1,
        raw={},
    )
    return project, client


def test_build_project_message_contains_required_fields():
    now = utcnow()
    project, client = _make_pair(now)

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    assert "تطوير موقع" in msg  # the (escaped) title text survives
    assert "Tier 1" in msg
    assert "87%" in msg  # hiring rate formatted with :.0f
    assert project.url in msg
    assert "تطوير, برمجة, تقنية" in msg
    assert "2h ago" in msg  # posted_at age
    assert len(msg) < 4096


def test_build_project_message_is_html_safe():
    now = utcnow()
    project, client = _make_pair(now)

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    # The literal angle brackets from the title must be escaped, not raw.
    assert "<ووردبريس>" not in msg
    assert "&lt;ووردبريس&gt;" in msg
    # Our own intended tags remain.
    assert "<b>" in msg and "</b>" in msg


def test_build_project_message_budget_has_no_trailing_zeros():
    now = utcnow()
    project, client = _make_pair(now)

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    assert "250" in msg and "500" in msg
    assert "250.00" not in msg and "500.00" not in msg


def test_relative_since_none_is_unknown():
    assert relative_since(None, utcnow()) == "unknown"


def test_relative_since_buckets():
    now = utcnow()
    assert relative_since(now - timedelta(minutes=12), now) == "12m ago"
    assert relative_since(now - timedelta(hours=2), now) == "2h ago"
    assert relative_since(now - timedelta(days=3), now) == "3d ago"
