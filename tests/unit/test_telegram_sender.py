"""Unit tests for notify.telegram.TelegramSender.

These exercise the lazy-bot lifecycle (start/aclose/reuse), the retry+backoff in ``_send``, and the
single-transaction send/dedup/failure semantics of ``send_project_notification`` — without ever
touching the network. A stub bot (``sender._bot``) records ``send_message`` calls so the real
``_send`` path (and its ``_get_bot`` reuse) is exercised; higher-level tests stub ``sender._send``.

Constitution focus:
  * At-least-once + dedup: a qualifying project is sent exactly once (one NotificationLog row,
    ``notified=True``), never twice (dedup short-circuits), and never silently dropped — a transient
    send failure must leave NO log row and ``notified=False`` so a later cycle can retry.
  * UTC everywhere: any timestamp written must be timezone-aware UTC.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
import telegram.error

from mostaql_notifier.db.models import Client, NotificationLog, Project
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.notify import telegram as tg
from mostaql_notifier.notify.telegram import TelegramSender


# --------------------------------------------------------------------------------------------------
# Stubs / fixtures
# --------------------------------------------------------------------------------------------------
class StubBot:
    """Records send_message calls; optionally raises a queued sequence of exceptions first."""

    def __init__(self, *, raises=None):
        # raises: list of (exc-instance-or-None) consumed per call; None => succeed.
        self._raises = list(raises or [])
        self.calls: list[dict] = []
        self.initialized = 0
        self.shutdowns = 0

    async def send_message(self, chat_id, text, parse_mode=None):
        self.calls.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        if self._raises:
            exc = self._raises.pop(0)
            if exc is not None:
                raise exc
        return {"ok": True}

    async def initialize(self):
        self.initialized += 1

    async def shutdown(self):
        self.shutdowns += 1


def make_sender(*, bot: StubBot | None = None) -> TelegramSender:
    sender = TelegramSender("test-token", "test-chat")
    if bot is not None:
        sender._bot = bot  # type: ignore[assignment]
    return sender


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Zero out backoff sleeps so retry tests are instantaneous & deterministic."""
    slept: list[float] = []

    async def _fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return slept


def _persist_pair(session, *, mostaql_id="9001", tier=1, notified=False):
    now = utcnow()
    client = Client(
        mostaql_id="derived:abc123",
        name="عميل",
        hiring_rate=75.0,
        last_refreshed_at=now,
        first_seen_at=now,
        raw={},
    )
    session.add(client)
    session.flush()
    project = Project(
        mostaql_id=mostaql_id,
        title="تطوير موقع",
        url=f"https://mostaql.com/project/{mostaql_id}",
        category="برمجة",
        budget_min=Decimal("300"),
        budget_max=Decimal("500"),
        currency="USD",
        bids_count=3,
        posted_at=now - timedelta(hours=1),
        scraped_at=now,
        tier=tier,
        notified=notified,
        client_id=client.id,
        raw={},
    )
    session.add(project)
    session.commit()
    return project, client


# --------------------------------------------------------------------------------------------------
# _get_bot / start / aclose lifecycle (lines 34-36, 39, 42-44)
# --------------------------------------------------------------------------------------------------
def test_get_bot_builds_once_and_reuses():
    """First call builds a real ExtBot (no network on construction); subsequent calls reuse it."""
    sender = make_sender()
    assert sender._bot is None
    b1 = sender._get_bot()  # lines 34-35: lazy build
    assert b1 is not None
    b2 = sender._get_bot()  # line 36: reuse, do not rebuild
    assert b1 is b2


async def test_start_initializes_the_bot():
    """start() routes through _get_bot().initialize() (line 39)."""
    bot = StubBot()
    sender = make_sender(bot=bot)
    await sender.start()
    assert bot.initialized == 1
    # The same (already-built) bot was reused, not replaced.
    assert sender._bot is bot


async def test_aclose_shuts_down_and_clears_bot():
    """aclose() shuts the bot down and drops the reference (lines 42-44)."""
    bot = StubBot()
    sender = make_sender(bot=bot)
    await sender.aclose()
    assert bot.shutdowns == 1
    assert sender._bot is None


async def test_aclose_is_noop_when_no_bot():
    """aclose() with no live bot must not blow up (the False branch of line 42)."""
    sender = make_sender()
    assert sender._bot is None
    await sender.aclose()  # should be a quiet no-op
    assert sender._bot is None


# --------------------------------------------------------------------------------------------------
# _send retry / backoff (lines 48-59)
# --------------------------------------------------------------------------------------------------
async def test_send_success_first_try():
    bot = StubBot()
    sender = make_sender(bot=bot)
    await sender._send("hello")
    assert len(bot.calls) == 1
    # parse_mode is always HTML (line 52).
    assert bot.calls[0]["parse_mode"] == "HTML"
    assert bot.calls[0]["chat_id"] == "test-chat"
    assert bot.calls[0]["text"] == "hello"


async def test_send_retries_then_succeeds(_no_sleep):
    """Two transient failures then a success: _send returns after 3 attempts (lines 54-57, 53)."""
    bot = StubBot(raises=[
        telegram.error.TimedOut(),
        telegram.error.NetworkError("boom"),
        None,
    ])
    sender = make_sender(bot=bot)
    await sender._send("retry-me")
    assert len(bot.calls) == 3
    # Exponential backoff with base=1.0 doubled each retry: 1.0 then 2.0 (only between attempts).
    assert _no_sleep == [tg._BACKOFF_BASE * 1, tg._BACKOFF_BASE * 2]


async def test_send_reraises_after_exhausting_tries(_no_sleep):
    """Always failing: re-raises the last exception after _SEND_TRIES (lines 58-59)."""
    last = telegram.error.NetworkError("persistent")
    bot = StubBot(raises=[telegram.error.TimedOut(), telegram.error.TimedOut(), last])
    sender = make_sender(bot=bot)
    with pytest.raises(telegram.error.NetworkError) as ei:
        await sender._send("doomed")
    assert ei.value is last
    assert len(bot.calls) == tg._SEND_TRIES == 3
    # Sleeps only happen between attempts, so one fewer than the number of tries.
    assert len(_no_sleep) == tg._SEND_TRIES - 1


async def test_send_does_not_swallow_non_network_errors(_no_sleep):
    """A permanent error (BadRequest: e.g. bad HTML/too-long) must NOT be retried — it should
    surface on the first attempt with no backoff. In python-telegram-bot, BadRequest is a subclass
    of NetworkError, so the ``except (TimedOut, NetworkError)`` in _send wrongly treats it as
    transient and retries it _SEND_TRIES times before re-raising."""
    bot = StubBot(raises=[telegram.error.BadRequest("nope")])
    sender = make_sender(bot=bot)
    with pytest.raises(telegram.error.BadRequest):
        await sender._send("bad")
    assert len(bot.calls) == 1  # CORRECT: no retry
    assert _no_sleep == []  # CORRECT: no backoff


async def test_send_uses_lazily_built_bot_and_reuses_it(_no_sleep, monkeypatch):
    """Without an injected bot, _send builds the real bot via _get_bot and reuses it across sends."""
    sender = make_sender()
    captured = {"count": 0}

    async def _fake_send_message(self, chat_id, text, parse_mode=None):
        captured["count"] += 1

    # Build the real bot once. ExtBot is frozen at the instance level, so patch the class method.
    real_bot = sender._get_bot()
    monkeypatch.setattr(type(real_bot), "send_message", _fake_send_message)
    await sender._send("a")
    await sender._send("b")
    assert captured["count"] == 2
    assert sender._bot is real_bot  # never rebuilt


# --------------------------------------------------------------------------------------------------
# send_project_notification — success path (one log row, notified True, single commit)
# --------------------------------------------------------------------------------------------------
async def test_notification_success_writes_one_log_and_sets_notified(db_session):
    project, client = _persist_pair(db_session)
    bot = StubBot()
    sender = make_sender(bot=bot)
    now = utcnow()

    ok = await sender.send_project_notification(
        db_session, project, client, now_utc=now, owner_tz="Africa/Cairo"
    )
    assert ok is True
    assert len(bot.calls) == 1
    assert bot.calls[0]["parse_mode"] == "HTML"

    logs = db_session.query(NotificationLog).all()
    assert len(logs) == 1
    row = logs[0]
    assert row.dedup_key == f"telegram:project:{project.mostaql_id}"
    assert row.project_id == project.id
    assert row.channel == "telegram"
    assert row.tier == project.tier
    assert row.payload == {"text": bot.calls[0]["text"]}
    # UTC everywhere: sent_at is aware UTC.
    assert row.sent_at.tzinfo is not None
    assert row.sent_at.utcoffset() == timedelta(0)

    db_session.refresh(project)
    assert project.notified is True


async def test_notification_dedup_key_uses_mostaql_id_not_pk(db_session):
    """The dedup key is keyed on the site id (mostaql_id), guaranteeing once-across-restarts."""
    project, client = _persist_pair(db_session, mostaql_id="55512")
    sender = make_sender(bot=StubBot())
    await sender.send_project_notification(
        db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
    )
    key = db_session.query(NotificationLog.dedup_key).scalar()
    assert key == "telegram:project:55512"
    # And not the integer primary key.
    assert key != f"telegram:project:{project.id}"


# --------------------------------------------------------------------------------------------------
# send_project_notification — dedup short-circuit (line 82)
# --------------------------------------------------------------------------------------------------
async def test_notification_dedup_skips_second_send(db_session):
    """A pre-existing log row with the same dedup key => returns False, no send, count stays 1."""
    project, client = _persist_pair(db_session)
    dedup_key = f"telegram:project:{project.mostaql_id}"
    db_session.add(
        NotificationLog(
            project_id=project.id,
            sent_at=utcnow(),
            channel="telegram",
            dedup_key=dedup_key,
            tier=project.tier,
            payload={"text": "already sent"},
        )
    )
    db_session.commit()

    bot = StubBot()
    sender = make_sender(bot=bot)
    ok = await sender.send_project_notification(
        db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
    )
    assert ok is False  # line 82
    assert bot.calls == []  # never sent
    assert db_session.query(NotificationLog).count() == 1  # no duplicate row


async def test_notification_not_sent_twice_in_a_row(db_session):
    """Calling twice in the same process: second call dedups (real, not pre-seeded, log row)."""
    project, client = _persist_pair(db_session)
    bot = StubBot()
    sender = make_sender(bot=bot)

    first = await sender.send_project_notification(
        db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
    )
    second = await sender.send_project_notification(
        db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
    )
    assert first is True
    assert second is False
    assert len(bot.calls) == 1
    assert db_session.query(NotificationLog).count() == 1


# --------------------------------------------------------------------------------------------------
# send_project_notification — transient failure leaves it retryable (lines 87-89)
# --------------------------------------------------------------------------------------------------
async def test_notification_timeout_leaves_no_log_and_notified_false(db_session, monkeypatch):
    """A transient send failure: returns False, writes NO log row, leaves notified False."""
    project, client = _persist_pair(db_session)
    sender = make_sender(bot=StubBot())

    async def _boom(text):
        raise telegram.error.TimedOut()

    monkeypatch.setattr(sender, "_send", _boom)

    ok = await sender.send_project_notification(
        db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
    )
    assert ok is False  # line 89
    assert db_session.query(NotificationLog).count() == 0  # no log row
    db_session.refresh(project)
    assert project.notified is False  # still retryable
    # And the dedup row is absent, so a later cycle is free to retry.
    assert (
        db_session.query(NotificationLog)
        .filter_by(dedup_key=f"telegram:project:{project.mostaql_id}")
        .first()
        is None
    )


async def test_notification_network_error_also_retryable(db_session, monkeypatch):
    """NetworkError (the sibling transient class) is handled identically (line 87)."""
    project, client = _persist_pair(db_session)
    sender = make_sender(bot=StubBot())

    async def _boom(text):
        raise telegram.error.NetworkError("flaky")

    monkeypatch.setattr(sender, "_send", _boom)

    ok = await sender.send_project_notification(
        db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
    )
    assert ok is False
    assert db_session.query(NotificationLog).count() == 0
    db_session.refresh(project)
    assert project.notified is False


async def test_notification_failure_then_retry_succeeds(db_session, monkeypatch):
    """Failing once then succeeding on a later call yields exactly one delivery (at-least-once)."""
    project, client = _persist_pair(db_session)
    sender = make_sender(bot=StubBot())
    state = {"fail": True}

    async def _maybe(text):
        if state["fail"]:
            raise telegram.error.TimedOut()

    monkeypatch.setattr(sender, "_send", _maybe)

    first = await sender.send_project_notification(
        db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
    )
    assert first is False
    assert db_session.query(NotificationLog).count() == 0

    state["fail"] = False
    second = await sender.send_project_notification(
        db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
    )
    assert second is True
    assert db_session.query(NotificationLog).count() == 1
    db_session.refresh(project)
    assert project.notified is True


async def test_notification_bad_request_should_not_be_treated_as_retryable(db_session, monkeypatch):
    """A BadRequest is a PERMANENT failure (e.g. message too long / bad HTML entity). Treating it as
    retryable strands the project forever in (notified=False, no log): every future cycle re-attempts
    a send that can never succeed. Correct behaviour: a non-transient error must propagate (so the
    caller can mark it eval_error / alert), not be silently swallowed as ``return False``."""
    project, client = _persist_pair(db_session)
    sender = make_sender(bot=StubBot())

    async def _boom(text):
        raise telegram.error.BadRequest("Message is too long")

    monkeypatch.setattr(sender, "_send", _boom)

    with pytest.raises(telegram.error.BadRequest):
        await sender.send_project_notification(
            db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
        )


async def test_notification_non_transient_send_error_propagates(db_session, monkeypatch):
    """A non-transient error from _send is NOT swallowed by the TimedOut/NetworkError handler.

    The except clause only catches transient classes, so e.g. a Forbidden bubbles up to the caller
    (which, in poll.py, increments error_count and skips — the project is not falsely marked sent).
    """
    project, client = _persist_pair(db_session)
    sender = make_sender(bot=StubBot())

    async def _boom(text):
        raise telegram.error.Forbidden("bot blocked")

    monkeypatch.setattr(sender, "_send", _boom)

    with pytest.raises(telegram.error.Forbidden):
        await sender.send_project_notification(
            db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
        )
    # No log row written, notified stays False.
    assert db_session.query(NotificationLog).count() == 0
    db_session.refresh(project)
    assert project.notified is False


# --------------------------------------------------------------------------------------------------
# send_alert (line 106) and send_heartbeat (line 109) both delegate to _send
# --------------------------------------------------------------------------------------------------
async def test_send_alert_delegates_to_send():
    bot = StubBot()
    sender = make_sender(bot=bot)
    await sender.send_alert("alert text")
    assert len(bot.calls) == 1
    assert bot.calls[0]["text"] == "alert text"
    assert bot.calls[0]["parse_mode"] == "HTML"


async def test_send_heartbeat_delegates_to_send():
    bot = StubBot()
    sender = make_sender(bot=bot)
    await sender.send_heartbeat("💚 Heartbeat")  # line 109
    assert len(bot.calls) == 1
    assert bot.calls[0]["text"] == "💚 Heartbeat"
    assert bot.calls[0]["parse_mode"] == "HTML"


async def test_send_alert_retries_on_transient(_no_sleep):
    """Alerts share the same retry path, so a transient failure is not lost."""
    bot = StubBot(raises=[telegram.error.TimedOut(), None])
    sender = make_sender(bot=bot)
    await sender.send_alert("important")
    assert len(bot.calls) == 2


async def test_send_heartbeat_propagates_when_send_exhausted(_no_sleep):
    """If every retry fails, send_heartbeat surfaces the error (callers wrap it; it isn't hidden)."""
    bot = StubBot(raises=[telegram.error.TimedOut()] * tg._SEND_TRIES)
    sender = make_sender(bot=bot)
    with pytest.raises(telegram.error.TimedOut):
        await sender.send_heartbeat("hb")
    assert len(bot.calls) == tg._SEND_TRIES


# --------------------------------------------------------------------------------------------------
# Constitution / at-least-once: failed qualified send is never retried by a later cycle.
# (The poll-cycle agent owns the repro; this asserts the local invariant that the FAILURE path
#  leaves the project in a retryable state. The gap is that poll.py never re-evaluates a
#  `qualified` project, so notified=False qualified projects are stranded — reported in bugs[].)
# --------------------------------------------------------------------------------------------------
async def test_failed_send_state_is_retryable_at_the_sender_level(db_session, monkeypatch):
    """At the sender boundary the contract holds: after a failed send the project is unmarked and
    unlogged. (Whether the *worker* ever re-offers it is a separate, reported gap.)"""
    project, client = _persist_pair(db_session)
    sender = make_sender(bot=StubBot())

    async def _boom(text):
        raise telegram.error.TimedOut()

    monkeypatch.setattr(sender, "_send", _boom)
    await sender.send_project_notification(
        db_session, project, client, now_utc=utcnow(), owner_tz="Africa/Cairo"
    )
    db_session.refresh(project)
    # The only signals a later cycle could key off of:
    assert project.notified is False
    assert (
        db_session.query(NotificationLog)
        .filter_by(dedup_key=f"telegram:project:{project.mostaql_id}")
        .count()
        == 0
    )
