"""Feature 3 added PATCH (personal updates) and DELETE (attachment removal); the browser can only
use them if the CORS preflight grants those methods to the configured origin. Feature 2's policy
only covered GET/POST/PUT/OPTIONS, so this pins the two new verbs explicitly.
"""
from __future__ import annotations

import pytest

ALLOWED_ORIGIN = "http://localhost:3000"  # api_env pins FRONTEND_ORIGIN to this


@pytest.mark.parametrize(
    "method, path",
    [
        ("PATCH", "/api/projects/1/personal"),
        ("DELETE", "/api/attachments/1"),
        ("POST", "/api/board/move"),
    ],
)
def test_cors_preflight_allows_feature3_methods(api_env, method, path):
    client = api_env.client()
    resp = client.options(
        path,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": method,
        },
    )
    assert resp.status_code in (200, 204)
    allow = resp.headers.get("access-control-allow-methods", "")
    assert method in allow or "*" in allow
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_cors_preflight_rejects_evil_origin_for_feature3_methods(api_env, method):
    client = api_env.client()
    resp = client.options(
        "/api/projects/1/personal",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": method,
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "http://evil.example"
