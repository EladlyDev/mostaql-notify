"""Tests for the gated Playwright fallback fetcher WITHOUT launching a real browser.

A fake ``playwright.async_api`` module is injected into ``sys.modules`` so the lazy
``from playwright.async_api import async_playwright`` inside ``_ensure_browser`` resolves to
controllable fakes. This exercises the success path, the navigation-error path, the launch-failure
(=> PlaywrightUnavailable) path, browser reuse, and teardown — none of which need Chromium.
"""
from __future__ import annotations

import sys
import types

import pytest

from mostaql_notifier.scraper.fetcher import Fetcher, FetchResult
from mostaql_notifier.scraper.playwright_fetcher import (
    PlaywrightFetcher,
    PlaywrightUnavailable,
)

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- fakes


class _FakeResponse:
    def __init__(self, status=200, headers=None):
        self.status = status
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}


class _FakePage:
    def __init__(self, *, body="<html>مرحبا</html>", response=None, goto_raises=None):
        self._body = body
        self._response = response if response is not None else _FakeResponse()
        self._goto_raises = goto_raises
        self.url = "about:blank"
        self.goto_args = None

    async def goto(self, url, *, referer=None, wait_until=None, timeout=None):
        self.goto_args = {"url": url, "referer": referer, "wait_until": wait_until, "timeout": timeout}
        if self._goto_raises is not None:
            raise self._goto_raises
        self.url = url
        return self._response

    async def content(self):
        return self._body


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False
        self.new_context_seen = False

    async def new_page(self):
        return self._page

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, context):
        self._context = context
        self.closed = False
        self.new_context_kwargs = None

    async def new_context(self, **kwargs):
        self.new_context_kwargs = kwargs
        return self._context

    async def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser, launch_raises=None):
        self._browser = browser
        self._launch_raises = launch_raises
        self.launch_count = 0
        self.launch_kwargs = None

    async def launch(self, **kwargs):
        self.launch_count += 1
        self.launch_kwargs = kwargs
        if self._launch_raises is not None:
            raise self._launch_raises
        return self._browser


class _FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium
        self.stopped = False

    async def stop(self):
        self.stopped = True


class _FakeAsyncPlaywrightCM:
    def __init__(self, pw):
        self._pw = pw

    async def start(self):
        return self._pw


def _install_fake_playwright(monkeypatch, *, page=None, launch_raises=None):
    page = page or _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser, launch_raises=launch_raises)
    pw = _FakePlaywright(chromium)

    mod = types.ModuleType("playwright.async_api")
    mod.async_playwright = lambda: _FakeAsyncPlaywrightCM(pw)
    parent = types.ModuleType("playwright")
    parent.async_api = mod
    monkeypatch.setitem(sys.modules, "playwright", parent)
    monkeypatch.setitem(sys.modules, "playwright.async_api", mod)
    return {"page": page, "context": context, "browser": browser, "chromium": chromium, "pw": pw}


# --------------------------------------------------------------------------- tests


async def test_get_success_returns_fetchresult(monkeypatch):
    fakes = _install_fake_playwright(monkeypatch)
    fetcher = PlaywrightFetcher(timeout=5.0)

    result = await fetcher.get("https://mostaql.com/projects/development", referer="https://mostaql.com/")

    assert isinstance(result, FetchResult)
    assert result.status == 200
    assert result.body == "<html>مرحبا</html>"
    assert result.body_bytes == len("<html>مرحبا</html>".encode())
    assert result.error is None
    assert result.ok is True
    assert result.url == "https://mostaql.com/projects/development"
    assert result.headers["content-type"].startswith("text/html")
    # navigation args forwarded (referer + domcontentloaded + ms timeout)
    assert fakes["page"].goto_args["referer"] == "https://mostaql.com/"
    assert fakes["page"].goto_args["wait_until"] == "domcontentloaded"
    assert fakes["page"].goto_args["timeout"] == 5000
    # Arabic locale + Accept-Language carried into the context.
    assert fakes["browser"].new_context_kwargs["locale"] == "ar"
    assert fakes["browser"].new_context_kwargs["extra_http_headers"]["Accept-Language"].startswith("ar")
    # the per-request context is always closed (finally)
    assert fakes["context"].closed is True

    await fetcher.aclose()
    assert fakes["browser"].closed is True
    assert fakes["pw"].stopped is True


async def test_get_navigation_error_collapses_to_status_zero(monkeypatch):
    page = _FakePage(goto_raises=RuntimeError("net::ERR_TIMED_OUT"))
    fakes = _install_fake_playwright(monkeypatch, page=page)
    fetcher = PlaywrightFetcher()

    result = await fetcher.get("https://mostaql.com/x")

    assert result.status == 0
    assert result.body == ""
    assert result.body_bytes == 0
    assert result.error is not None and "ERR_TIMED_OUT" in result.error
    assert result.ok is False
    # context still closed despite the error (finally)
    assert fakes["context"].closed is True


async def test_browser_is_launched_once_and_reused(monkeypatch):
    fakes = _install_fake_playwright(monkeypatch)
    fetcher = PlaywrightFetcher()

    await fetcher.get("https://mostaql.com/a")
    await fetcher.get("https://mostaql.com/b")

    assert fakes["chromium"].launch_count == 1  # _ensure_browser short-circuits on the 2nd call
    assert fakes["chromium"].launch_kwargs == {"headless": True}


async def test_launch_failure_raises_playwright_unavailable(monkeypatch):
    _install_fake_playwright(monkeypatch, launch_raises=RuntimeError("no chromium binary"))
    fetcher = PlaywrightFetcher()

    with pytest.raises(PlaywrightUnavailable) as ei:
        await fetcher.get("https://mostaql.com/x")
    assert "chromium launch failed" in str(ei.value)
    # cleaned up: a second aclose is still safe
    await fetcher.aclose()


async def test_import_unavailable_raises_playwright_unavailable(monkeypatch):
    # Simulate playwright not installed: importing the submodule raises ImportError.
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    fetcher = PlaywrightFetcher()
    with pytest.raises(PlaywrightUnavailable) as ei:
        await fetcher.get("https://mostaql.com/x")
    assert "import failed" in str(ei.value)


async def test_aclose_is_noop_before_start():
    fetcher = PlaywrightFetcher()
    # Never started a browser -> aclose must not raise.
    await fetcher.aclose()


async def test_playwright_fetcher_satisfies_fetcher_protocol():
    assert isinstance(PlaywrightFetcher(), Fetcher)
