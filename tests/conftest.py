"""Shared pytest fixtures: a temp-file SQLite session, seeded settings, and the fixtures dir."""
from __future__ import annotations

import pathlib

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from mostaql_notifier.config.settings_store import SettingsStore, seed_defaults
from mostaql_notifier.db import models  # noqa: F401  (register tables)
from mostaql_notifier.db.base import Base

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def engine(tmp_path):
    eng = sa.create_engine(f"sqlite:///{tmp_path}/test.db", future=True)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db_session(engine):
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    with Session() as s:
        yield s


@pytest.fixture
def settings(db_session):
    seed_defaults(db_session)
    return SettingsStore(db_session)


@pytest.fixture
def fixtures_dir() -> pathlib.Path:
    return FIXTURES


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
