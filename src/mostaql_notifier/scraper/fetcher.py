"""The fetch-layer seam (contracts/fetcher-interface.md).

Everything above this interface (parsing, qualification, notification) depends only on
``FetchResult`` — never on httpx or Playwright types — so the fetcher is swappable.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int                 # HTTP status; 0 on transport error
    body: str                   # decoded UTF-8 text ("" on transport error)
    body_bytes: int             # raw length, for size-based block detection
    headers: Mapping[str, str] = field(default_factory=dict)
    elapsed_ms: int = 0
    error: str | None = None    # transport/exception summary, else None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None


@runtime_checkable
class Fetcher(Protocol):
    async def get(self, url: str, *, referer: str | None = None) -> FetchResult: ...

    async def aclose(self) -> None: ...
