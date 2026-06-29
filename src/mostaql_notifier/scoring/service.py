"""Surface-agnostic scoring service (Feature 4) — see research.md R7 + contracts.

The single entry point the API, worker re-check loop and bot all call, so "one score, one breakdown,
consistent everywhere" lives in one place (mirrors ``personal/service.py``). Surface-agnostic: the
caller owns the transaction (these functions ``flush`` but never ``commit``). ``settings`` is a
``SettingsStore``; ``now_utc`` is injected aware-UTC.

Implements T014 (``score_project`` / ``rescore_all`` / ``get_breakdown``) and T049 (``top_open``).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager, selectinload

from ..db.models import EvalStatus, Project, ProjectScore, ProjectStatus
from . import model


def score_project(session: Session, project, *, settings, now_utc) -> ProjectScore:
    """Compute the score for one already-loaded qualified ``project`` and upsert its ``ProjectScore``.

    Returns the persisted ``ProjectScore``. Uses ``project.snapshots`` (eager-loaded by the caller for
    a batch) for velocity. Touches only ``score``/``breakdown``/``computed_at`` — ``outcome``,
    ``tracking_active`` and ``last_checked_at`` are owned by the re-check loop. ``flush`` only.
    """
    result = model.score_project(project, project.client, settings=settings, now_utc=now_utc)

    row = session.get(ProjectScore, project.id)
    if row is None:
        # Rely on the model column defaults for outcome (open) / tracking_active (True).
        row = ProjectScore(project_id=project.id)
        session.add(row)
    row.score = result.score
    row.breakdown = result.breakdown
    row.computed_at = now_utc

    session.flush()
    return row


def rescore_all(session: Session, *, settings, now_utc) -> int:
    """(Re)score every ``eval_status == qualified`` project from stored data (pure, no network).

    Backfill (startup) + settings-triggered re-score. Non-qualified projects are skipped (left with no
    score). Eager-loads ``client`` + ``snapshots`` to avoid N+1. Returns the number scored.
    """
    stmt = (
        select(Project)
        .where(Project.eval_status == EvalStatus.qualified)
        .options(selectinload(Project.client), selectinload(Project.snapshots))
    )
    projects = session.execute(stmt).scalars().all()
    for project in projects:
        score_project(session, project, settings=settings, now_utc=now_utc)
    return len(projects)


def get_breakdown(session: Session, project_id: int) -> dict | None:
    """Return the stored ``ScoreBreakdown``-shaped dict for ``project_id`` (``None`` if never scored).

    Read-only; used by the API detail view and the bot "Why?" reply.
    """
    row = session.get(ProjectScore, project_id)
    if row is None or row.score is None:
        return None
    return row.breakdown


def top_open(session: Session, n: int) -> list:
    """Return up to ``n`` qualified + open + actively-tracked projects ordered by score desc.

    Read-only; used by the bot ``/top`` command. Each returned project's ``score_row`` is eager-loaded.
    """
    stmt = (
        select(Project)
        .join(Project.score_row)
        .where(
            Project.eval_status == EvalStatus.qualified,
            Project.site_status == ProjectStatus.open,
            ProjectScore.tracking_active.is_(True),
        )
        .order_by(ProjectScore.score.desc())
        .limit(n)
        .options(contains_eager(Project.score_row))
    )
    return list(session.execute(stmt).scalars().all())
