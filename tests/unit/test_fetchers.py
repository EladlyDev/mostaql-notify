"""Unit tests for the fetch layer: scraper/fetcher.py, scraper/httpx_fetcher.py,
scraper/playwright_fetcher.py.

These exercise the fetcher contracts WITHOUT touching the network or launching a browser:

  * ``HttpxFetcher``: a real ``httpx.AsyncClient`` whose transport is replaced with an
    ``httpx.MockTransport`` so every request hits a local handler. We assert the full
    ``FetchResult`` mapping for 200/403/transport-error cases, header propagation, the
    ``Referer`` request header, and ``aclose`` lifecycle.
  * ``FetchResult.ok``: the fail-closed predicate — True *only* when ``status == 200`` AND
    ``error is None`` (a 200-with-error and a status-0 case must both be False).
  * ``PlaywrightFetcher``: only the import-unavailable branch (we never launch Chromium). The
    lazy ``from playwright.async_api import async_playwright`` is forced to fail and we assert the
    documented ``PlaywrightUnavailable`` contract, plus the ``aclose``-is-a-no-op invariant on a
    never-started fetcher.

Constitution focus:
  * Fail-closed: a transport failure never raises out of the fetcher; it collapses to a
    ``status=0`` ``FetchResult`` with ``error`` set and ``ok is False`` so callers decide.
"""
from __future__ import annotations

import sys

import httpx
import pytest

from mostaql_notifier.scraper.fetcher import Fetcher, FetchResult
from mostaql_notifier.scraper.httpx_fetcher import DEFAULT_HEADERS, HttpxFetcher
from mostaql_notifier.scraper.playwright_fetcher import (
    DEFAULT_LOCALE,
    DEFAULT_USER_AGENT,
    PlaywrightFetcher,
    PlaywrightUnavailable,
)


# ==================================================================================================
# Helpers
# ==================================================================================================
def _mock_fetcher(handler, *, headers: dict[str, str] | None = None) -> HttpxFetcher:
    """An HttpxFetcher whose persistent client routes every request to ``handler`` (no network).

    Only the *transport* is swapped; the replacement client mirrors HttpxFetcher's real config
    (same default/injected headers and follow_redirects) so behaviour under test is faithful.
    """
    fetcher = HttpxFetcher(headers=headers)
    real_headers = dict(fetcher._client.headers)
    fetcher._client = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler),
        http2=False,
        follow_redirects=True,
        headers=real_headers,
    )
    return fetcher


# ==================================================================================================
# FetchResult.ok — the fail-closed predicate (fetcher.py:24-25)
# ==================================================================================================
def test_ok_true_only_for_200_and_no_error():
    r = FetchResult(url="u", status=200, body="x", body_bytes=1, error=None)
    assert r.ok is True


def test_ok_false_for_200_with_error():
    """A 200 carrying an error is NOT ok (fail-closed: both conditions must hold)."""
    r = FetchResult(url="u", status=200, body="x", body_bytes=1, error="weird partial read")
    assert r.ok is False


def test_ok_false_for_transport_error_status_zero():
    r = FetchResult(url="u", status=0, body="", body_bytes=0, error="ConnectError")
    assert r.ok is False


def test_ok_false_for_zero_status_even_without_error():
    """status==0 alone disqualifies, even if error somehow None (status check is independent)."""
    r = FetchResult(url="u", status=0, body="", body_bytes=0, error=None)
    assert r.ok is False


@pytest.mark.parametrize("status", [201, 204, 301, 302, 304, 400, 403, 404, 429, 500, 503])
def test_ok_false_for_every_non_200_status(status):
    r = FetchResult(url="u", status=status, body="b", body_bytes=1, error=None)
    assert r.ok is False


def test_fetchresult_defaults():
    """headers default to an empty dict, elapsed_ms to 0, error to None."""
    r = FetchResult(url="u", status=200, body="b", body_bytes=1)
    assert r.headers == {}
    assert r.elapsed_ms == 0
    assert r.error is None
    assert r.ok is True


def test_fetchresult_is_frozen():
    """FetchResult is an immutable dataclass — callers can't mutate a fetched result."""
    r = FetchResult(url="u", status=200, body="b", body_bytes=1)
    with pytest.raises(AttributeError):  # frozen dataclass -> FrozenInstanceError(AttributeError)
        r.status = 500  # type: ignore[misc]


def test_each_fetchresult_gets_its_own_headers_dict():
    """field(default_factory=dict) — two results must not share one mutable mapping."""
    a = FetchResult(url="a", status=200, body="", body_bytes=0)
    b = FetchResult(url="b", status=200, body="", body_bytes=0)
    assert a.headers is not b.headers


# ==================================================================================================
# Fetcher protocol — runtime_checkable structural typing (fetcher.py:28-32)
# ==================================================================================================
def test_httpx_fetcher_satisfies_fetcher_protocol():
    assert isinstance(HttpxFetcher(), Fetcher)


def test_playwright_fetcher_satisfies_fetcher_protocol():
    assert isinstance(PlaywrightFetcher(), Fetcher)


def test_arbitrary_object_is_not_a_fetcher():
    class NotAFetcher:
        pass

    assert not isinstance(NotAFetcher(), Fetcher)


def test_object_with_only_get_is_not_a_fetcher():
    """runtime_checkable requires BOTH get and aclose to be present."""

    class Half:
        async def get(self, url, *, referer=None):
            ...

    assert not isinstance(Half(), Fetcher)


# ==================================================================================================
# HttpxFetcher.__init__ — header selection (httpx_fetcher.py:38-44)
# ==================================================================================================
def test_default_headers_used_when_none_passed():
    fetcher = HttpxFetcher()
    # The client copies DEFAULT_HEADERS (Arabic-first Accept-Language).
    assert fetcher._client.headers.get("Accept-Language") == "ar,en-US;q=0.9,en;q=0.8"
    assert fetcher._client.headers.get("User-Agent") == DEFAULT_HEADERS["User-Agent"]


def test_default_headers_are_copied_not_shared():
    """dict(DEFAULT_HEADERS) — mutating the client's headers must not corrupt the module default."""
    before = dict(DEFAULT_HEADERS)
    fetcher = HttpxFetcher()
    fetcher._client.headers["User-Agent"] = "mutated"
    assert DEFAULT_HEADERS == before
    assert DEFAULT_HEADERS["User-Agent"] != "mutated"


def test_injected_headers_replace_defaults():
    fetcher = HttpxFetcher(headers={"X-Custom": "1", "User-Agent": "rotated-ua"})
    assert fetcher._client.headers.get("X-Custom") == "1"
    assert fetcher._client.headers.get("User-Agent") == "rotated-ua"
    # A default-only header is NOT present when a caller injects their own set.
    assert "sec-fetch-dest" not in fetcher._client.headers


def test_empty_headers_dict_is_respected_not_treated_as_none():
    """An explicit empty dict means 'no default headers' — it is distinct from None."""
    fetcher = HttpxFetcher(headers={})
    assert fetcher._client.headers.get("Accept-Language") is None


def test_injected_headers_are_copied():
    src = {"X-Custom": "1"}
    fetcher = HttpxFetcher(headers=src)
    fetcher._client.headers["X-Custom"] = "changed"
    assert src["X-Custom"] == "1"


# ==================================================================================================
# HttpxFetcher.get — 200 success (httpx_fetcher.py:46-70)
# ==================================================================================================
async def test_get_200_maps_to_fetchresult():
    def handler(request):
        return httpx.Response(
            200, text="<html>مرحبا</html>", headers={"Content-Type": "text/html; charset=utf-8"}
        )

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/projects")

    assert isinstance(res, FetchResult)
    assert res.status == 200
    assert res.body == "<html>مرحبا</html>"
    # body_bytes is the raw byte length of the content, not the str length.
    assert res.body_bytes == len("<html>مرحبا</html>".encode())
    assert res.body_bytes == len(res.body.encode("utf-8"))
    assert res.error is None
    assert res.ok is True
    assert res.elapsed_ms >= 0
    await fetcher.aclose()


async def test_get_200_body_bytes_differ_from_str_len_for_arabic():
    """Arabic-Indic content: byte length must exceed character length (UTF-8 multibyte)."""
    body = "٠١٢٣ مشروع"  # Arabic-Indic digits + Arabic word

    def handler(request):
        return httpx.Response(200, content=body.encode("utf-8"))

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/p")
    assert res.body == body
    assert res.body_bytes == len(body.encode("utf-8"))
    assert res.body_bytes > len(body)
    await fetcher.aclose()


async def test_get_200_propagates_headers_as_plain_dict():
    def handler(request):
        return httpx.Response(200, text="x", headers={"X-Block": "false", "Server": "nginx"})

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/p")
    assert isinstance(res.headers, dict)
    # httpx lowercases header names.
    assert res.headers.get("x-block") == "false"
    assert res.headers.get("server") == "nginx"
    await fetcher.aclose()


async def test_get_uses_final_url_after_redirect():
    """follow_redirects=True: the FetchResult.url reflects the FINAL resolved url, not the input."""

    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "https://mostaql.com/final"})
        return httpx.Response(200, text="landed")

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/start")
    assert res.status == 200
    assert res.body == "landed"
    assert res.url == "https://mostaql.com/final"
    await fetcher.aclose()


# ==================================================================================================
# HttpxFetcher.get — non-200 statuses are returned, never raised (httpx_fetcher.py:62-70)
# ==================================================================================================
async def test_get_403_returns_result_not_raises():
    def handler(request):
        return httpx.Response(403, text="forbidden")

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/p")
    assert res.status == 403
    assert res.body == "forbidden"
    assert res.error is None  # an HTTP error status is NOT a transport error
    assert res.ok is False
    await fetcher.aclose()


@pytest.mark.parametrize("status", [301, 400, 404, 429, 500, 503])
async def test_get_various_error_statuses_pass_through(status):
    def handler(request):
        # 3xx without Location won't redirect; return a plain body for all.
        return httpx.Response(status, text="body")

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/p")
    assert res.status == status
    assert res.error is None
    assert res.ok is False
    await fetcher.aclose()


async def test_get_empty_body_has_zero_body_bytes():
    def handler(request):
        return httpx.Response(204)

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/p")
    assert res.body == ""
    assert res.body_bytes == 0
    await fetcher.aclose()


# ==================================================================================================
# HttpxFetcher.get — transport error collapses to status 0 (httpx_fetcher.py:51-60)
# ==================================================================================================
async def test_get_connect_error_collapses_to_status_zero():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/p")
    assert res.status == 0
    assert res.body == ""
    assert res.body_bytes == 0
    assert res.error is not None
    assert "connection refused" in res.error
    assert res.ok is False
    # The url echoed back is the REQUESTED url (no response to read a final url from).
    assert res.url == "https://mostaql.com/p"
    await fetcher.aclose()


async def test_get_timeout_collapses_to_status_zero():
    """ReadTimeout is an httpx.HTTPError subclass — also fail-closed to status 0."""

    def handler(request):
        raise httpx.ReadTimeout("timed out")

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/p")
    assert res.status == 0
    assert res.error is not None
    assert res.ok is False
    await fetcher.aclose()


async def test_get_pool_timeout_collapses_to_status_zero():
    def handler(request):
        raise httpx.PoolTimeout("pool exhausted")

    fetcher = _mock_fetcher(handler)
    res = await fetcher.get("https://mostaql.com/p")
    assert res.status == 0
    assert res.error is not None
    assert res.ok is False
    await fetcher.aclose()


async def test_get_does_not_catch_non_http_exceptions():
    """The except is narrowed to httpx.HTTPError; a programming error (ValueError) must propagate,
    not be silently swallowed as a status-0 result."""

    def handler(request):
        raise ValueError("not a transport error")

    fetcher = _mock_fetcher(handler)
    with pytest.raises(ValueError):
        await fetcher.get("https://mostaql.com/p")
    await fetcher.aclose()


# ==================================================================================================
# HttpxFetcher.get — Referer handling (httpx_fetcher.py:47, 50)
# ==================================================================================================
async def test_referer_passed_as_request_header():
    seen = {}

    def handler(request):
        seen["referer"] = request.headers.get("Referer")
        return httpx.Response(200, text="ok")

    fetcher = _mock_fetcher(handler)
    await fetcher.get("https://mostaql.com/p", referer="https://mostaql.com/projects")
    assert seen["referer"] == "https://mostaql.com/projects"
    await fetcher.aclose()


async def test_no_referer_means_no_referer_header_override():
    """When referer is None the per-request header dict is None, so the client's default headers
    apply and no Referer is injected."""
    seen = {}

    def handler(request):
        seen["referer"] = request.headers.get("Referer")
        return httpx.Response(200, text="ok")

    fetcher = _mock_fetcher(handler)
    await fetcher.get("https://mostaql.com/p")
    assert seen["referer"] is None
    await fetcher.aclose()


async def test_empty_string_referer_is_treated_as_falsy_no_header():
    """An empty-string referer is falsy, so the code sends no Referer header (referer or None)."""
    seen = {}

    def handler(request):
        seen["referer"] = request.headers.get("Referer")
        return httpx.Response(200, text="ok")

    fetcher = _mock_fetcher(handler)
    await fetcher.get("https://mostaql.com/p", referer="")
    assert seen["referer"] is None
    await fetcher.aclose()


async def test_referer_does_not_persist_to_later_requests():
    """The Referer is a per-request header, not stored on the client — a subsequent get without a
    referer must not leak the previous one."""
    seen: list[str | None] = []

    def handler(request):
        seen.append(request.headers.get("Referer"))
        return httpx.Response(200, text="ok")

    fetcher = _mock_fetcher(handler)
    await fetcher.get("https://mostaql.com/a", referer="https://ref/")
    await fetcher.get("https://mostaql.com/b")
    assert seen == ["https://ref/", None]
    await fetcher.aclose()


async def test_default_headers_still_sent_on_get():
    """The persistent client's default headers (User-Agent etc.) accompany every request."""
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("User-Agent")
        seen["al"] = request.headers.get("Accept-Language")
        return httpx.Response(200, text="ok")

    fetcher = _mock_fetcher(handler)
    await fetcher.get("https://mostaql.com/p")
    assert seen["ua"] == DEFAULT_HEADERS["User-Agent"]
    assert seen["al"] == "ar,en-US;q=0.9,en;q=0.8"
    await fetcher.aclose()


# ==================================================================================================
# HttpxFetcher.aclose — lifecycle (httpx_fetcher.py:72-73)
# ==================================================================================================
async def test_aclose_closes_the_client():
    def handler(request):
        return httpx.Response(200, text="ok")

    fetcher = _mock_fetcher(handler)
    assert fetcher._client.is_closed is False
    await fetcher.aclose()
    assert fetcher._client.is_closed is True


async def test_get_after_aclose_raises():
    """Once closed, the persistent client is unusable — a further get must error (the worker should
    not silently re-open a fetcher it has retired)."""
    def handler(request):
        return httpx.Response(200, text="ok")

    fetcher = _mock_fetcher(handler)
    await fetcher.aclose()
    with pytest.raises(RuntimeError):
        await fetcher.get("https://mostaql.com/p")


async def test_multiple_gets_reuse_one_persistent_client():
    """The client instance is the same across calls (persistent connection reuse)."""
    def handler(request):
        return httpx.Response(200, text="ok")

    fetcher = _mock_fetcher(handler)
    client_before = fetcher._client
    await fetcher.get("https://mostaql.com/a")
    await fetcher.get("https://mostaql.com/b")
    assert fetcher._client is client_before
    await fetcher.aclose()


# ==================================================================================================
# PlaywrightFetcher.__init__ — construction is cheap and lazy (playwright_fetcher.py:28-38)
# ==================================================================================================
def test_playwright_init_does_not_start_browser():
    fetcher = PlaywrightFetcher()
    assert fetcher._playwright is None
    assert fetcher._browser is None


def test_playwright_init_defaults():
    fetcher = PlaywrightFetcher()
    assert fetcher._user_agent == DEFAULT_USER_AGENT
    assert fetcher._locale == DEFAULT_LOCALE
    # timeout seconds -> ms.
    assert fetcher._timeout_ms == 20_000


def test_playwright_init_custom_timeout_converts_to_ms():
    fetcher = PlaywrightFetcher(timeout=2.5)
    assert fetcher._timeout_ms == 2500


def test_playwright_satisfies_protocol_without_starting():
    assert isinstance(PlaywrightFetcher(), Fetcher)


# ==================================================================================================
# PlaywrightFetcher import-unavailable path (playwright_fetcher.py:43-46)
# ==================================================================================================
@pytest.fixture
def _no_playwright(monkeypatch):
    """Force ``from playwright.async_api import async_playwright`` to raise ImportError without
    uninstalling the package. Setting the submodule to None in sys.modules makes the import
    machinery raise 'import ... halted; None in sys.modules'."""
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)


async def test_ensure_browser_raises_playwright_unavailable_on_import_failure(_no_playwright):
    fetcher = PlaywrightFetcher()
    with pytest.raises(PlaywrightUnavailable) as ei:
        await fetcher._ensure_browser()
    assert "import failed" in str(ei.value)
    # Nothing was started.
    assert fetcher._browser is None
    assert fetcher._playwright is None


async def test_playwright_unavailable_is_a_runtimeerror():
    """Callers may catch it as RuntimeError to fall back to HttpxFetcher."""
    assert issubclass(PlaywrightUnavailable, RuntimeError)
    err = PlaywrightUnavailable("x")
    assert isinstance(err, RuntimeError)


async def test_get_raises_playwright_unavailable_when_import_fails(_no_playwright):
    """get() begins with _ensure_browser(); when the import fails the contract is to RAISE
    PlaywrightUnavailable (the try/except around navigation does not wrap _ensure_browser, so the
    error is NOT swallowed into a status-0 FetchResult — it propagates for the caller to fall back).
    """
    fetcher = PlaywrightFetcher()
    with pytest.raises(PlaywrightUnavailable):
        await fetcher.get("https://mostaql.com/p")


async def test_unavailable_error_chains_the_original_importerror(_no_playwright):
    fetcher = PlaywrightFetcher()
    with pytest.raises(PlaywrightUnavailable) as ei:
        await fetcher._ensure_browser()
    assert isinstance(ei.value.__cause__, ImportError)


# ==================================================================================================
# PlaywrightFetcher.aclose — no-op on a never-started fetcher (playwright_fetcher.py:96-102)
# ==================================================================================================
async def test_aclose_is_noop_when_never_started():
    fetcher = PlaywrightFetcher()
    # Both guards are False, so aclose touches nothing and does not raise.
    await fetcher.aclose()
    assert fetcher._browser is None
    assert fetcher._playwright is None


async def test_aclose_idempotent_when_never_started(_no_playwright):
    """A failed _ensure_browser leaves the fetcher unstarted; aclose must remain a clean no-op
    (and be safely callable more than once)."""
    fetcher = PlaywrightFetcher()
    with pytest.raises(PlaywrightUnavailable):
        await fetcher._ensure_browser()
    await fetcher.aclose()
    await fetcher.aclose()
    assert fetcher._browser is None
    assert fetcher._playwright is None
