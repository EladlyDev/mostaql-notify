"""The watch-over-time re-check cycle (Feature 4, Part B — research R5).

A second AsyncIOScheduler cadence that re-visits already-known projects: it refreshes their bids and
Mostaql status, appends an append-only ``project_snapshots`` row, re-scores while the project is still
open (and FREEZES the score once it closes), records a fail-closed ``Outcome``, retires a project from
tracking once it has been closed past the grace window, and — only when explicitly enabled — performs
the reversible Interested→Expired/Missed personal-status transition.

Politeness, block-detection and the circuit breaker are TRUE BY CONSTRUCTION: every primitive here is
the one the fast poll cycle (``worker/poll.py``) already uses — ``fetcher.get`` + ``classify_response``
+ ``CircuitBreaker`` + ``polite_delay`` + ``parse_project_page`` — so this module is thin orchestration
over already-tested helpers.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import and_, or_

from ..db.models import (
    Client,
    Outcome,
    Project,
    ProjectScore,
    ProjectSnapshot,
    ProjectStatus,
    RunStatus,
    ScrapeRun,
    derive_client_key,
)
from ..db.types import utcnow
from ..scoring import service as score_service
from ..scraper.mostaql import parse_project_page
from ..worker.circuit_breaker import CircuitBreaker, Classification, classify_response
from ..worker.politeness import polite_delay
from ..worker.poll import _finish_blocked, _safe_alert

log = logging.getLogger("mostaql.recheck")


async def run_recheck_cycle(session, fetcher, sender, settings, *, now=None) -> ScrapeRun | None:
    """Run one re-check cycle; returns the ``kind="recheck"`` ``ScrapeRun`` (or ``None`` if paused).

    Mirrors ``run_poll_cycle``: an owner-initiated pause is a QUIET skip (no run row, so an
    intentional idle never reddens the health light), and a circuit-breaker pause finishes the run as
    ``blocked`` without hammering the site.
    """
    settings.reload()
    # Owner-initiated pause (FR-021): skip QUIETLY — write no scrape_run, exactly like the poll cycle.
    if settings.get_bool("watcher_paused"):
        log.info("watcher paused; skipping re-check cycle (no scrape_run written)")
        return None
    now = now or utcnow()
    breaker = CircuitBreaker(session)

    run = ScrapeRun(kind="recheck", started_at=now, status=RunStatus.running)
    session.add(run)
    session.commit()

    if breaker.is_paused():
        run.status = RunStatus.blocked
        run.notes = f"circuit breaker paused until {breaker.resume_at()}"
        run.finished_at = utcnow()
        session.commit()
        return run

    grace_hours = settings.get_int("tracking_grace_hours")
    min_interval = settings.get_int("recheck_min_interval_seconds")
    batch_size = settings.get_int("recheck_batch_size")
    grace_cutoff = now - timedelta(hours=grace_hours)
    min_cutoff = now - timedelta(seconds=min_interval)

    # Retire (no fetch) any still-tracking project that has been closed/awarded past the grace window.
    # This is the literal "now − closed_observed_at ≥ grace ⇒ tracking_active=False" rule from the
    # data-model, applied to exactly the aged-out rows the due-selector intentionally drops — so a
    # project at the grace boundary can never be orphaned (tracking_active=True but never re-selected).
    retired = (
        session.query(ProjectScore)
        .join(Project, Project.id == ProjectScore.project_id)
        .filter(
            ProjectScore.tracking_active.is_(True),
            Project.site_status.in_([ProjectStatus.closed, ProjectStatus.awarded]),
            ProjectScore.closed_observed_at.isnot(None),
            ProjectScore.closed_observed_at < grace_cutoff,
        )
        .all()
    )
    for row in retired:
        row.tracking_active = False
    if retired:
        session.commit()

    # Select due projects, stalest first (NULL last_checked_at first), capped at the batch size.
    due = (
        session.query(Project)
        .join(ProjectScore, ProjectScore.project_id == Project.id)
        .filter(
            ProjectScore.tracking_active.is_(True),
            or_(
                ProjectScore.last_checked_at.is_(None),
                ProjectScore.last_checked_at <= min_cutoff,
            ),
            or_(
                Project.site_status == ProjectStatus.open,
                and_(
                    Project.site_status.in_([ProjectStatus.closed, ProjectStatus.awarded]),
                    or_(
                        ProjectScore.closed_observed_at.is_(None),
                        ProjectScore.closed_observed_at >= grace_cutoff,
                    ),
                ),
            ),
        )
        .order_by(
            ProjectScore.last_checked_at.is_(None).desc(),
            ProjectScore.last_checked_at.asc(),
        )
        .limit(batch_size)
        .all()
    )
    run.found_count = len(due)
    session.commit()  # persist the batch size now so a per-project rollback can't revert it

    for project in due:
        try:
            await polite_delay(settings)
            stop = await _recheck_one(
                session, fetcher, sender, settings, breaker, run, project,
                now=now, grace_hours=grace_hours,
            )
            if stop:  # block detected mid-cycle — back off, stop hammering, keep the run loud
                await _finish_blocked(session, run)
                return run
        except Exception as exc:  # one bad project must never stall the batch (FR-020)
            log.exception("re-check of project %s failed", project.mostaql_id)
            session.rollback()
            run.error_count += 1
            run.notes = (run.notes or "") + f"\n{project.mostaql_id}: {exc}"
            session.commit()

    await _finish_recheck(session, breaker, sender, run)
    return run


async def _recheck_one(
    session, fetcher, sender, settings, breaker, run, project, *, now, grace_hours
) -> bool:
    """Re-check one project. Returns True iff a block was detected (caller stops the cycle)."""
    result = await fetcher.get(project.url, referer=settings.get_str("listing_url"))
    cls = classify_response(result, settings)
    if cls in (Classification.blocked, Classification.challenge):
        transitioned = breaker.record_failure(hard=True, settings=settings)
        if transitioned:
            await _safe_alert(
                sender, kind=cls.value.upper(),
                detail=f"re-check fetch {project.mostaql_id} http={result.status}", run=run,
            )
        return True
    if cls is Classification.transient:
        run.error_count += 1
        return False

    data = parse_project_page(result.body, awarded_markers=settings.get_json("awarded_markers"))

    # Refresh the client's stats from the page only when the cached copy is stale (None-safe).
    _maybe_refresh_client(session, project, data, settings, now)

    # Always-on Mostaql sync (FR-026): the page is the single source of truth for bids + status.
    project.bids_count = data.get("bids_count")
    project.site_status = data.get("site_status") or ProjectStatus.unknown

    score_row = session.get(ProjectScore, project.id)

    # Re-score ONLY while open; once closed/awarded/unknown the score is FROZEN (keep the stored value;
    # the snapshot carries that frozen score).
    if project.site_status == ProjectStatus.open:
        score_row = score_service.score_project(session, project, settings=settings, now_utc=now)
        current_score = score_row.score
    else:
        current_score = score_row.score if score_row is not None else None

    # Append-only trajectory point (never update/delete a snapshot).
    session.add(
        ProjectSnapshot(
            project_id=project.id,
            captured_at=now,
            bids_count=project.bids_count,
            site_status=project.site_status,
            score=current_score,
        )
    )

    if score_row is not None:
        # Fail-closed outcome — NEVER infer "hired" from the absence of evidence.
        score_row.outcome = _outcome_for(project.site_status)
        # Grace: stamp the first non-open observation, then retire once past the window.
        if project.site_status is not ProjectStatus.open and score_row.closed_observed_at is None:
            score_row.closed_observed_at = now
        if score_row.closed_observed_at is not None and (
            now - score_row.closed_observed_at
        ) >= timedelta(hours=grace_hours):
            score_row.tracking_active = False
        score_row.last_checked_at = now

    # Optional, gated, reversible personal-status transition (FR-028).
    _maybe_auto_status(session, project, settings, now)

    session.commit()
    return False


def _outcome_for(site_status: ProjectStatus) -> Outcome:
    """Fail-closed map from the latest observed site status to a final outcome (data-model)."""
    if site_status is ProjectStatus.open:
        return Outcome.open
    if site_status is ProjectStatus.awarded:
        return Outcome.hired
    if site_status is ProjectStatus.closed:
        return Outcome.closed_no_hire  # a plain close with no award marker
    return Outcome.unknown  # ambiguous/unparseable — never "hired"


def _maybe_refresh_client(session, project, data, settings, now) -> None:
    """Refresh the project's client stats from the page only when the cached copy is stale.

    Throttled by ``client_refresh_hours`` (reusing the poll cycle's client-upsert shape). None-safe:
    creates the client if the project somehow has none yet.
    """
    cdata = data.get("client") or {}
    client = project.client
    if client is not None:
        last = client.last_refreshed_at
        if last is not None and (now - last) <= timedelta(
            hours=settings.get_int("client_refresh_hours")
        ):
            return  # still fresh — leave the cached stats untouched
    else:
        ckey = derive_client_key(cdata.get("name"), cdata.get("member_since"))
        client = session.query(Client).filter_by(mostaql_id=ckey).one_or_none()
        if client is None:
            # last_refreshed_at is NOT NULL, so set it now: the flush below (needed to obtain
            # client.id for project.client_id) would otherwise fail before the field is assigned.
            client = Client(mostaql_id=ckey, first_seen_at=now, last_refreshed_at=now)
            session.add(client)
            session.flush()
        project.client_id = client.id

    client.name = cdata.get("name")
    client.hiring_rate = cdata.get("hiring_rate")
    client.projects_open = cdata.get("projects_open")
    client.member_since = cdata.get("member_since")
    client.last_refreshed_at = now
    client.raw = cdata.get("raw") or cdata
    session.flush()


def _maybe_auto_status(session, project, settings, now) -> None:
    """Reversible Interested→Expired/Missed transition (T041) — strictly gated (FR-028).

    Fires ONLY when enabled, the project has just been observed closed/awarded, and the owner's record
    is exactly ``"interested"`` with no application recorded. NEVER on applied/won/lost or any other
    status; NEVER overwrites a status the owner set after the close (once it leaves ``"interested"`` the
    guard can never fire again); NEVER deletes notes/tags/files.
    """
    if not settings.get_bool("auto_status_personal_enabled"):
        return
    if project.site_status not in (ProjectStatus.closed, ProjectStatus.awarded):
        return
    record = project.personal
    if record is None or record.status != "interested" or record.applied_at is not None:
        return
    record.auto_status_from = "interested"
    record.auto_status_at = now
    record.status = "expired_missed"
    record.status_changed_at = now


async def _finish_recheck(session, breaker, sender, run) -> None:
    """Close out a non-blocked cycle: partial if anything errored, else success (Fail Loud on recover)."""
    recovered = breaker.record_success()
    run.status = RunStatus.partial if run.error_count else RunStatus.success
    run.finished_at = utcnow()
    session.commit()
    if recovered:
        await _safe_alert(sender, kind="RECOVERED", detail="access restored", run=run, action="resumed")
