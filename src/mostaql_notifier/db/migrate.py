"""Programmatic Alembic runner so `python -m mostaql_notifier` self-migrates on startup.

`alembic upgrade head` on the CLI works too; both use the same alembic/ env.
"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _alembic_cfg() -> Config:
    return Config(str(_REPO_ROOT / "alembic.ini"))


def upgrade_head() -> None:
    command.upgrade(_alembic_cfg(), "head")
