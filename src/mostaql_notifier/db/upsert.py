"""Cross-dialect idempotent upsert (research §3).

The SQLite and Postgres ``on_conflict_do_update`` signatures are mirrored; the only difference is
which ``insert`` to import. We isolate that here so ingestion has one code path.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session


def upsert(
    session: Session,
    model,
    values: Mapping,
    *,
    index_elements: Sequence[str],
    update_cols: Sequence[str],
) -> None:
    """Insert ``values``; on conflict over ``index_elements`` update only ``update_cols``."""
    dialect = session.bind.dialect.name
    insert = sqlite_insert if dialect == "sqlite" else pg_insert
    stmt = insert(model).values(**dict(values))
    set_ = {c: getattr(stmt.excluded, c) for c in update_cols}
    stmt = stmt.on_conflict_do_update(index_elements=list(index_elements), set_=set_)
    session.execute(stmt)


def exists_by(session: Session, model, **filters) -> bool:
    return session.query(model).filter_by(**filters).first() is not None


def pk_columns(model) -> list[str]:
    return [c.key for c in inspect(model).primary_key]
