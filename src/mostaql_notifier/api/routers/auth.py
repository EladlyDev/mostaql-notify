"""Auth routes: login (issue cookie), logout (clear), status (introspect)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from ..schemas import AuthStatus, LoginRequest
from ..security import (
    SecretsDep,
    clear_session,
    is_authenticated,
    issue_session,
    password_matches,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=AuthStatus)
def login(
    body: LoginRequest,
    response: Response,
    secrets: SecretsDep,
) -> AuthStatus:
    # When auth is disabled, any login "succeeds" (the gate is open anyway).
    if secrets.dashboard_auth_enabled and not password_matches(body.password, secrets):
        raise HTTPException(status_code=401, detail="Invalid password")
    issue_session(response, secrets)
    return AuthStatus(authenticated=True, auth_enabled=secrets.dashboard_auth_enabled)


@router.post("/logout", response_model=AuthStatus)
def logout(response: Response, secrets: SecretsDep) -> AuthStatus:
    clear_session(response)
    return AuthStatus(authenticated=False, auth_enabled=secrets.dashboard_auth_enabled)


@router.get("/status", response_model=AuthStatus)
def status(request: Request, secrets: SecretsDep) -> AuthStatus:
    return AuthStatus(
        authenticated=is_authenticated(request, secrets),
        auth_enabled=secrets.dashboard_auth_enabled,
    )
