"""Kanban board endpoints (Feature 3, US3).

The pipeline board projects the **engaged, non-hidden** personal records into status columns in the
configured order (including empty columns), with a trailing fallback column per status key that was
removed from config so a stale record is never dropped (constitution IV). Moves go through
``personal.service.move`` (applied-once + last-write-wins); no rule is reimplemented here. Auth is
applied at include time; no route writes to mostaql.com.
"""
from __future__ import annotations

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ...db.models import PersonalRecord, Project
from ...personal import service, statuses
from ...personal.service import PersonalValidationError
from .. import schemas
from ..deps import get_db

router = APIRouter(tags=["board"])


def _f(x: object | None) -> float | None:
    """Coerce a Decimal/Numeric (or None) to float|None — never to 0."""
    return float(x) if x is not None else None  # type: ignore[arg-type]


def _to_card(rec: PersonalRecord) -> schemas.BoardCard:
    """Build a board card from a record + its (eager-loaded) project/client facts."""
    p = rec.project
    client = p.client if p is not None else None
    return schemas.BoardCard(
        project_id=rec.project_id,
        title=p.title if p is not None else None,
        url=p.url if p is not None else None,
        client_hiring_rate=client.hiring_rate if client is not None else None,
        budget_min=_f(p.budget_min) if p is not None else None,
        budget_max=_f(p.budget_max) if p is not None else None,
        currency=p.currency if p is not None else None,
        tier=p.tier if p is not None else None,
        tier_label=f"Tier {p.tier}" if (p is not None and p.tier) else None,
        bids_count=p.bids_count if p is not None else None,
        posted_at=p.posted_at if p is not None else None,
        tags=list(rec.tags or []),
        status=rec.status,
        board_position=rec.board_position,
    )


def _validation_response(exc: PersonalValidationError) -> JSONResponse:
    body = schemas.ValidationErrorBody(
        detail="Validation failed",
        errors=[schemas.FieldError(key=exc.key, message=exc.message)],
    )
    return JSONResponse(status_code=422, content=body.model_dump())


@router.get("/api/board", response_model=schemas.BoardResponse)
def get_board(session: Annotated[Session, Depends(get_db)]) -> schemas.BoardResponse:
    """The pipeline board: engaged, non-hidden projects grouped by status (research §8)."""
    default = statuses.default_status(session)
    # Engaged = (favorite OR status != default) AND NOT hidden — eager-load project + client so
    # each card's facts come from the one query (no N+1).
    stmt = (
        select(PersonalRecord)
        .options(joinedload(PersonalRecord.project).joinedload(Project.client))
        .where(
            PersonalRecord.hidden.is_(False),
            sa.or_(PersonalRecord.favorite.is_(True), PersonalRecord.status != default),
        )
        .order_by(PersonalRecord.board_position.asc())
    )
    records = session.scalars(stmt).unique().all()

    by_status: dict[str, list[PersonalRecord]] = {}
    for rec in records:
        by_status.setdefault(rec.status, []).append(rec)

    def _cards(items: list[PersonalRecord]) -> list[schemas.BoardCard]:
        return [_to_card(r) for r in sorted(items, key=lambda r: r.board_position)]

    configured = statuses.list_statuses(session)
    valid = {s["key"] for s in configured}
    columns: list[schemas.BoardColumn] = [
        schemas.BoardColumn(key=s["key"], label=s["label"], cards=_cards(by_status.get(s["key"], [])))
        for s in configured
    ]
    # Trailing fallback column(s): any engaged record whose status key left the config — never dropped.
    for key in sorted(st for st in by_status if st not in valid):
        columns.append(
            schemas.BoardColumn(
                key=key, label=statuses.label_for(session, key), cards=_cards(by_status[key])
            )
        )

    return schemas.BoardResponse(columns=columns)


@router.post("/api/board/move", response_model=schemas.BoardCard)
def move_card(
    body: schemas.BoardMoveRequest, session: Annotated[Session, Depends(get_db)]
):
    """Move/reorder a card (last-write-wins; →applied stamps the applied date via the service)."""
    if session.get(Project, body.project_id) is None:
        raise HTTPException(404, "No such project")
    try:
        rec = service.move(session, body.project_id, body.to_status, body.position)
    except PersonalValidationError as exc:
        return _validation_response(exc)
    session.commit()
    return _to_card(rec)
