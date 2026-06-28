"""Service-level guards for non-finite numerics (integrator hardening).

`move`/`reorder` board positions and `set_outcome` won amounts must reject NaN/±inf with a clean
`PersonalValidationError` (the API maps it to 422). A non-finite value would otherwise serialize as
the invalid-JSON tokens `Infinity`/`NaN` (breaking the browser), and `Decimal('NaN') < 0` raises.
These exercise the paths directly (the API's float typing can't reach the non-numeric branch).
"""
from __future__ import annotations

import pytest

from mostaql_notifier.db.models import EvalStatus, PersonalRecord, Project, ProjectStatus
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.personal import service


def _project(session) -> int:
    p = Project(
        mostaql_id="p1",
        url="https://mostaql.com/project/1",
        title="t",
        site_status=ProjectStatus.unknown,
        eval_status=EvalStatus.pending,
        scraped_at=utcnow(),
        raw={},
    )
    session.add(p)
    session.flush()
    return p.id


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_move_rejects_non_finite_position_without_touching_status(db_session, settings, bad):
    pid = _project(db_session)
    with pytest.raises(service.PersonalValidationError) as ei:
        service.move(db_session, pid, "interested", bad)
    assert ei.value.key == "position"
    # Position is validated first, so a fresh project gets no record (status never mutated).
    assert db_session.get(PersonalRecord, pid) is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_reorder_rejects_non_finite_position(db_session, settings, bad):
    pid = _project(db_session)
    service.reorder(db_session, pid, 1.0)  # establish a record + valid position
    with pytest.raises(service.PersonalValidationError) as ei:
        service.reorder(db_session, pid, bad)
    assert ei.value.key == "position"
    assert db_session.get(PersonalRecord, pid).board_position == 1.0  # unchanged


def test_finite_position_rejects_non_numeric(db_session, settings):
    with pytest.raises(service.PersonalValidationError) as ei:
        service._finite_position(object())
    assert ei.value.key == "position"


def test_finite_position_accepts_int_and_float(db_session, settings):
    assert service._finite_position(3) == 3.0
    assert service._finite_position(2.5) == 2.5


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_set_outcome_rejects_non_finite_won_amount(db_session, settings, bad):
    pid = _project(db_session)
    with pytest.raises(service.PersonalValidationError) as ei:
        service.set_outcome(db_session, pid, won_amount=bad)
    assert ei.value.key == "won_amount"
