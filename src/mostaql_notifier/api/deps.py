"""Request-scoped dependencies for the dashboard API.

Reuses Feature 1's sessionmaker (single source of truth). Read sessions are opened and closed
per request; any DB/operational error is surfaced as HTTP 503 (backend unreachable) so the
frontend shows its error state rather than a blank screen.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..db.session import get_sessionmaker


def get_db() -> Iterator[Session]:
    """Yield a request-scoped SQLAlchemy session; map DB failures to 503."""
    try:
        session_factory = get_sessionmaker()
    except SQLAlchemyError as exc:  # engine could not be created
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    session = session_factory()
    try:
        yield session
    except OperationalError as exc:  # locked / unreachable DB mid-request
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    finally:
        session.close()
