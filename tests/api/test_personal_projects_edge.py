"""Edge-case coverage for the personal / projects-detail / statuses / control endpoints (Feature 3).

Targets gaps the happy-path suites miss: ``GET /api/statuses`` (config-driven pickers), the
project-detail *embedded personal* projection when a record exists, the control insert branch when
the ``watcher_paused`` settings row is absent, and the per-field PATCH rules (applied_at override,
won_amount=0, whitespace lost_reason, atomicity of a rejected create). Mirrors the fixtures/factories
in ``tests/api/conftest.py``; asserts correct behaviour throughout.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from mostaql_notifier.db.models import PersonalRecord, Setting
from tests.api.conftest import make_personal_record, make_project

# The 7 configured pipeline stages, in order (settings seed `personal_statuses`).
_EXPECTED_STAGES = [
    {"key": "new", "label": "جديد"},
    {"key": "interested", "label": "مهتم"},
    {"key": "applied", "label": "تقدّمت"},
    {"key": "in_discussion", "label": "قيد النقاش"},
    {"key": "won", "label": "ربح"},
    {"key": "lost", "label": "خسارة"},
    {"key": "ignored", "label": "تجاهل"},
]


def _parse(dt_str: str) -> datetime:
    """Parse an API-serialized ISO timestamp into an aware datetime (handles a trailing ``Z``)."""
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def _new_project_id(api_env, **over) -> int:
    with api_env.session() as s:
        p = make_project(s, **over)
        s.commit()
        return p.id


# ---------------------------------------------------------------------------
# GET /api/statuses  (personal.py L121)
# ---------------------------------------------------------------------------


def test_statuses_lists_the_configured_stages_in_order(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.get("/api/statuses")
    assert resp.status_code == 200
    assert resp.json() == _EXPECTED_STAGES  # full {key,label} list, in board/picker order


def test_statuses_requires_auth_when_enabled(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    assert client.get("/api/statuses").status_code == 401


# ---------------------------------------------------------------------------
# GET /api/projects/{id} detail — embedded personal block (projects.py L98, branch 87->98)
# ---------------------------------------------------------------------------


def test_detail_personal_block_reflects_an_existing_record(api_env):
    applied = datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc)
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_personal_record(
            s,
            project=p,
            favorite=True,
            status="applied",
            tags=["عاجل", "تصميم"],
            won_amount=250,
            applied_at=applied,
        )
        s.commit()
        pid = p.id

    c = api_env.client()
    personal = c.get(f"/api/projects/{pid}").json()["personal"]
    assert personal["project_id"] == pid
    assert personal["favorite"] is True
    assert personal["status"] == "applied"
    assert personal["status_label"] == "تقدّمت"  # resolved from config, not the raw slug
    assert personal["tags"] == ["عاجل", "تصميم"]
    assert personal["won_amount"] == 250.0  # Numeric coerced to float
    assert _parse(personal["applied_at"]) == applied


def test_detail_personal_block_defaults_when_no_record(api_env):
    pid = _new_project_id(api_env, _n=2)
    c = api_env.client()
    personal = c.get(f"/api/projects/{pid}").json()["personal"]
    assert personal["favorite"] is False
    assert personal["status"] == "new"
    assert personal["status_label"] == "جديد"
    assert personal["tags"] == []
    assert personal["notes"] == ""
    assert personal["board_position"] == 0.0
    assert personal["hidden"] is False
    assert personal["won_amount"] is None
    assert personal["applied_at"] is None


# ---------------------------------------------------------------------------
# control.py L37 — the _set_paused INSERT branch (watcher_paused row absent)
# ---------------------------------------------------------------------------


def test_pause_inserts_setting_row_when_absent(api_env):
    # seed_defaults wrote a watcher_paused row; remove it so _set_paused takes the INSERT branch.
    with api_env.session() as s:
        row = s.get(Setting, "watcher_paused")
        assert row is not None  # sanity: it was seeded
        s.delete(row)
        s.commit()
        assert s.get(Setting, "watcher_paused") is None

    client = api_env.client(auth_enabled=False)
    assert client.post("/api/control/pause").json() == {"paused": True}  # INSERT path
    assert client.get("/api/control").json()["paused"] is True  # persisted + re-read
    assert client.post("/api/control/resume").json()["paused"] is False  # now the UPDATE path


# ---------------------------------------------------------------------------
# PATCH /api/projects/{id}/personal — per-field rules
# ---------------------------------------------------------------------------


def test_patch_applied_at_reminder_notes_and_hidden_roundtrip(api_env):
    pid = _new_project_id(api_env, _n=1)
    applied = datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc)
    reminder = datetime(2024, 7, 1, 12, 0, tzinfo=timezone.utc)

    client = api_env.client(auth_enabled=False)
    data = client.patch(
        f"/api/projects/{pid}/personal",
        json={
            "applied_at": applied.isoformat(),
            "reminder_at": reminder.isoformat(),
            "notes": "ملاحظة أولى",
            "hidden": True,
        },
    ).json()
    assert _parse(data["applied_at"]) == applied
    assert _parse(data["reminder_at"]) == reminder
    assert data["notes"] == "ملاحظة أولى"
    assert data["hidden"] is True

    # hidden: True -> False round-trips (False is distinct from omitted).
    back = client.patch(f"/api/projects/{pid}/personal", json={"hidden": False}).json()
    assert back["hidden"] is False


def test_patch_won_amount_zero_is_accepted(api_env):
    pid = _new_project_id(api_env, _n=1)
    client = api_env.client(auth_enabled=False)
    resp = client.patch(f"/api/projects/{pid}/personal", json={"won_amount": 0})
    assert resp.status_code == 200
    assert resp.json()["won_amount"] == 0.0  # a real 0, not null


def test_patch_negative_won_amount_returns_full_422_body(api_env):
    pid = _new_project_id(api_env, _n=1)
    client = api_env.client(auth_enabled=False)
    resp = client.patch(f"/api/projects/{pid}/personal", json={"won_amount": -1})
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "Validation failed"
    assert len(body["errors"]) == 1
    assert body["errors"][0]["key"] == "won_amount"
    assert body["errors"][0]["message"]  # a human-readable message is present


def test_patch_unknown_status_returns_422_and_creates_no_row(api_env):
    pid = _new_project_id(api_env, _n=1)
    client = api_env.client(auth_enabled=False)
    resp = client.patch(f"/api/projects/{pid}/personal", json={"status": "made-up"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "Validation failed"
    assert body["errors"][0]["key"] == "status"
    # Atomicity: the lazy get_or_create flush is discarded because get_db never commits the error path.
    with api_env.session() as s:
        assert s.get(PersonalRecord, pid) is None


def test_explicit_applied_at_overrides_the_auto_stamp_in_same_patch(api_env):
    pid = _new_project_id(api_env, _n=1)
    explicit = datetime(2023, 3, 14, 8, 0, tzinfo=timezone.utc)

    client = api_env.client(auth_enabled=False)
    data = client.patch(
        f"/api/projects/{pid}/personal",
        json={"status": "applied", "applied_at": explicit.isoformat()},
    ).json()
    assert data["status"] == "applied"
    # apply_update sets status (which auto-stamps) before applying applied_at, so the explicit
    # value wins — and it is clearly not "now".
    assert _parse(data["applied_at"]) == explicit


def test_lost_reason_whitespace_trims_to_null(api_env):
    pid = _new_project_id(api_env, _n=1)
    client = api_env.client(auth_enabled=False)

    set_resp = client.patch(f"/api/projects/{pid}/personal", json={"lost_reason": "x"})
    assert set_resp.json()["lost_reason"] == "x"

    cleared = client.patch(f"/api/projects/{pid}/personal", json={"lost_reason": "   "})
    assert cleared.json()["lost_reason"] is None  # trimmed empty -> null


def test_favorite_toggle_twice_returns_to_original_state(api_env):
    # Start from an existing record already favorited; two flips return to the original True.
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_personal_record(s, project=p, favorite=True)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    assert client.post(f"/api/projects/{pid}/personal/favorite").json()["favorite"] is False
    assert client.post(f"/api/projects/{pid}/personal/favorite").json()["favorite"] is True


# ---------------------------------------------------------------------------
# personal_status filter coalesces a record-less project to the default status
# ---------------------------------------------------------------------------


def test_personal_status_filter_coalesces_recordless_to_default(api_env):
    with api_env.session() as s:
        a = make_project(s, _n=1)  # has a record, status applied
        make_personal_record(s, project=a, status="applied")
        b = make_project(s, _n=2)  # no record -> coalesces to default "new"
        s.commit()
        a_id, b_id = a.id, b.id

    c = api_env.client()

    new_ids = {it["id"] for it in c.get("/api/projects", params={"personal_status": "new"}).json()["items"]}
    assert b_id in new_ids and a_id not in new_ids

    applied_ids = {
        it["id"] for it in c.get("/api/projects", params={"personal_status": "applied"}).json()["items"]
    }
    assert a_id in applied_ids and b_id not in applied_ids


# ---------------------------------------------------------------------------
# 404s on a missing project id
# ---------------------------------------------------------------------------


def test_missing_project_id_is_404_across_endpoints(api_env):
    client = api_env.client(auth_enabled=False)
    missing = 987654
    assert client.get(f"/api/projects/{missing}").status_code == 404  # detail
    assert client.get(f"/api/projects/{missing}/personal").status_code == 404
    assert client.patch(f"/api/projects/{missing}/personal", json={"favorite": True}).status_code == 404
    assert client.post(f"/api/projects/{missing}/personal/favorite").status_code == 404


def test_no_records_table_grows_from_pure_reads(api_env):
    """GET detail + GET personal + GET statuses must not lazily create personal rows."""
    pid = _new_project_id(api_env, _n=1)
    client = api_env.client(auth_enabled=False)
    client.get(f"/api/projects/{pid}")
    client.get(f"/api/projects/{pid}/personal")
    client.get("/api/statuses")
    with api_env.session() as s:
        assert (s.scalar(select(func.count()).select_from(PersonalRecord)) or 0) == 0
