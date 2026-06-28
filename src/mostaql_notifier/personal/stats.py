"""Shared figures for the bot's ``/stats`` + ``/health`` and the dashboard Home (Feature 3).

One implementation so the dashboard and Telegram report identical numbers. Day boundaries are
computed in the owner timezone then expressed in UTC (matching ``api/routers/home.py``), so
"today" means the owner's calendar day (constitution V).
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config.settings_store import SettingsStore
from ..db.models import Client, PersonalRecord, Project, RunStatus, ScrapeRun
from . import statuses


def today_start_utc(session: Session) -> datetime:
    """Start-of-today in the owner timezone, expressed in UTC. Bad tz → Africa/Cairo."""
    tz_name = SettingsStore(session).get_str("owner_timezone")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # invalid/unknown tz string — fall back to default
        tz = ZoneInfo("Africa/Cairo")
    local_midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)


def is_paused(session: Session) -> bool:
    """Whether the watcher is intentionally paused (the ``watcher_paused`` settings flag)."""
    return SettingsStore(session).get_bool("watcher_paused")


def per_stage_counts(session: Session) -> dict[str, int]:
    """Count of engaged records in each configured stage.

    Engaged = ``(favorite OR status != default) AND NOT hidden`` — the same predicate the board
    uses (research §8), so ``/stats`` and the board agree. Keys are every configured slug (zero when
    empty); a stored status removed from config is omitted (it has no column)."""
    default = statuses.default_status(session)
    rows = session.execute(
        select(PersonalRecord.status, func.count())
        .where(
            PersonalRecord.hidden.is_(False),
            (PersonalRecord.favorite.is_(True)) | (PersonalRecord.status != default),
        )
        .group_by(PersonalRecord.status)
    ).all()
    counts = {status: count for status, count in rows}
    return {s["key"]: counts.get(s["key"], 0) for s in statuses.list_statuses(session)}


def compute_stats(session: Session) -> dict:
    """The ``/stats`` payload: today's found/qualified, totals, and per-stage counts."""
    start = today_start_utc(session)
    found_today = session.scalar(
        select(func.count()).select_from(Project).where(Project.scraped_at >= start)
    )
    qualified_today = session.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.qualified_at.is_not(None), Project.qualified_at >= start)
    )
    total_projects = session.scalar(select(func.count()).select_from(Project))
    total_clients = session.scalar(select(func.count()).select_from(Client))
    return {
        "found_today": found_today or 0,
        "qualified_today": qualified_today or 0,
        "total_projects": total_projects or 0,
        "total_clients": total_clients or 0,
        "per_stage": per_stage_counts(session),
        "paused": is_paused(session),
    }


def compute_health(session: Session) -> dict:
    """The ``/health`` payload: latest run status + counts, last success time, and paused state — so
    an intentional idle is distinguishable from a fault (constitution VI)."""
    last_successful_scrape = session.scalar(
        select(func.max(ScrapeRun.finished_at)).where(ScrapeRun.status == RunStatus.success)
    )
    latest_run = session.scalar(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(1))
    return {
        "paused": is_paused(session),
        "last_successful_scrape": last_successful_scrape,
        "latest_run_status": latest_run.status.value if latest_run else None,
        "found_count": latest_run.found_count if latest_run else None,
        "new_count": latest_run.new_count if latest_run else None,
        "updated_count": latest_run.updated_count if latest_run else None,
        "error_count": latest_run.error_count if latest_run else None,
    }
