"""The primary fetcher: a single persistent HTTP/2 ``httpx.AsyncClient``.

Implements the :class:`Fetcher` protocol. It never raises on HTTP status (a 403/503 is a
``FetchResult`` like any other); transport-level failures collapse to ``status=0`` with the
exception summary in ``error`` (fail-closed — callers decide what to do, the fetcher never
crashes the worker).
"""
from __future__ import annotations

import time

import httpx

from .fetcher import FetchResult

# A realistic Firefox desktop header set (Arabic-first Accept-Language). Used unless the caller
# injects a rotated set from worker.politeness.HEADER_SETS.
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class HttpxFetcher:
    """One persistent client, reused across the worker's lifetime."""

    def __init__(self, headers: dict[str, str] | None = None, timeout: float = 20.0):
        self._client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=timeout,
            headers=dict(headers) if headers is not None else dict(DEFAULT_HEADERS),
        )

    async def get(self, url: str, *, referer: str | None = None) -> FetchResult:
        request_headers = {"Referer": referer} if referer else None
        start = time.perf_counter()
        try:
            response = await self._client.get(url, headers=request_headers)
        except httpx.HTTPError as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return FetchResult(
                url=url,
                status=0,
                body="",
                body_bytes=0,
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(
            url=str(response.url),
            status=response.status_code,
            body=response.text,
            body_bytes=len(response.content),
            headers=dict(response.headers),
            elapsed_ms=elapsed_ms,
            error=None,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
