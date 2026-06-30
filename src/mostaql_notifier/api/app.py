"""FastAPI application factory for the dashboard backend (Feature 2).

Reuses Feature 1's engine/session (single source of truth) and ensures SQLite WAL is applied on
startup. CORS is restricted to the configured frontend origin with credentials allowed so the
signed session cookie flows. Every data/settings route is gated by :func:`require_auth`.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config.secrets import get_secrets, require_dashboard
from ..db.session import get_engine
from .security import require_auth


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Touch the engine so the sqlite connect-listener applies WAL + busy_timeout.
    get_engine()
    # Feature 3 — ensure the attachments directory exists before any upload is served (it lives
    # under the backed-up ./data volume, outside any public web path).
    os.makedirs(get_secrets().attachments_dir, exist_ok=True)
    yield


def create_app() -> FastAPI:
    secrets = get_secrets()
    # Fail loud if auth is enabled but the password/secret are missing (mirrors require_telegram).
    require_dashboard(secrets)

    app = FastAPI(
        title="Mostaql Notifier — Dashboard API",
        version="1.0.0",
        description="Read-mostly JSON API over Feature 1's local SQLite database.",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[secrets.frontend_origin],
        allow_credentials=True,
        # Feature 3 adds PATCH (personal/rename) and DELETE (attachments) verbs.
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Auth routes are public (login/logout/status); data + settings routes are gated.
    from .routers import (
        analytics,
        attachments,
        auth,
        board,
        control,
        home,
        personal,
        projects,
        settings,
    )

    app.include_router(auth.router)
    app.include_router(projects.router, dependencies=[Depends(require_auth)])
    app.include_router(home.router, dependencies=[Depends(require_auth)])
    app.include_router(settings.router, dependencies=[Depends(require_auth)])
    # Feature 6 — read-only analytics overview (auth-gated like every data route).
    app.include_router(analytics.router, dependencies=[Depends(require_auth)])
    # Feature 3 — personal pipeline & workspace (all auth-gated).
    app.include_router(personal.router, dependencies=[Depends(require_auth)])
    app.include_router(board.router, dependencies=[Depends(require_auth)])
    app.include_router(attachments.router, dependencies=[Depends(require_auth)])
    app.include_router(control.router, dependencies=[Depends(require_auth)])

    return app


app = create_app()
