"""The single long-lived asyncio worker: AsyncIOScheduler poll loop + outbound Telegram (research §2).

Outbound-only — no Application/Updater, no get_updates. ExtBot gives AIORateLimiter; AsyncIOScheduler is
built inside the running loop; failures are loud (job-error listener + Telegram alerts).
"""
from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config.secrets import get_secrets, require_telegram
from ..config.settings_store import SettingsStore, app_state_get, app_state_set, seed_defaults
from ..db.migrate import upgrade_head
from ..db.session import get_sessionmaker
from ..db.types import utcnow
from ..notify.format import build_heartbeat
from ..notify.telegram import TelegramSender
from ..scoring.service import rescore_all
from ..scraper.httpx_fetcher import HttpxFetcher
from ..worker.poll import run_poll_cycle
from ..worker.recheck import run_recheck_cycle

log = logging.getLogger("mostaql.worker")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    secrets = get_secrets()
    require_telegram(secrets)

    # Self-migrate + seed settings on startup.
    upgrade_head()
    Session = get_sessionmaker()
    with Session() as s:
        seeded = seed_defaults(s)
        settings = SettingsStore(s)
        poll_interval = settings.get_int("poll_interval_seconds")
        misfire = settings.get_int("misfire_grace_seconds")
        heartbeat_hours = settings.get_int("heartbeat_hours")
        recheck_interval = settings.get_int("recheck_interval_seconds")
        # T015 — one-time opportunity-scoring backfill so already-collected projects get a score
        # (FR-005). Guarded by an app_state flag: runs once, then is a cheap no-op on every later boot.
        if app_state_get(s, "scoring_backfilled") != "true":
            scored = rescore_all(s, settings=settings, now_utc=utcnow())
            s.commit()
            app_state_set(s, "scoring_backfilled", "true")
            log.info("scoring backfill: scored %d qualified project(s)", scored)
    log.info("seeded %d settings; poll every %ss; re-check every %ss",
             seeded, poll_interval, recheck_interval)

    sender = TelegramSender(secrets.telegram_bot_token, secrets.telegram_chat_id)
    await sender.start()
    fetcher = HttpxFetcher()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    async def poll_job() -> None:
        with Session() as s:
            settings = SettingsStore(s)
            run = await run_poll_cycle(s, fetcher, sender, settings)
            if run is None:  # watcher intentionally paused — skipped quietly, no run row
                log.info("poll skipped: watcher paused")
                return
            log.info("run %s: found=%s new=%s updated=%s errors=%s status=%s",
                     run.id, run.found_count, run.new_count, run.updated_count,
                     run.error_count, run.status.value)

    async def recheck_job() -> None:
        with Session() as s:
            settings = SettingsStore(s)
            run = await run_recheck_cycle(s, fetcher, sender, settings)
            if run is None:  # watcher intentionally paused — skipped quietly, no run row
                log.info("recheck skipped: watcher paused")
                return
            log.info("recheck %s: found=%s checked=%s errors=%s status=%s",
                     run.id, run.found_count, run.found_count - run.error_count,
                     run.error_count, run.status.value)

    async def heartbeat_job() -> None:
        with Session() as s:
            last = app_state_get(s, "last_successful_poll_at")
            await sender.send_heartbeat(build_heartbeat(
                last_poll_iso=last or "never",
                active_floor=app_state_get(s, "active_budget_floor", "?"),
            ))
            app_state_set(s, "last_heartbeat_at", utcnow().isoformat())
            # downtime self-check (covers scheduler-alive-but-poll-failing).
            if last:
                gap = (utcnow() - datetime.fromisoformat(last)).total_seconds()
                if gap > 2 * poll_interval:
                    await sender.send_alert(
                        f"⚠️ No successful poll for {int(gap)}s (> 2× interval). Investigate."
                    )

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(poll_job, IntervalTrigger(seconds=poll_interval), id="poll",
                      coalesce=True, max_instances=1, misfire_grace_time=misfire)
    scheduler.add_job(heartbeat_job, IntervalTrigger(hours=heartbeat_hours), id="heartbeat",
                      coalesce=True, max_instances=1)
    scheduler.add_job(recheck_job, IntervalTrigger(seconds=recheck_interval), id="recheck",
                      coalesce=True, max_instances=1, misfire_grace_time=misfire)

    def on_job_event(event) -> None:  # fail-loud: APScheduler otherwise swallows job errors
        if event.exception:
            log.error("job %s raised: %s", event.job_id, event.exception)
            loop.create_task(sender.send_alert(f"⚠️ job '{event.job_id}' failed: {event.exception}"))
        else:
            log.warning("job %s missed its run", event.job_id)
            loop.create_task(sender.send_alert(f"⚠️ job '{event.job_id}' missed a scheduled run"))

    scheduler.add_listener(on_job_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    scheduler.start()
    log.info("worker started")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # non-POSIX
            pass

    try:
        await stop_event.wait()
    finally:
        log.info("shutting down")
        scheduler.shutdown(wait=True)
        await fetcher.aclose()
        await sender.aclose()
