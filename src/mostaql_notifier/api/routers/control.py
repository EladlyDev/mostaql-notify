"""Watcher control endpoints (Feature 3, US4).

Mirrors the Telegram ``/pause`` · ``/resume`` commands: flips the ``watcher_paused`` settings flag
that the worker reads at the top of each poll cycle (it skips quietly when true — FR-028). Both
mutations are idempotent (setting the flag to its current value is harmless). Auth is applied at
include time; this writes only the additive ``watcher_paused`` settings row — never mostaql.com.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...config.settings_store import SettingsStore, _serialize
from ...db.models import Setting
from .. import schemas
from ..deps import get_db

router = APIRouter(tags=["control"])

_PAUSED_KEY = "watcher_paused"


def _read_paused(session: Session) -> bool:
    """Re-read the flag through a fresh store so a just-committed change is reflected."""
    return SettingsStore(session).get_bool(_PAUSED_KEY)


def _set_paused(session: Session, value: bool) -> None:
    """Persist the ``watcher_paused`` flag (same settings-row mechanism as routers/settings.py)."""
    row = session.get(Setting, _PAUSED_KEY)
    if row is not None:
        row.value = _serialize(value, "bool")
        row.value_type = "bool"
    else:
        session.add(Setting(key=_PAUSED_KEY, value=_serialize(value, "bool"), value_type="bool"))
    session.commit()


@router.get("/api/control", response_model=schemas.ControlState)
def get_control(session: Annotated[Session, Depends(get_db)]) -> schemas.ControlState:
    """Current control state (paused?)."""
    return schemas.ControlState(paused=_read_paused(session))


@router.post("/api/control/pause", response_model=schemas.ControlState)
def pause(session: Annotated[Session, Depends(get_db)]) -> schemas.ControlState:
    """Pause the watcher's polling (idempotent)."""
    _set_paused(session, True)
    return schemas.ControlState(paused=_read_paused(session))


@router.post("/api/control/resume", response_model=schemas.ControlState)
def resume(session: Annotated[Session, Depends(get_db)]) -> schemas.ControlState:
    """Resume the watcher's polling (idempotent)."""
    _set_paused(session, False)
    return schemas.ControlState(paused=_read_paused(session))
