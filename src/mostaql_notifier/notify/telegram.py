"""Telegram delivery: a thin async sender with retries + per-project dedup.

The bot is built lazily (and torn down explicitly) so importing this module never touches the
network. Sends are idempotent at the project level via a ``NotificationLog`` dedup row, and the
log-row + ``project.notified`` flag are written in a single transaction so a crash can never leave
"notified but unlogged" (or vice versa).
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import telegram.error
from sqlalchemy.orm import Session
from telegram.ext import AIORateLimiter, ExtBot

from ..db.models import Client, NotificationLog, Project
from ..db.types import utcnow
from .format import build_project_message

_SEND_TRIES = 3
_BACKOFF_BASE = 1.0  # seconds; doubled each retry


class TelegramSender:
    """Owns an ExtBot; one instance per process. Call ``start()`` before sending."""

    def __init__(self, token: str, chat_id: str | int):
        self._token = token
        self._chat_id = chat_id
        self._bot: ExtBot | None = None

    def _get_bot(self) -> ExtBot:
        if self._bot is None:
            self._bot = ExtBot(self._token, rate_limiter=AIORateLimiter(max_retries=3))
        return self._bot

    async def start(self) -> None:
        await self._get_bot().initialize()

    async def aclose(self) -> None:
        if self._bot is not None:
            await self._bot.shutdown()
            self._bot = None

    async def _send(self, text: str, reply_markup=None) -> None:
        """Send one HTML message, retrying transient network failures with exponential backoff.

        ``reply_markup`` (e.g. the project action keyboard) is only passed through when present, so
        the message API surface is unchanged for plain alerts/heartbeats.
        """
        bot = self._get_bot()
        extra = {"reply_markup": reply_markup} if reply_markup is not None else {}
        last_exc: Exception | None = None
        for attempt in range(_SEND_TRIES):
            try:
                await bot.send_message(self._chat_id, text, parse_mode="HTML", **extra)
                return
            except telegram.error.BadRequest:
                # Permanent (malformed HTML / too-long / bad entities). BadRequest subclasses
                # NetworkError, so it MUST be caught first — retrying it can never succeed.
                raise
            except (telegram.error.TimedOut, telegram.error.NetworkError) as exc:
                last_exc = exc
                if attempt < _SEND_TRIES - 1:
                    await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
        assert last_exc is not None
        raise last_exc

    async def send_project_notification(
        self,
        session: Session,
        project: Project,
        client: Client,
        *,
        now_utc: datetime,
        owner_tz: str,
        reply_markup=None,
    ) -> bool:
        """Send a project notification once; return True if newly sent, False if skipped/failed.

        Dedup is keyed on the project's site id, so a project is notified at most once even across
        restarts. On a successful send the log row and ``project.notified`` are committed together.
        """
        dedup_key = f"telegram:project:{project.mostaql_id}"
        existing = (
            session.query(NotificationLog.id)
            .filter(NotificationLog.dedup_key == dedup_key)
            .first()
        )
        if existing is not None:
            return False

        text = build_project_message(project, client, now_utc=now_utc, owner_tz=owner_tz)
        try:
            # Pass reply_markup only when provided so the existing _send stubs/signature are unaffected.
            if reply_markup is not None:
                await self._send(text, reply_markup=reply_markup)
            else:
                await self._send(text)
        except telegram.error.BadRequest:
            # Permanent failure: do NOT masquerade as retryable (would strand the project forever
            # in notified=False / no-log). Propagate so the caller can mark it terminal + alert.
            raise
        except (telegram.error.TimedOut, telegram.error.NetworkError):
            # Transient: leave notified False and write no log row so a later cycle can retry.
            return False

        session.add(
            NotificationLog(
                project_id=project.id,
                sent_at=utcnow(),
                channel="telegram",
                dedup_key=dedup_key,
                tier=project.tier,
                payload={"text": text},
            )
        )
        project.notified = True
        session.commit()
        return True

    async def send_alert(self, text: str) -> None:
        await self._send(text)

    async def send_heartbeat(self, text: str) -> None:
        await self._send(text)
