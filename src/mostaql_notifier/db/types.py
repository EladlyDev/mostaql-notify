"""Portable SQLAlchemy column types (research §3).

These normalise the SQLite/Postgres differences at the type layer so models and queries run
unchanged on both backends (constitution X — deployment-portable).
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """Timezone-aware UTC datetime that behaves identically on SQLite and Postgres.

    On write: rejects naive datetimes (fail-loud) and converts aware values to UTC.
    On read: re-attaches ``timezone.utc`` so callers always receive aware UTC.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"UtcDateTime expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            raise ValueError("UtcDateTime refuses naive datetimes; pass timezone-aware UTC")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# JSON that upgrades to JSONB on Postgres automatically, plain JSON1 on SQLite.
JSONType = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def make_enum(py_enum: type[enum.Enum], name: str) -> sa.Enum:
    """Portable enum: a named CHECK constraint instead of a native DB enum type."""
    return sa.Enum(py_enum, native_enum=False, name=name, validate_strings=True)


def utcnow() -> datetime:
    """The one approved way to get 'now' — always aware UTC."""
    return datetime.now(timezone.utc)
