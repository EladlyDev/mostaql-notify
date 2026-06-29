"""Projects API — list (filter/sort/paginate) and detail (with client + sibling projects).

Read-only projection over Feature 1's ORM. Numerics are passed through as float|None so the
frontend can distinguish "not calculated" (null) from a real 0.0. Auth is applied at include time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, nulls_last, select
from sqlalchemy.orm import Session, contains_eager

from ...config.settings_store import SettingsStore
from ...db.models import Client, EvalStatus, PersonalRecord, Project, ProjectScore
from ...personal import statuses
from ...scoring.freshness import freshness
from ..deps import get_db
from ..schemas import (
    ClientPanel,
    Lifecycle,
    ProjectDetail,
    ProjectListItem,
    ProjectListResponse,
    ScoreBreakdown,
    Snapshot,
    StatusEvent,
)
from ..schemas import (
    PersonalRecord as PersonalRecordDTO,
)

router = APIRouter(tags=["projects"])


def _like_escape(term: str) -> str:
    """Escape LIKE/ILIKE metacharacters so a search term matches literally.

    Without this, a query of ``%`` or ``_`` would match everything / any char, and a literal
    ``%``/``_`` in project text could never be searched for. Backslash is the escape char.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _f(x: object | None) -> float | None:
    """Coerce a Decimal/Numeric (or None) to float|None — never to 0."""
    return float(x) if x is not None else None  # type: ignore[arg-type]


def to_list_item(
    p: Project,
    status_labels: dict[str, str] | None = None,
    default_status: str = "new",
    *,
    settings: SettingsStore | None = None,
    now: datetime | None = None,
) -> ProjectListItem:
    """Build a list-item DTO explicitly from a Project (and its optional client + personal record).

    The personal projection is defaulted when no record exists (favorite=False, status=default,
    tags=[], hidden=False). ``status_labels`` (slug→Arabic label) is passed in so the label is
    resolved from config without a per-row query; an unmapped slug falls back to the slug itself.

    Feature 4 — the opportunity ``score`` is the latest stored value (null when never scored), and
    ``freshness`` is derived on read (green/yellow/red) ONLY for a scored project; an unscored /
    non-qualified project (no ``score_row``) reads null for both. ``settings``/``now`` feed the
    pure freshness deriver (built once per request by the caller).
    """
    pr = p.personal  # loaded via contains_eager in the list query; lazy for the few detail siblings
    p_status = pr.status if pr is not None else default_status
    labels = status_labels or {}
    score_row = p.score_row
    score = score_row.score if score_row is not None else None
    fresh: str | None = None
    if score_row is not None and settings is not None and now is not None:
        # latest_snapshot=None is correct: the re-check loop mirrors the latest observation onto
        # the project's own site_status / bids_count, so the project row is the live source.
        fresh = freshness(p, None, settings=settings, now_utc=now)
    return ProjectListItem(
        id=p.id,
        title=p.title,
        url=p.url,
        client_name=p.client.name if p.client else None,
        client_hiring_rate=p.client.hiring_rate if p.client else None,
        budget_min=_f(p.budget_min),
        budget_max=_f(p.budget_max),
        currency=p.currency,
        tier=p.tier,
        tier_label=f"Tier {p.tier}" if p.tier else None,
        bids_count=p.bids_count,
        posted_at=p.posted_at,
        site_status=p.site_status.value,
        eval_status=p.eval_status.value,
        qualified=(p.eval_status == EvalStatus.qualified),
        favorite=pr.favorite if pr is not None else False,
        personal_status=p_status,
        personal_status_label=labels.get(p_status, p_status),
        tags=list(pr.tags) if pr is not None and pr.tags else [],
        hidden=pr.hidden if pr is not None else False,
        score=score,
        freshness=fresh,
    )


def to_personal_dto(rec: PersonalRecord | None, project_id: int, status_labels: dict[str, str],
                    default_status: str) -> PersonalRecordDTO:
    """Build the embedded personal DTO from a record (or defaults when none exists yet)."""
    if rec is None:
        return PersonalRecordDTO(
            project_id=project_id,
            favorite=False,
            status=default_status,
            status_label=status_labels.get(default_status, default_status),
            tags=[],
            notes="",
            board_position=0.0,
            hidden=False,
        )
    return PersonalRecordDTO(
        project_id=rec.project_id,
        favorite=rec.favorite,
        status=rec.status,
        status_label=status_labels.get(rec.status, rec.status),
        tags=list(rec.tags or []),
        applied_at=rec.applied_at,
        won_amount=_f(rec.won_amount),
        lost_reason=rec.lost_reason,
        notes=rec.notes,
        board_position=rec.board_position,
        hidden=rec.hidden,
        status_changed_at=rec.status_changed_at,
        reminder_at=rec.reminder_at,
        auto_status_from=rec.auto_status_from,
        auto_status_at=rec.auto_status_at,
    )


def _status_label_map(session: Session) -> dict[str, str]:
    return {s["key"]: s["label"] for s in statuses.list_statuses(session)}


def to_client_panel(c: Client) -> ClientPanel:
    """Build the client side-panel DTO; hiring_rate/total_spent stay None when None."""
    return ClientPanel(
        id=c.id,
        name=c.name,
        hiring_rate=c.hiring_rate,
        projects_posted=c.projects_posted,
        projects_open=c.projects_open,
        hires_count=c.hires_count,
        avg_rating=c.avg_rating,
        reviews_count=c.reviews_count,
        total_spent=_f(c.total_spent),
        country=c.country,
        member_since=c.member_since,
        verified=c.verified,
    )


# sort key → column (hiring_rate lives on the joined Client; score on the joined ProjectScore).
_SORT_COLUMNS = {
    "posted_at": Project.posted_at,
    "budget": Project.budget_max,
    "bids_count": Project.bids_count,
    "hiring_rate": Client.hiring_rate,
    "score": ProjectScore.score,
}


@router.get("/api/projects", response_model=ProjectListResponse)
def list_projects(
    db: Annotated[Session, Depends(get_db)],
    tier: Annotated[int | None, Query(ge=1, le=2)] = None,
    budget_min: Annotated[float | None, Query()] = None,
    budget_max: Annotated[float | None, Query()] = None,
    min_hiring_rate: Annotated[float | None, Query(ge=0, le=100)] = None,
    bids_min: Annotated[int | None, Query(ge=0)] = None,
    bids_max: Annotated[int | None, Query(ge=0)] = None,
    posted_within_hours: Annotated[int | None, Query(ge=1)] = None,
    site_status: Annotated[Literal["open", "closed", "awarded", "unknown"] | None, Query()] = None,
    qualified_only: Annotated[bool, Query()] = False,
    score_min: Annotated[float | None, Query(ge=0, le=100)] = None,
    score_max: Annotated[float | None, Query(ge=0, le=100)] = None,
    q: Annotated[str | None, Query()] = None,
    personal_status: Annotated[str | None, Query()] = None,
    favorites_only: Annotated[bool, Query()] = False,
    include_hidden: Annotated[bool, Query()] = False,
    sort: Annotated[
        Literal["posted_at", "budget", "bids_count", "hiring_rate", "score"], Query()
    ] = "posted_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ProjectListResponse:
    """List projects with optional filters (AND-combined), sorting and pagination.

    Outer-joins Client and the personal record so client-less / record-less projects still appear
    (those fields defaulted). Feature 3 adds the personal projection + ``personal_status`` /
    ``favorites_only`` / ``include_hidden`` filters; hidden projects are excluded unless
    ``include_hidden``. Enum-like params (tier, site_status, sort, order) are constrained → 422.
    """
    default_status = statuses.default_status(db)
    status_labels = _status_label_map(db)
    settings = SettingsStore(db)
    now = datetime.now(timezone.utc)
    # LEFT OUTER JOIN client + personal + score so record-less / unscored projects are retained;
    # contains_eager populates all three relationships from the same joins (avoids N+1 lazy loads).
    stmt = (
        select(Project)
        .outerjoin(Project.client)
        .outerjoin(Project.personal)
        .outerjoin(Project.score_row)
        .options(
            contains_eager(Project.client),
            contains_eager(Project.personal),
            contains_eager(Project.score_row),
        )
    )

    if tier is not None:
        stmt = stmt.where(Project.tier == tier)
    if budget_min is not None:
        stmt = stmt.where(Project.budget_max >= budget_min)
    if budget_max is not None:
        stmt = stmt.where(Project.budget_max <= budget_max)
    if min_hiring_rate is not None:
        # Comparison naturally excludes NULL hiring rates (required behaviour).
        stmt = stmt.where(Client.hiring_rate >= min_hiring_rate)
    if bids_min is not None:
        stmt = stmt.where(Project.bids_count >= bids_min)
    if bids_max is not None:
        stmt = stmt.where(Project.bids_count <= bids_max)
    if posted_within_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=posted_within_hours)
        stmt = stmt.where(Project.posted_at >= cutoff)
    if site_status is not None:
        stmt = stmt.where(Project.site_status == site_status)
    if qualified_only:
        stmt = stmt.where(Project.eval_status == EvalStatus.qualified)
    # Feature 4 — score-range filter. The comparison naturally excludes NULL scores, so a project
    # that was never scored (no score_row / null score) is dropped from the match whenever either
    # bound is set, and only reappears once the score filter is absent (constitution VII, FR-011).
    if score_min is not None:
        stmt = stmt.where(ProjectScore.score >= score_min)
    if score_max is not None:
        stmt = stmt.where(ProjectScore.score <= score_max)
    # Personal filters (Feature 3). A missing personal record counts as the default status and
    # not-favorite / not-hidden, so coalesce/NULL handling keeps record-less projects visible.
    if personal_status is not None:
        stmt = stmt.where(
            func.coalesce(PersonalRecord.status, default_status) == personal_status
        )
    if favorites_only:
        stmt = stmt.where(PersonalRecord.favorite.is_(True))
    if not include_hidden:
        stmt = stmt.where(
            (PersonalRecord.hidden.is_(None)) | (PersonalRecord.hidden.is_(False))
        )
    if q:
        pattern = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            Project.title.ilike(pattern, escape="\\")
            | Project.description.ilike(pattern, escape="\\")
            | sa.cast(Project.skills, sa.String).ilike(pattern, escape="\\")
        )

    # total = count of the filtered set, before pagination.
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    # Sort: validated key/order, NULLs always last.
    column = _SORT_COLUMNS.get(sort, Project.posted_at)
    direction = column.asc() if order == "asc" else column.desc()
    stmt = stmt.order_by(nulls_last(direction))

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    projects = db.scalars(stmt).all()

    return ProjectListResponse(
        items=[
            to_list_item(p, status_labels, default_status, settings=settings, now=now)
            for p in projects
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/api/projects/{id}", response_model=ProjectDetail)
def get_project(id: int, db: Annotated[Session, Depends(get_db)]) -> ProjectDetail:
    """Project detail with client side-panel and other projects from the same client."""
    project = db.get(Project, id)
    if project is None:
        raise HTTPException(404, "No such project")

    default_status = statuses.default_status(db)
    status_labels = _status_label_map(db)
    settings = SettingsStore(db)
    now = datetime.now(timezone.utc)

    # Sibling projects: same client, excluding self (none if client-less).
    same_client: list[ProjectListItem] = []
    if project.client_id is not None:
        siblings = db.scalars(
            select(Project).where(
                Project.client_id == project.client_id,
                Project.id != project.id,
            )
        ).all()
        same_client = [
            to_list_item(p, status_labels, default_status, settings=settings, now=now)
            for p in siblings
        ]

    base = to_list_item(project, status_labels, default_status, settings=settings, now=now)
    # Feature 4 — outcome + the stored per-component breakdown behind ``score`` (null when never
    # scored). The stored dict is a superset; Pydantic ignores its extra ``weights``/``inputs`` keys.
    score_row = project.score_row
    outcome = score_row.outcome.value if score_row is not None else None
    score_breakdown = (
        ScoreBreakdown.model_validate(score_row.breakdown)
        if (score_row is not None and score_row.score is not None)
        else None
    )
    return ProjectDetail(
        **base.model_dump(),
        description=project.description,
        category=project.category,
        skills=project.skills,
        scraped_at=project.scraped_at,
        client=to_client_panel(project.client) if project.client else None,
        same_client_projects=same_client,
        personal=to_personal_dto(project.personal, project.id, status_labels, default_status),
        outcome=outcome,
        score_breakdown=score_breakdown,
    )


@router.get("/api/projects/{id}/lifecycle", response_model=Lifecycle)
def get_project_lifecycle(id: int, db: Annotated[Session, Depends(get_db)]) -> Lifecycle:
    """The project's lifecycle — its append-only snapshot trajectory, the deduped status timeline
    derived from it, and the fail-closed final outcome (Feature 4).

    ``snapshots`` powers the inline bid-over-time chart (time-ordered, oldest first via the
    relationship ``order_by``). ``status_timeline`` emits one ``StatusEvent`` per transition — a row
    only when ``site_status`` differs from the previous snapshot's, with the first snapshot always
    seeding the timeline. ``outcome`` is the stored disposition (null when never scored/tracked). A
    project with no snapshots yet returns empty lists.
    """
    project = db.get(Project, id)
    if project is None:
        raise HTTPException(404, "No such project")

    snaps = project.snapshots  # ordered by captured_at (ascending) via the relationship.
    snapshots = [
        Snapshot(
            captured_at=s.captured_at,
            bids_count=s.bids_count,
            site_status=s.site_status.value,
            score=s.score,
        )
        for s in snaps
    ]

    status_timeline: list[StatusEvent] = []
    prev_status: str | None = None
    for s in snaps:
        status = s.site_status.value
        if status != prev_status:  # the first snapshot (prev=None) always starts the timeline.
            status_timeline.append(StatusEvent(at=s.captured_at, status=status))
            prev_status = status

    outcome = project.score_row.outcome.value if project.score_row is not None else None
    return Lifecycle(outcome=outcome, snapshots=snapshots, status_timeline=status_timeline)
