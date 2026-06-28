"""Hardening tests: the board-move and personal endpoints must reject non-finite floats.

A NaN / ±Infinity ``position`` (or ``won_amount``) would be stored and then serialized by FastAPI
as the non-standard JSON tokens ``Infinity`` / ``NaN``, which a browser's ``JSON.parse`` rejects —
a single poisoned card would break ``GET /api/board`` for the whole dashboard. The request schemas
set ``allow_inf_nan=False`` so such a body is a clean 422 instead. Some JSON parsers (incl. Python's
``json.loads`` used by Starlette) accept these literal tokens, so we send them as a raw body.
"""
from __future__ import annotations

import pytest

from tests.api.conftest import make_project

_JSON = {"Content-Type": "application/json"}


def _project(api_env) -> int:
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        return p.id


@pytest.mark.parametrize("token", ["Infinity", "-Infinity", "NaN"])
def test_board_move_rejects_non_finite_position(api_env, token):
    pid = _project(api_env)
    client = api_env.client()
    body = (
        '{"project_id": ' + str(pid)
        + ', "to_status": "interested", "position": ' + token + "}"
    )
    resp = client.post("/api/board/move", content=body, headers=_JSON)
    assert resp.status_code == 422, resp.text


def test_board_move_accepts_finite_position(api_env):
    pid = _project(api_env)
    client = api_env.client()
    resp = client.post(
        "/api/board/move",
        json={"project_id": pid, "to_status": "interested", "position": 3.5},
    )
    assert resp.status_code == 200
    assert resp.json()["board_position"] == 3.5


@pytest.mark.parametrize("token", ["Infinity", "-Infinity", "NaN"])
def test_personal_won_amount_rejects_non_finite(api_env, token):
    pid = _project(api_env)
    client = api_env.client()
    body = '{"won_amount": ' + token + "}"
    resp = client.patch(f"/api/projects/{pid}/personal", content=body, headers=_JSON)
    assert resp.status_code == 422, resp.text


def test_personal_won_amount_accepts_finite(api_env):
    pid = _project(api_env)
    client = api_env.client()
    resp = client.patch(f"/api/projects/{pid}/personal", json={"won_amount": 1250.75})
    assert resp.status_code == 200
    assert resp.json()["won_amount"] == 1250.75
