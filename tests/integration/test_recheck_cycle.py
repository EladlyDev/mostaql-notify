"""T024 — integration coverage for the watch-over-time re-check cycle (worker/recheck.py).

Mirrors test_poll_cycle.py's no-network style: the async fetcher is stubbed to return canned
project-page bodies (FakeFetcher routes by URL substring), the sender is faked, and the DB/settings
come from the shared fixtures. Each test drives ``run_recheck_cycle`` with an injected ``now`` so the
score math is deterministic.

Covered: snapshot append + re-score while open (more bids ⇒ lower score); status→closed FREEZES the
score and records ``Outcome.closed_no_hire``; an awarded page ⇒ ``Outcome.hired``; an ambiguous page ⇒
``Outcome.unknown`` (never hired); a project closed past ``tracking_grace_hours`` flips
``tracking_active=False`` and is not re-fetched; a too-recently-checked project is not selected; a
failing project is logged + skipped without stalling the batch; ``watcher_paused`` ⇒ ``None`` + no run.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from mostaql_notifier.db.models import (
    EvalStatus,
    Outcome,
    ProjectScore,
    ProjectSnapshot,
    ProjectStatus,
    RunStatus,
    ScrapeRun,
)
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.scoring import service
from mostaql_notifier.worker.recheck import run_recheck_cycle
from tests.api.conftest import make_client, make_project, make_project_score

from ._helpers import FakeFetcher, make_sender, set_setting

pytestmark = pytest.mark.asyncio

_OPEN = '<bdi class="label label-prj-open">مفتوح</bdi>'
_CLOSED = '<bdi class="label label-prj-closed">مغلق</bdi>'
_AWARDED = '<bdi class="label label-prj-awarded">تم الترسية</bdi>'
_UNKNOWN = '<bdi class="label">؟؟؟</bdi>'


def _project_html(
    *,
    status: str = _OPEN,
    bids: int = 4,
    hiring_rate: str = "75.00%",
    budget: str = "$300.00 - $500.00",
    client_name: str = "Acme Corp",
    member_since: str = "10 يناير 2024",
) -> str:
    """A minimal, structurally-valid project page the real parser accepts (status + budget + bids +
    an employer widget carrying a hiring-rate row)."""
    return (
        "<html><body>"
        '<div class="meta-label">حالة المشروع</div>'
        f'<div class="meta-value">{status}</div>'
        '<div class="meta-label">الميزانية</div>'
        f'<div class="meta-value"><span dir="rtl">{budget}</span></div>'
        '<div data-type="employer_widget">'
        f'<h5 class="profile__name"><bdi>{client_name}</bdi></h5>'
        '<table class="table-meta"><tbody>'
        f"<tr><td>تاريخ التسجيل</td><td><time>{member_since}</time></td></tr>"
        f"<tr><td>معدل التوظيف</td><td><label>{hiring_rate}</label></td></tr>"
        "<tr><td>المشاريع المفتوحة</td><td>2</td></tr>"
        "</tbody></table></div>"
        f'<div class="offers-section"><span class="count">{bids}</span></div>'
        "</body></html>"
    )


def _zero_delay(db_session, settings) -> None:
    set_setting(db_session, settings, "delay_min_seconds", 0)
    set_setting(db_session, settings, "delay_max_seconds", 0)


def _tracked_open_project(db_session, settings, *, mostaql_id, now, bids=4, _n=1):
    """A qualified, open, freshly-scored project with a live ProjectScore (tracking_active=True)."""
    client = make_client(db_session, _n=_n)
    project = make_project(
        db_session,
        mostaql_id=mostaql_id,
        url=f"https://mostaql.com/project/{mostaql_id}",
        client_id=client.id,
        bids_count=bids,
        site_status=ProjectStatus.open,
        posted_at=now - timedelta(hours=2),
        eval_status=EvalStatus.qualified,
        tier=1,
    )
    row = service.score_project(db_session, project, settings=settings, now_utc=now)
    db_session.commit()
    return project, row.score


async def test_open_recheck_appends_snapshot_and_drops_score_on_more_bids(db_session, settings):
    _zero_delay(db_session, settings)
    now = utcnow()
    project, s0 = _tracked_open_project(db_session, settings, mostaql_id="9001", now=now, bids=4)

    fetcher = FakeFetcher([("/project/9001", 200, _project_html(status=_OPEN, bids=40), None)])
    run = await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    assert run is not None and run.kind == "recheck"
    assert run.status is RunStatus.success and run.found_count == 1
    score_row = db_session.get(ProjectScore, project.id)
    # More bids ⇒ stiffer competition ⇒ a strictly lower (re-computed, not frozen) score.
    assert score_row.score < s0
    assert score_row.outcome is Outcome.open
    assert score_row.last_checked_at == now
    snaps = (
        db_session.query(ProjectSnapshot)
        .filter_by(project_id=project.id)
        .order_by(ProjectSnapshot.captured_at)
        .all()
    )
    assert len(snaps) == 1
    assert snaps[-1].bids_count == 40
    assert snaps[-1].site_status is ProjectStatus.open
    assert snaps[-1].score == score_row.score  # the snapshot carries the freshly-computed score
    assert db_session.query(ScrapeRun).filter_by(kind="recheck").count() == 1


async def test_close_freezes_score_and_records_closed_no_hire(db_session, settings):
    _zero_delay(db_session, settings)
    now = utcnow()
    project, frozen = _tracked_open_project(db_session, settings, mostaql_id="9002", now=now, bids=4)

    # The page now shows CLOSED with far more bids — the score must NOT move (frozen once closed).
    fetcher = FakeFetcher([("/project/9002", 200, _project_html(status=_CLOSED, bids=99), None)])
    await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    score_row = db_session.get(ProjectScore, project.id)
    assert score_row.score == frozen  # FROZEN despite the climbing bids
    assert score_row.outcome is Outcome.closed_no_hire
    assert project.site_status is ProjectStatus.closed
    assert score_row.closed_observed_at == now
    assert score_row.tracking_active is True  # still within the grace window
    snap = db_session.query(ProjectSnapshot).filter_by(project_id=project.id).one()
    assert snap.score == frozen and snap.site_status is ProjectStatus.closed


async def test_awarded_page_records_hired(db_session, settings):
    _zero_delay(db_session, settings)
    now = utcnow()
    project, frozen = _tracked_open_project(db_session, settings, mostaql_id="9003", now=now)

    fetcher = FakeFetcher([("/project/9003", 200, _project_html(status=_AWARDED), None)])
    await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    score_row = db_session.get(ProjectScore, project.id)
    assert score_row.outcome is Outcome.hired
    assert score_row.score == frozen  # frozen on close
    assert project.site_status is ProjectStatus.awarded


async def test_unknown_page_is_never_hired(db_session, settings):
    _zero_delay(db_session, settings)
    now = utcnow()
    project, _ = _tracked_open_project(db_session, settings, mostaql_id="9004", now=now)

    fetcher = FakeFetcher([("/project/9004", 200, _project_html(status=_UNKNOWN), None)])
    await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    score_row = db_session.get(ProjectScore, project.id)
    assert score_row.outcome is Outcome.unknown  # ambiguous ending — never inferred as hired
    assert project.site_status is ProjectStatus.unknown


async def test_closed_past_grace_stops_tracking_and_is_not_refetched(db_session, settings):
    _zero_delay(db_session, settings)
    now = utcnow()
    grace = settings.get_int("tracking_grace_hours")
    client = make_client(db_session, _n=1)
    project = make_project(
        db_session,
        mostaql_id="9005",
        url="https://mostaql.com/project/9005",
        client_id=client.id,
        site_status=ProjectStatus.closed,
        eval_status=EvalStatus.qualified,
    )
    make_project_score(
        db_session,
        project=project,
        score=55.0,
        tracking_active=True,
        closed_observed_at=now - timedelta(hours=grace + 1),  # aged out past the grace window
        last_checked_at=now - timedelta(hours=2),
    )
    db_session.commit()

    fetcher = FakeFetcher([("/project/9005", 200, _project_html(status=_CLOSED), None)])
    run = await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    score_row = db_session.get(ProjectScore, project.id)
    assert score_row.tracking_active is False  # retired past grace
    assert run.found_count == 0  # not selected for a fetch
    assert not any("9005" in c for c in fetcher.calls)  # "stop re-checking" — no fetch issued


async def test_too_recently_checked_is_not_selected(db_session, settings):
    _zero_delay(db_session, settings)
    now = utcnow()
    min_interval = settings.get_int("recheck_min_interval_seconds")
    client = make_client(db_session, _n=1)
    project = make_project(
        db_session,
        mostaql_id="9006",
        url="https://mostaql.com/project/9006",
        client_id=client.id,
        site_status=ProjectStatus.open,
        posted_at=now - timedelta(hours=2),
        eval_status=EvalStatus.qualified,
    )
    make_project_score(
        db_session,
        project=project,
        score=60.0,
        tracking_active=True,
        last_checked_at=now - timedelta(seconds=min_interval // 2),  # checked too recently
    )
    db_session.commit()

    fetcher = FakeFetcher([("/project/9006", 200, _project_html(), None)])
    run = await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    assert run.found_count == 0
    assert not any("9006" in c for c in fetcher.calls)
    assert db_session.query(ProjectSnapshot).filter_by(project_id=project.id).count() == 0


async def test_failing_project_is_skipped_without_stalling_the_batch(db_session, settings):
    _zero_delay(db_session, settings)
    now = utcnow()
    bad, _ = _tracked_open_project(db_session, settings, mostaql_id="9007", now=now, _n=1)
    good, _ = _tracked_open_project(db_session, settings, mostaql_id="9008", now=now, _n=2)

    fetcher = FakeFetcher(
        [
            # A structurally-broken page (no employer widget) makes the parser raise ParseError.
            ("/project/9007", 200, "<html><body>broken page</body></html>", None),
            ("/project/9008", 200, _project_html(bids=10), None),
        ]
    )
    run = await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    assert run.error_count == 1
    assert run.status is RunStatus.partial
    # The good project was still processed despite the bad one failing first/at-all.
    assert db_session.query(ProjectSnapshot).filter_by(project_id=good.id).count() == 1
    assert db_session.query(ProjectSnapshot).filter_by(project_id=bad.id).count() == 0


async def test_watcher_paused_returns_none_and_writes_no_run(db_session, settings):
    set_setting(db_session, settings, "watcher_paused", True)
    now = utcnow()
    _tracked_open_project(db_session, settings, mostaql_id="9009", now=now)

    fetcher = FakeFetcher([("/project/9009", 200, _project_html(), None)])
    run = await run_recheck_cycle(db_session, fetcher, make_sender(), settings, now=now)

    assert run is None
    assert db_session.query(ScrapeRun).filter_by(kind="recheck").count() == 0
    assert not fetcher.calls  # nothing fetched on a quiet pause
