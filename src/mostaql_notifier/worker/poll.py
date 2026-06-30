"""One poll cycle: discover → ingest (idempotent) → evaluate (fail-closed) → notify → log run.

Reliability (FR-002/030): each project is processed in its own try/except so one failure increments
the run's error_count and is skipped — it never crashes the loop.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from ..config.settings_store import app_state_set
from ..db.models import (
    Client,
    EvalStatus,
    Project,
    ProjectStatus,
    RunStatus,
    ScrapeRun,
    derive_client_key,
)
from ..db.types import utcnow
from ..notify.format import build_project_keyboard
from ..qualify.budget_policy import load_policy, recompute_floor, save_policy
from ..qualify.filters import qualify
from ..scraper.mostaql import merge_bids_count, parse_listing, parse_project_page
from ..worker.circuit_breaker import (
    CircuitBreaker,
    Classification,
    classify_response,
    is_clearly_nonempty,
)
from ..worker.politeness import polite_delay

log = logging.getLogger("mostaql.poll")


async def run_poll_cycle(session, fetcher, sender, settings, *, now=None) -> ScrapeRun | None:
    settings.reload()
    # Owner-initiated pause (Feature 3, FR-028): skip the cycle QUIETLY — write no scrape_run so an
    # intentional idle never turns the health light red (a pause is not a fault). Checked before any
    # run row is created; the bot/dashboard toggle the watcher_paused settings flag.
    if settings.get_bool("watcher_paused"):
        log.info("watcher paused; skipping poll cycle (no scrape_run written)")
        return None
    now = now or utcnow()
    owner_tz = settings.get_str("owner_timezone")
    breaker = CircuitBreaker(session)

    run = ScrapeRun(started_at=now, status=RunStatus.running)
    session.add(run)
    session.commit()

    if breaker.is_paused():
        run.status = RunStatus.blocked
        run.notes = f"circuit breaker paused until {breaker.resume_at()}"
        run.finished_at = utcnow()
        session.commit()
        return run

    # Recompute the dynamic budget floor once per cycle, before evaluating (research R5).
    policy = load_policy(session, settings)
    new_floor = recompute_floor(policy.active_floor, settings, session)
    if new_floor != policy.active_floor:
        policy.active_floor = new_floor
        save_policy(session, policy)

    # 1) Fetch the listing.
    listing_url = settings.get_str("listing_url")
    result = await fetcher.get(listing_url, referer="https://mostaql.com/")
    cls = classify_response(result, settings)
    if cls is not Classification.ok:
        await _handle_block(session, sender, breaker, settings, run, cls, detail=f"listing http={result.status}")
        return run

    # 2) Parse the listing (discovery only). parse_listing is fail-soft (it skips unidentifiable
    # rows rather than raising), so a listing-shape change surfaces as "0 rows on a clearly
    # non-empty page" below — the reachable structure-change signal.
    rows = parse_listing(result.body)
    if not rows and is_clearly_nonempty(result, settings):
        await _handle_block(session, sender, breaker, settings, run, Classification.structure_change,
                            detail="0 rows on a clearly non-empty listing")
        return run

    run.found_count = len(rows)

    # 3) First-run baseline: seed seen-state, notify nothing (research R7).
    if session.query(Project).count() == 0 and settings.get_bool("baseline_on_first_run"):
        for row in rows:
            session.add(Project(
                mostaql_id=row["mostaql_id"], url=row.get("url"),
                title=row.get("title"), category=settings.get_str("category_slug"),
                bids_count=row.get("bids_count"),  # authoritative uncapped listing total
                site_status=ProjectStatus.unknown, eval_status=EvalStatus.baseline,
                scraped_at=now, raw={"listing": row},
            ))
        session.commit()
        run.notes = "first-run baseline; notified nothing"
        await _finish_success(session, breaker, sender, settings, run)
        return run

    # 4) Idempotent ingest: insert new ids as pending; existing ids are re-observations (no change).
    existing_ids = {mid for (mid,) in session.query(Project.mostaql_id).all()}
    for row in rows:
        if row["mostaql_id"] in existing_ids:
            run.updated_count += 1
        else:
            session.add(Project(
                mostaql_id=row["mostaql_id"], url=row.get("url"),
                title=row.get("title"), category=settings.get_str("category_slug"),
                bids_count=row.get("bids_count"),  # authoritative uncapped listing total
                site_status=ProjectStatus.unknown, eval_status=EvalStatus.pending,
                scraped_at=now, raw={"listing": row},
            ))
            run.new_count += 1
    session.commit()

    # 5) Evaluate pending projects (new + retried), capped per cycle (politeness).
    max_attempts = settings.get_int("max_eval_attempts")
    max_age = timedelta(hours=settings.get_int("pending_max_age_hours"))
    cap = settings.get_int("max_fetches_per_cycle")

    pending = (
        session.query(Project)
        .filter(Project.eval_status == EvalStatus.pending)
        .order_by(Project.scraped_at.asc())
        .all()
    )
    evaluated = 0
    for project in pending:
        # Terminal conditions (FR-005): too many attempts or too old → eval_error (alerted, not dropped).
        if project.eval_attempts >= max_attempts or (now - project.scraped_at) > max_age:
            project.eval_status = EvalStatus.eval_error
            project.last_eval_at = utcnow()
            session.commit()
            run.error_count += 1
            await _safe_alert(sender, kind="EVAL_ERROR",
                              detail=f"project {project.mostaql_id} unresolved after {project.eval_attempts} tries",
                              run=run)
            continue
        if evaluated >= cap:
            break
        evaluated += 1
        try:
            await polite_delay(settings)
            stop = await _evaluate_project(session, fetcher, sender, settings, breaker, run,
                                           project, policy, owner_tz)
            if stop:  # block detected mid-cycle — back off, stop hammering
                await _finish_blocked(session, run)
                return run
        except Exception as exc:  # one bad project must not crash the run (FR-030)
            log.exception("project %s failed", project.mostaql_id)
            project.eval_attempts += 1
            project.last_eval_at = utcnow()
            session.commit()
            run.error_count += 1
            run.notes = (run.notes or "") + f"\n{project.mostaql_id}: {exc}"

    # At-least-once delivery: drain qualified projects whose notification has not yet landed.
    await _drain_unnotified(session, sender, settings, run, owner_tz)

    await _finish_success(session, breaker, sender, settings, run)
    return run


async def _drain_unnotified(session, sender, settings, run, owner_tz) -> None:
    """(Re)send every qualified project that is not yet notified — the single delivery point.

    Constitution VI (at-least-once): a transient send failure leaves the project ``notified=False``
    with no log row, so the NEXT cycle retries it here; dedup (``NotificationLog.dedup_key``) keeps
    it at-most-once. A *permanent* send error (e.g. ``BadRequest``) can never succeed, so it is
    terminal: alert once and move the project to ``eval_error`` rather than retry it forever.
    """
    unsent = (
        session.query(Project)
        .filter(Project.eval_status == EvalStatus.qualified, Project.notified.is_(False))
        .order_by(Project.qualified_at.asc())
        .all()
    )
    for project in unsent:
        client = (
            session.get(Client, project.client_id) if project.client_id is not None else None
        )
        try:
            await sender.send_project_notification(
                session, project, client, now_utc=utcnow(), owner_tz=owner_tz,
                reply_markup=build_project_keyboard(project),  # Feature 3 inline action buttons
            )
        except Exception as exc:  # permanent delivery failure -> terminal + fail-loud alert
            log.exception("permanent delivery failure for project %s", project.mostaql_id)
            project.eval_status = EvalStatus.eval_error
            project.last_eval_at = utcnow()
            session.commit()
            run.error_count += 1
            await _safe_alert(
                sender,
                kind="NOTIFY_ERROR",
                detail=f"project {project.mostaql_id} delivery failed permanently: {exc}",
                run=run,
                action="skipped (permanent)",
            )


async def _evaluate_project(session, fetcher, sender, settings, breaker, run, project, policy, owner_tz) -> bool:
    """Returns True if a block was detected (caller should stop the cycle)."""
    result = await fetcher.get(project.url, referer=settings.get_str("listing_url"))
    cls = classify_response(result, settings)
    if cls in (Classification.blocked, Classification.challenge):
        transitioned = breaker.record_failure(hard=True, settings=settings)
        if transitioned:
            await _safe_alert(sender, kind=cls.value.upper(),
                              detail=f"project fetch {project.mostaql_id} http={result.status}", run=run)
        return True
    if cls is Classification.transient:
        project.eval_attempts += 1
        project.last_eval_at = utcnow()
        session.commit()
        run.error_count += 1
        return False

    data = parse_project_page(result.body)  # may raise ParseError -> caught by caller as a skip

    # Upsert the client snapshot (no /u/ profile reachable — see models note).
    cdata = data.get("client") or {}
    ckey = derive_client_key(cdata.get("name"), cdata.get("member_since"))
    client = session.query(Client).filter_by(mostaql_id=ckey).one_or_none()
    if client is None:
        client = Client(mostaql_id=ckey, first_seen_at=utcnow())
        session.add(client)
    client.name = cdata.get("name")
    client.hiring_rate = cdata.get("hiring_rate")
    client.projects_open = cdata.get("projects_open")
    client.member_since = cdata.get("member_since")
    client.last_refreshed_at = utcnow()
    client.raw = cdata.get("raw") or cdata
    session.flush()

    # Update the project from its page (single source of truth).
    project.client_id = client.id
    project.title = data.get("title") or project.title
    project.description = data.get("description")
    project.category = data.get("category") or project.category
    project.skills = data.get("skills")
    project.budget_min = _dec(data.get("budget_min"))
    project.budget_max = _dec(data.get("budget_max"))
    project.currency = data.get("currency")
    # Detail-page bids cap at 50 cards; keep the larger of it and the (uncapped) listing total.
    project.bids_count = merge_bids_count(data.get("bids_count"), project.bids_count)
    project.posted_at = data.get("posted_at")
    project.site_status = data.get("site_status") or ProjectStatus.unknown
    project.raw = {**(project.raw or {}), "project": data.get("raw", {})}
    project.eval_attempts += 1
    project.last_eval_at = utcnow()

    q = qualify(project, client, policy, settings)
    if q.qualified:
        project.eval_status = EvalStatus.qualified
        project.tier = q.tier
        project.qualified_at = utcnow()
        session.commit()
        # Delivery is NOT done here: it is a separate, retriable obligation drained every cycle
        # (see _drain_unnotified) so a failed send is retried instead of being silently dropped.
    else:
        project.eval_status = EvalStatus.disqualified
        session.commit()
    return False


async def _handle_block(session, sender, breaker, settings, run, cls, *, detail):
    transitioned = breaker.record_failure(hard=cls is not Classification.transient, settings=settings)
    run.status = RunStatus.blocked if cls is not Classification.transient else RunStatus.failed
    run.notes = f"{cls.value}: {detail}"
    run.finished_at = utcnow()
    session.commit()
    if transitioned:
        await _safe_alert(sender, kind=cls.value.upper(), detail=detail, run=run,
                          action=f"backing off until {breaker.resume_at()}")


async def _finish_blocked(session, run):
    run.status = RunStatus.blocked
    run.finished_at = utcnow()
    session.commit()


async def _finish_success(session, breaker, sender, settings, run):
    recovered = breaker.record_success()
    run.status = RunStatus.partial if run.error_count else RunStatus.success
    run.finished_at = utcnow()
    app_state_set(session, "last_successful_poll_at", utcnow().isoformat())
    session.commit()
    if recovered:
        await _safe_alert(sender, kind="RECOVERED", detail="access restored", run=run, action="resumed")


async def _safe_alert(sender, *, kind, detail, run, action="backing off"):
    from ..notify.format import build_health_alert
    try:
        text = build_health_alert(kind=kind, detail=detail, action=action,
                                  found=run.found_count, new=run.new_count,
                                  updated=run.updated_count, errors=run.error_count)
        await sender.send_alert(text)
    except Exception:
        log.exception("failed to send health alert (%s)", kind)


def _dec(v):
    return Decimal(str(v)) if v is not None else None
