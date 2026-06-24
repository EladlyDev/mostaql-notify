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

from ...db.models import Client, EvalStatus, Project
from ..deps import get_db
from ..schemas import ClientPanel, ProjectDetail, ProjectListItem, ProjectListResponse

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


def to_list_item(p: Project) -> ProjectListItem:
    """Build a list-item DTO explicitly from a Project (and its optional client)."""
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
    )


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


# sort key → column (hiring_rate lives on the joined Client).
_SORT_COLUMNS = {
    "posted_at": Project.posted_at,
    "budget": Project.budget_max,
    "bids_count": Project.bids_count,
    "hiring_rate": Client.hiring_rate,
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
    site_status: Annotated[Literal["open", "closed", "unknown"] | None, Query()] = None,
    qualified_only: Annotated[bool, Query()] = False,
    q: Annotated[str | None, Query()] = None,
    sort: Annotated[Literal["posted_at", "budget", "bids_count", "hiring_rate"], Query()] = "posted_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ProjectListResponse:
    """List projects with optional filters (AND-combined), sorting and pagination.

    Outer-joins Client so client-less projects still appear (client fields null). Enum-like
    params (tier, site_status, sort, order) are constrained so invalid values yield 422.
    """
    # LEFT OUTER JOIN so projects without a client are retained; contains_eager populates the
    # relationship from the same join (avoids an N+1 lazy load per row).
    stmt = select(Project).outerjoin(Project.client).options(contains_eager(Project.client))

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
        items=[to_list_item(p) for p in projects],
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

    # Sibling projects: same client, excluding self (none if client-less).
    same_client: list[ProjectListItem] = []
    if project.client_id is not None:
        siblings = db.scalars(
            select(Project).where(
                Project.client_id == project.client_id,
                Project.id != project.id,
            )
        ).all()
        same_client = [to_list_item(p) for p in siblings]

    base = to_list_item(project)
    return ProjectDetail(
        **base.model_dump(),
        description=project.description,
        category=project.category,
        skills=project.skills,
        scraped_at=project.scraped_at,
        client=to_client_panel(project.client) if project.client else None,
        same_client_projects=same_client,
    )
