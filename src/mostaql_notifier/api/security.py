"""Single shared-password auth gate (constitution IX — local security).

Login exchanges the configured password for a signed, HttpOnly, SameSite=Lax cookie
(``mn_session``) carrying a short token signed with ``itsdangerous``. Every data/settings route
depends on :func:`require_auth`, which is a no-op when ``dashboard_auth_enabled=false`` so a
local-only owner can disable login via config alone.
"""
from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config.secrets import Secrets, get_secrets

# Module-level dependency alias (keeps Depends() out of argument defaults — ruff B008).
SecretsDep = Annotated[Secrets, Depends(get_secrets)]

SESSION_COOKIE = "mn_session"
_SESSION_SALT = "mn-dashboard-session"
_SESSION_PAYLOAD = "ok"  # single-user: presence of a valid signature is the whole claim
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days


def _serializer(secrets: Secrets) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secrets.dashboard_session_secret or "insecure-dev-secret",
                                  salt=_SESSION_SALT)


def password_matches(candidate: str, secrets: Secrets) -> bool:
    """Constant-time comparison against the configured dashboard password."""
    expected = secrets.dashboard_password or ""
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def issue_session(response: Response, secrets: Secrets) -> None:
    token = _serializer(secrets).dumps(_SESSION_PAYLOAD)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # local HTTP; flip to true behind TLS
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def is_authenticated(request: Request, secrets: Secrets) -> bool:
    if not secrets.dashboard_auth_enabled:
        return True
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    try:
        _serializer(secrets).loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return True


def require_auth(request: Request, secrets: SecretsDep) -> None:
    """Route dependency: 401 unless authenticated (bypassed when auth disabled)."""
    if not is_authenticated(request, secrets):
        raise HTTPException(status_code=401, detail="Not authenticated")
