"""Settings router — read/tune the worker's editable settings (T025).

GET returns the 8 editable tunables (registry order). PUT validates a partial update against
the registry and persists it all-or-nothing; the worker picks up changes on its next cycle.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...config.settings_store import SettingsStore, _serialize
from ...db.models import Setting
from ..deps import get_db
from ..schemas import SettingItem, SettingsResponse
from ..settings_spec import EDITABLE_BY_KEY, EDITABLE_SETTINGS, SettingsValidationError, validate_updates

router = APIRouter(tags=["settings"])


def _build_response(store: SettingsStore) -> SettingsResponse:
    """Project the registry over the current store values (registry display order)."""
    items: list[SettingItem] = []
    for spec in EDITABLE_SETTINGS:
        raw = store.get(spec.key)
        value = int(raw) if spec.type == "int" else float(raw)
        items.append(
            SettingItem(key=spec.key, value=value, type=spec.type, min=spec.min, max=spec.max, label=spec.label)
        )
    return SettingsResponse(items=items)


@router.get("/api/settings", response_model=SettingsResponse)
def get_settings(session: Annotated[Session, Depends(get_db)]) -> SettingsResponse:
    """Return the editable settings with their current values."""
    store = SettingsStore(session)
    store.reload()
    return _build_response(store)


@router.put("/api/settings", response_model=SettingsResponse)
def put_settings(body: Annotated[dict, Body(...)], session: Annotated[Session, Depends(get_db)]):
    """Validate and persist a partial settings update (all-or-nothing)."""
    store = SettingsStore(session)
    store.reload()
    current = {spec.key: store.get(spec.key) for spec in EDITABLE_SETTINGS}

    try:
        coerced = validate_updates(body, current)
    except SettingsValidationError as e:
        return JSONResponse(
            status_code=422,
            content={"detail": "Validation failed", "errors": [{"key": k, "message": m} for k, m in e.errors]},
        )

    for key, value in coerced.items():
        vtype = EDITABLE_BY_KEY[key].type
        row = session.get(Setting, key)
        if row is not None:
            row.value = _serialize(value, vtype)
            row.value_type = vtype
        else:
            session.add(Setting(key=key, value=_serialize(value, vtype), value_type=vtype))
    session.commit()

    fresh = SettingsStore(session)
    fresh.reload()
    return _build_response(fresh)
