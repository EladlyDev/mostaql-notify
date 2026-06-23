"""Gated fallback fetcher backed by headless Chromium (Playwright).

Playwright is heavy and optional, so it is imported lazily inside the methods. If the import
fails, :class:`PlaywrightUnavailable` is raised — callers are expected to fall back to
:class:`HttpxFetcher` rather than crash. This path is only used when the primary fetcher
repeatedly hits a JS/challenge wall.
"""
from __future__ import annotations

import time

from .fetcher import FetchResult

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_LOCALE = "ar"


class PlaywrightUnavailable(RuntimeError):
    """Raised when Playwright (or its browser binary) cannot be loaded/launched."""


class PlaywrightFetcher:
    """Minimal Playwright wrapper. Lazily starts a browser on first ``get``."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        locale: str = DEFAULT_LOCALE,
        timeout: float = 20.0,
    ):
        self._user_agent = user_agent
        self._locale = locale
        self._timeout_ms = int(timeout * 1000)
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - exercised only without playwright
            raise PlaywrightUnavailable(f"playwright import failed: {exc}") from exc
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 - any launch error means "unavailable"
            await self.aclose()
            raise PlaywrightUnavailable(f"chromium launch failed: {exc}") from exc

    async def get(self, url: str, *, referer: str | None = None) -> FetchResult:
        await self._ensure_browser()
        context = await self._browser.new_context(
            user_agent=self._user_agent,
            locale=self._locale,
            extra_http_headers={"Accept-Language": "ar,en-US;q=0.9,en;q=0.8"},
        )
        page = await context.new_page()
        start = time.perf_counter()
        try:
            response = await page.goto(
                url,
                referer=referer,
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )
            body = await page.content()
            status = response.status if response is not None else 0
            headers = dict(response.headers) if response is not None else {}
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return FetchResult(
                url=page.url,
                status=status,
                body=body,
                body_bytes=len(body.encode("utf-8")),
                headers=headers,
                elapsed_ms=elapsed_ms,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001 - navigation/timeout collapses to status 0
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return FetchResult(
                url=url,
                status=0,
                body="",
                body_bytes=0,
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )
        finally:
            await context.close()

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
