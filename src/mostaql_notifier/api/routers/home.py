"""Home overview endpoint — today's counts, totals, and a never-false-green health signal."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config.settings_store import SettingsStore
from ...db.models import Client, Project, RunStatus, ScrapeRun
from ..deps import get_db
from ..schemas import HomeOverview

router = APIRouter(tags=["home"])


def _today_start_utc(session: Session) -> datetime:
    """Start-of-today in the owner timezone, expressed in UTC. Bad tz -> Africa/Cairo."""
    tz_name = SettingsStore(session).get_str("owner_timezone")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # invalid/unknown tz string — fall back to default
        tz = ZoneInfo("Africa/Cairo")
    local_midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)


@router.get("/api/home", response_model=HomeOverview)
def get_home(session: Annotated[Session, Depends(get_db)]) -> HomeOverview:
    today_start_utc = _today_start_utc(session)

    found_today = session.scalar(
        select(func.count()).select_from(Project).where(Project.scraped_at >= today_start_utc)
    )
    qualified_today = session.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.qualified_at.is_not(None), Project.qualified_at >= today_start_utc)
    )
    total_projects = session.scalar(select(func.count()).select_from(Project))
    total_clients = session.scalar(select(func.count()).select_from(Client))

    last_successful_scrape = session.scalar(
        select(func.max(ScrapeRun.finished_at)).where(ScrapeRun.status == RunStatus.success)
    )

    # Latest run by start time drives the health badge.
    latest_run = session.scalar(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(1))
    latest_run_status = latest_run.status.value if latest_run else None

    if latest_run is None:
        health = "unknown"
    elif latest_run.status in (RunStatus.success, RunStatus.partial):
        # partial = the cycle completed and refreshed data, just skipped some projects
        # (a normal, operational degraded state) — green, not false-green.
        health = "green"
    elif latest_run.status in (RunStatus.failed, RunStatus.blocked):
        health = "red"
    else:  # running — in progress, not yet known
        health = "unknown"

    return HomeOverview(
        found_today=found_today or 0,
        qualified_today=qualified_today or 0,
        total_projects=total_projects or 0,
        total_clients=total_clients or 0,
        last_successful_scrape=last_successful_scrape,
        latest_run_status=latest_run_status,
        health=health,
        # Feature 3 — intentional idle surfaced distinctly from a fault (constitution VI).
        paused=SettingsStore(session).get_bool("watcher_paused"),
    )
