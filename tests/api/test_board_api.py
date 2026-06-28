"""T034 — Kanban board API: column order, the engaged predicate, fallback column, moves, auth."""
from __future__ import annotations

from mostaql_notifier.db.models import PersonalRecord
from tests.api.conftest import make_personal_record, make_project

_CONFIGURED_ORDER = ["new", "interested", "applied", "in_discussion", "won", "lost", "ignored"]


def _columns(client):
    return client.get("/api/board").json()["columns"]


def _card_ids(columns, key: str) -> set[int]:
    for col in columns:
        if col["key"] == key:
            return {c["project_id"] for c in col["cards"]}
    return set()


def _all_card_ids(columns) -> set[int]:
    return {c["project_id"] for col in columns for c in col["cards"]}


def test_columns_in_configured_order_including_empty(api_env):
    client = api_env.client(auth_enabled=False)
    columns = _columns(client)
    # All seven configured columns, in order, even though none hold any cards.
    assert [c["key"] for c in columns] == _CONFIGURED_ORDER
    assert all(c["cards"] == [] for c in columns)
    # Labels come from config (Arabic).
    labels = {c["key"]: c["label"] for c in columns}
    assert labels["new"] == "جديد"
    assert labels["applied"] == "تقدّمت"


def test_only_engaged_non_hidden_projects_appear(api_env):
    with api_env.session() as s:
        untouched = make_project(s, _n=1)  # no personal record => not engaged
        hidden = make_project(s, _n=2)
        make_personal_record(s, project=hidden, favorite=True, hidden=True)  # hidden wins
        favorited = make_project(s, _n=3)
        make_personal_record(s, project=favorited, favorite=True, status="new", board_position=1.0)
        moved = make_project(s, _n=4)
        make_personal_record(s, project=moved, status="interested", board_position=2.0)
        s.commit()
        untouched_id, hidden_id = untouched.id, hidden.id
        favorited_id, moved_id = favorited.id, moved.id

    client = api_env.client(auth_enabled=False)
    columns = _columns(client)
    shown = _all_card_ids(columns)
    assert favorited_id in shown  # engaged via favorite (status still 'new')
    assert moved_id in shown  # engaged via off-default status
    assert untouched_id not in shown  # no record => default 'new', not favorite
    assert hidden_id not in shown  # hidden, even though favorited
    # Placed in the right columns.
    assert favorited_id in _card_ids(columns, "new")
    assert moved_id in _card_ids(columns, "interested")


def test_cards_within_column_ordered_by_board_position(api_env):
    with api_env.session() as s:
        p_lo = make_project(s, _n=1)
        make_personal_record(s, project=p_lo, favorite=True, status="new", board_position=2.0)
        p_hi = make_project(s, _n=2)
        make_personal_record(s, project=p_hi, favorite=True, status="new", board_position=1.0)
        s.commit()
        lo_id, hi_id = p_lo.id, p_hi.id

    client = api_env.client(auth_enabled=False)
    columns = _columns(client)
    new_cards = next(c for c in columns if c["key"] == "new")["cards"]
    assert [c["project_id"] for c in new_cards] == [hi_id, lo_id]  # ascending board_position


def test_removed_status_surfaces_in_fallback_column(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        # 'archived' is engaged (status != default) but no longer configured.
        make_personal_record(s, project=p, status="archived")
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    columns = _columns(client)
    # Configured columns first, then the trailing fallback for the removed key.
    assert [c["key"] for c in columns[: len(_CONFIGURED_ORDER)]] == _CONFIGURED_ORDER
    fallback = columns[-1]
    assert fallback["key"] == "archived"
    assert fallback["label"] == "archived"  # label_for falls back to the slug
    assert {c["project_id"] for c in fallback["cards"]} == {pid}


def test_card_carries_project_facts(api_env):
    from tests.api.conftest import make_client

    with api_env.session() as s:
        c = make_client(s, _n=1, hiring_rate=72.0)
        p = make_project(s, _n=1, title="مشروع", client_id=c.id, tier=2, currency="USD")
        make_personal_record(s, project=p, status="interested", tags=["x"], board_position=1.0)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    columns = _columns(client)
    card = next(col for col in columns if col["key"] == "interested")["cards"][0]
    assert card["project_id"] == pid
    assert card["title"] == "مشروع"
    assert card["client_hiring_rate"] == 72.0
    assert card["tier"] == 2
    assert card["tier_label"] == "Tier 2"
    assert card["currency"] == "USD"
    assert card["tags"] == ["x"]
    assert card["status"] == "interested"


def test_move_changes_status_and_persists_position(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    resp = client.post(
        "/api/board/move", json={"project_id": pid, "to_status": "applied", "position": 3.0}
    )
    assert resp.status_code == 200
    card = resp.json()
    assert card["status"] == "applied"
    assert card["board_position"] == 3.0
    # →applied records the applied date (visible via the personal record).
    personal = client.get(f"/api/projects/{pid}/personal").json()
    assert personal["applied_at"] is not None
    # The card now lives in the 'applied' column.
    assert pid in _card_ids(_columns(client), "applied")


def test_move_is_last_write_wins(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    client.post("/api/board/move", json={"project_id": pid, "to_status": "interested", "position": 1.0})
    final = client.post(
        "/api/board/move", json={"project_id": pid, "to_status": "won", "position": 5.0}
    ).json()
    assert final["status"] == "won"
    assert final["board_position"] == 5.0
    with api_env.session() as s:
        rec = s.get(PersonalRecord, pid)
        assert rec.status == "won"
        assert rec.board_position == 5.0


def test_move_unknown_status_returns_422(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    resp = client.post(
        "/api/board/move", json={"project_id": pid, "to_status": "bogus", "position": 1.0}
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["key"] == "status"


def test_move_404_when_project_missing(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        "/api/board/move", json={"project_id": 999999, "to_status": "applied", "position": 1.0}
    )
    assert resp.status_code == 404


def test_board_requires_auth(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    assert client.get("/api/board").status_code == 401
    assert (
        client.post(
            "/api/board/move", json={"project_id": 1, "to_status": "applied", "position": 1.0}
        ).status_code
        == 401
    )
