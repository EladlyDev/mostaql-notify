"""T038 — integration coverage for the optional auto personal-status transition in the re-check loop.

Same no-network style as test_recheck_cycle.py. Proves the gated, reversible Interested→Expired/Missed
rule (research R8 / data-model state machine):

- toggle OFF (default): an interested-not-applied project that closes is left exactly as the owner had
  it — but the Mostaql ``site_status`` is still synced (FR-026 is always-on);
- toggle ON: that project becomes ``expired_missed`` (timestamped, ``auto_status_from="interested"``),
  with notes/tags untouched;
- an Applied / Won / Lost record (or an Interested record that has an ``applied_at``) is never touched;
- a deliberately-set non-interested status is never overwritten.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from mostaql_notifier.db.models import (
    EvalStatus,
    PersonalRecord,
    Project,
    ProjectStatus,
)
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.scoring import service
from mostaql_notifier.worker.recheck import run_recheck_cycle
from tests.api.conftest import make_client, make_personal_record, make_project

from ._helpers import FakeFetcher, make_sender, set_setting

pytestmark = pytest.mark.asyncio

_CLOSED = '<bdi class="label label-prj-closed">مغلق</bdi>'


def _closed_page(*, status: str = _CLOSED) -> str:
    """A structurally-valid project page reporting a non-open status."""
    return (
        "<html><body>"
        '<div class="meta-label">حالة المشروع</div>'
        f'<div class="meta-value">{status}</div>'
        '<div class="meta-label">الميزانية</div>'
        '<div class="meta-value"><span dir="rtl">$300.00 - $500.00</span></div>'
        '<div data-type="employer_widget">'
        '<h5 class="profile__name"><bdi>Acme Corp</bdi></h5>'
        '<table class="table-meta"><tbody>'
        "<tr><td>تاريخ التسجيل</td><td><time>2024</time></td></tr>"
        "<tr><td>معدل التوظيف</td><td><label>75.00%</label></td></tr>"
        "</tbody></table></div>"
        '<div class="offers-section"><span class="count">12</span></div>'
        "</body></html>"
    )


def _zero_delay(db_session, settings) -> None:
    set_setting(db_session, settings, "delay_min_seconds", 0)
    set_setting(db_session, settings, "delay_max_seconds", 0)


def _tracked_with_personal(
    db_session, settings, *, mostaql_id, now, status, applied_at=None, tags=None, notes="", _n=1
):
    """A qualified, open, scored project (tracking_active=True) carrying an owner personal record."""
    client = make_client(db_session, _n=_n)
    project = make_project(
        db_session,
        mostaql_id=mostaql_id,
        url=f"https://mostaql.com/project/{mostaql_id}",
        client_id=client.id,
        site_status=ProjectStatus.open,
        posted_at=now - timedelta(hours=2),
        eval_status=EvalStatus.qualified,
        bids_count=4,
    )
    service.score_project(db_session, project, settings=settings, now_utc=now)
    make_personal_record(
        db_session,
        project=project,
        status=status,
        applied_at=applied_at,
        tags=list(tags or []),
        notes=notes,
    )
    db_session.commit()
    return project


async def test_disabled_leaves_interested_unchanged_but_still_syncs_site_status(db_session, settings):
    _zero_delay(db_session, settings)
    # auto_status_personal_enabled defaults to False.
    now = utcnow()
    project = _tracked_with_personal(
        db_session, settings, mostaql_id="8001", now=now,
        status="interested", tags=["a", "b"], notes="keep me",
    )

    fetcher = FakeFetcher([("/project/8001", 200, _closed_page(), None)])
    await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    pr = db_session.get(PersonalRecord, project.id)
    assert pr.status == "interested"  # toggle off ⇒ no auto transition
    assert pr.auto_status_from is None and pr.auto_status_at is None
    assert pr.tags == ["a", "b"] and pr.notes == "keep me"  # nothing deleted
    # FR-026: the Mostaql status is synced by the loop regardless of the personal-status toggle.
    assert db_session.get(Project, project.id).site_status is ProjectStatus.closed


async def test_enabled_transitions_interested_not_applied_to_expired_missed(db_session, settings):
    _zero_delay(db_session, settings)
    set_setting(db_session, settings, "auto_status_personal_enabled", True)
    now = utcnow()
    project = _tracked_with_personal(
        db_session, settings, mostaql_id="8002", now=now,
        status="interested", tags=["x"], notes="my notes",
    )

    fetcher = FakeFetcher([("/project/8002", 200, _closed_page(), None)])
    await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    pr = db_session.get(PersonalRecord, project.id)
    assert pr.status == "expired_missed"
    assert pr.auto_status_from == "interested"  # reversible trail recorded
    assert pr.auto_status_at == now
    assert pr.status_changed_at == now
    assert pr.tags == ["x"] and pr.notes == "my notes"  # owner data survives
    assert db_session.get(Project, project.id).site_status is ProjectStatus.closed


async def test_enabled_never_touches_applied_won_lost_or_applied_interested(db_session, settings):
    _zero_delay(db_session, settings)
    set_setting(db_session, settings, "auto_status_personal_enabled", True)
    now = utcnow()
    p_applied = _tracked_with_personal(
        db_session, settings, mostaql_id="8003", now=now,
        status="applied", applied_at=now - timedelta(days=1), _n=1,
    )
    p_won = _tracked_with_personal(db_session, settings, mostaql_id="8004", now=now, status="won", _n=2)
    p_lost = _tracked_with_personal(db_session, settings, mostaql_id="8005", now=now, status="lost", _n=3)
    # Interested but already applied-to ⇒ guarded by applied_at, must NOT transition.
    p_int_applied = _tracked_with_personal(
        db_session, settings, mostaql_id="8006", now=now,
        status="interested", applied_at=now - timedelta(hours=3), _n=4,
    )

    # One broad route closes every project in the batch.
    fetcher = FakeFetcher([("/project/", 200, _closed_page(), None)])
    await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    for project, expected in (
        (p_applied, "applied"),
        (p_won, "won"),
        (p_lost, "lost"),
        (p_int_applied, "interested"),
    ):
        pr = db_session.get(PersonalRecord, project.id)
        assert pr.status == expected
        assert pr.auto_status_from is None and pr.auto_status_at is None


async def test_enabled_does_not_overwrite_a_deliberately_set_status(db_session, settings):
    _zero_delay(db_session, settings)
    set_setting(db_session, settings, "auto_status_personal_enabled", True)
    now = utcnow()
    project = _tracked_with_personal(
        db_session, settings, mostaql_id="8007", now=now, status="ignored", notes="leave it",
    )

    fetcher = FakeFetcher([("/project/8007", 200, _closed_page(), None)])
    await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    pr = db_session.get(PersonalRecord, project.id)
    assert pr.status == "ignored"  # not "interested" ⇒ never auto-changed
    assert pr.auto_status_from is None
    assert pr.notes == "leave it"
