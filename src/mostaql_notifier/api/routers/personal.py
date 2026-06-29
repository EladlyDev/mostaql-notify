"""Personal record endpoints (Feature 3, US1).

The owner's CRM layer for one project: get (returns defaults if untouched), partial create-or-update
(lazily creates the row on first touch), and a one-click favorite toggle. All mutations route through
``personal.service`` — the rules (applied-once, status_changed_at, won_amount ≥ 0, status validation)
live there, never here. Auth is applied at include time (constitution IX); no route writes to
mostaql.com (constitution VIII).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...db.models import PersonalRecord, Project
from ...personal import service, statuses
from ...personal.service import PersonalValidationError
from .. import schemas
from ..deps import get_db

router = APIRouter(tags=["personal"])


def _f(x: object | None) -> float | None:
    """Coerce a Decimal/Numeric (or None) to float|None — never to 0."""
    return float(x) if x is not None else None  # type: ignore[arg-type]


def to_personal_dto(session: Session, rec: PersonalRecord) -> schemas.PersonalRecord:
    """Project a stored record to its response DTO; ``status_label`` resolved from config."""
    return schemas.PersonalRecord(
        project_id=rec.project_id,
        favorite=rec.favorite,
        status=rec.status,
        status_label=statuses.label_for(session, rec.status),
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


def _validation_response(exc: PersonalValidationError) -> JSONResponse:
    """Map a service field-error to the contract's 422 ``ValidationErrorBody``."""
    body = schemas.ValidationErrorBody(
        detail="Validation failed",
        errors=[schemas.FieldError(key=exc.key, message=exc.message)],
    )
    return JSONResponse(status_code=422, content=body.model_dump())


def _require_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "No such project")
    return project


@router.get("/api/projects/{project_id}/personal", response_model=schemas.PersonalRecord)
def get_personal(
    project_id: int, session: Annotated[Session, Depends(get_db)]
) -> schemas.PersonalRecord:
    """Return the personal record, or read-only defaults (no row created) if untouched."""
    _require_project(session, project_id)
    rec = session.get(PersonalRecord, project_id)
    if rec is None:
        default = statuses.default_status(session)
        return schemas.PersonalRecord(
            project_id=project_id,
            favorite=False,
            status=default,
            status_label=statuses.label_for(session, default),
            tags=[],
            notes="",
            board_position=0.0,
            hidden=False,
        )
    return to_personal_dto(session, rec)


@router.patch("/api/projects/{project_id}/personal", response_model=schemas.PersonalRecord)
def patch_personal(
    project_id: int,
    body: schemas.PersonalUpdate,
    session: Annotated[Session, Depends(get_db)],
):
    """Create-or-update (partial). ``exclude_unset`` keeps an omitted field distinct from null."""
    _require_project(session, project_id)
    try:
        rec = service.apply_update(session, project_id, body.model_dump(exclude_unset=True))
    except PersonalValidationError as exc:
        return _validation_response(exc)
    session.commit()
    return to_personal_dto(session, rec)


@router.post("/api/projects/{project_id}/personal/favorite", response_model=schemas.PersonalRecord)
def toggle_favorite(
    project_id: int, session: Annotated[Session, Depends(get_db)]
) -> schemas.PersonalRecord:
    """Flip the favorite flag (one-click feed action + Telegram parity)."""
    _require_project(session, project_id)
    rec = service.toggle_favorite(session, project_id)
    session.commit()
    return to_personal_dto(session, rec)


@router.post(
    "/api/projects/{project_id}/personal/revert-auto-status",
    response_model=schemas.PersonalRecord,
)
def revert_auto_status(
    project_id: int, session: Annotated[Session, Depends(get_db)]
):
    """Undo the optional auto personal-status transition (Feature 4) — restore the prior status and
    clear the auto-trail fields. Owner data (favorite/tags/notes/applied/outcome/files) is never
    touched; 422 when there is no recorded auto-change to revert."""
    _require_project(session, project_id)
    try:
        rec = service.revert_auto_status(session, project_id)
    except PersonalValidationError as exc:
        return _validation_response(exc)
    session.commit()
    return to_personal_dto(session, rec)


@router.get("/api/statuses", response_model=list[schemas.PersonalStatusOption])
def list_status_options(
    session: Annotated[Session, Depends(get_db)]
) -> list[schemas.PersonalStatusOption]:
    """The configured pipeline stages (slug + Arabic label), in order — feeds the feed/detail
    status pickers so options stay config-driven (constitution III)."""
    return [
        schemas.PersonalStatusOption(key=s["key"], label=s["label"])
        for s in statuses.list_statuses(session)
    ]
