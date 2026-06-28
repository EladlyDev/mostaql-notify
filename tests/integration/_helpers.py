"""Shared helpers for poll-cycle integration tests (no network)."""
from __future__ import annotations

from mostaql_notifier.db.models import Setting
from mostaql_notifier.notify.telegram import TelegramSender
from mostaql_notifier.scraper.fetcher import FetchResult


class FakeFetcher:
    """Routes URLs (by substring) to canned responses. 200s default to a large body_bytes so the
    block detector treats them as full pages."""

    def __init__(self, routes):
        # routes: list of (substring, status, body, body_bytes|None)
        self.routes = routes
        self.calls: list[str] = []

    async def get(self, url, *, referer=None):
        self.calls.append(url)
        for sub, status, body, bb in self.routes:
            if sub in url:
                nbytes = bb if bb is not None else (200_000 if status == 200 else len(body.encode("utf-8")))
                return FetchResult(url=url, status=status, body=body, body_bytes=nbytes)
        return FetchResult(url=url, status=404, body="", body_bytes=0, error="no route")

    async def aclose(self):
        pass


def make_sender() -> TelegramSender:
    """A real TelegramSender with the network send stubbed — exercises the real dedup path."""
    sender = TelegramSender("test-token", "test-chat")
    sent: list[str] = []

    async def _fake_send(text: str, reply_markup=None) -> None:
        # Mirrors the real _send signature (Feature 3 added the optional reply_markup so project
        # notifications can carry inline action buttons).
        sent.append(text)

    sender._send = _fake_send  # type: ignore[method-assign]
    sender.sent = sent  # type: ignore[attr-defined]
    return sender


def set_setting(session, settings, key: str, value) -> None:
    row = session.get(Setting, key)
    if isinstance(value, bool):
        row.value = "true" if value else "false"
    else:
        row.value = str(value)
    session.commit()
    settings.reload()
