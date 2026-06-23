"""Lifecycle coverage for worker.main.main() without a real scheduler, bot, or network.

The asyncio Event that main() awaits is swapped (only inside the worker.main module namespace) for
one whose ``wait()`` returns immediately, so main() runs its full setup -> start -> shutdown path
and returns. A fake AsyncIOScheduler captures the registered job callables + the job-event listener,
which we then invoke directly to cover the closure bodies (poll logging, heartbeat downtime
self-check, and the fail-loud job-error/missed handler).
"""
from __future__ import annotations

import asyncio
import types
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import mostaql_notifier.worker.main as main_mod
from mostaql_notifier.config.settings_store import app_state_get, app_state_set
from mostaql_notifier.db import models  # noqa: F401  (register tables)
from mostaql_notifier.db.base import Base
from mostaql_notifier.db.types import utcnow

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- fakes


class _FakeEvent:
    def __init__(self):
        self.set_called = False

    def set(self):
        self.set_called = True

    async def wait(self):  # never blocks -> main() proceeds straight to graceful shutdown
        return True


class _FakeScheduler:
    last = None

    def __init__(self, *a, **k):
        self.jobs = {}
        self.listener = None
        self.listener_mask = None
        self.started = False
        self.shutdown_called = False
        _FakeScheduler.last = self

    def add_job(self, func, trigger=None, id=None, **k):
        self.jobs[id] = func

    def add_listener(self, cb, mask):
        self.listener = cb
        self.listener_mask = mask

    def start(self):
        self.started = True

    def shutdown(self, wait=True):
        self.shutdown_called = True


class _FakeSender:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.started = False
        self.closed = False
        self.alerts: list[str] = []
        self.heartbeats: list[str] = []

    async def start(self):
        self.started = True

    async def aclose(self):
        self.closed = True

    async def send_alert(self, text):
        self.alerts.append(text)

    async def send_heartbeat(self, text):
        self.heartbeats.append(text)


class _FakeFetcher:
    def __init__(self, *a, **k):
        self.closed = False

    async def aclose(self):
        self.closed = True


class _FakeRun:
    id = 7
    found_count = 3
    new_count = 1
    updated_count = 0
    error_count = 0
    status = types.SimpleNamespace(value="success")


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Patch every external dependency of main() and return the captured fakes."""
    engine = sa.create_engine(f"sqlite:///{tmp_path}/main.db", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    poll_calls: list[tuple] = []

    async def _fake_poll(session, fetcher, sender, settings):
        poll_calls.append((fetcher, sender))
        return _FakeRun()

    secrets = types.SimpleNamespace(
        telegram_bot_token="tok", telegram_chat_id="chat", database_url="sqlite://"
    )

    fake_fetcher = _FakeFetcher()

    monkeypatch.setattr(main_mod, "get_secrets", lambda: secrets)
    monkeypatch.setattr(main_mod, "upgrade_head", lambda: None)
    monkeypatch.setattr(main_mod, "get_sessionmaker", lambda: Session)
    monkeypatch.setattr(main_mod, "TelegramSender", _FakeSender)
    monkeypatch.setattr(main_mod, "HttpxFetcher", lambda: fake_fetcher)
    monkeypatch.setattr(main_mod, "run_poll_cycle", _fake_poll)
    monkeypatch.setattr(main_mod, "AsyncIOScheduler", _FakeScheduler)
    # Only the Event that main() awaits is swapped (module-local asyncio shim); the real loop helper
    # is preserved so signal-handler registration + create_task keep working.
    monkeypatch.setattr(
        main_mod,
        "asyncio",
        types.SimpleNamespace(Event=_FakeEvent, get_running_loop=asyncio.get_running_loop),
    )
    return types.SimpleNamespace(Session=Session, poll_calls=poll_calls, fetcher=fake_fetcher)


# --------------------------------------------------------------------------- tests


async def test_main_runs_setup_and_graceful_shutdown(wired):
    await main_mod.main()

    sched = _FakeScheduler.last
    assert sched is not None
    assert sched.started is True
    assert sched.shutdown_called is True            # graceful teardown ran (finally)
    assert set(sched.jobs) == {"poll", "heartbeat"}  # both jobs registered
    assert sched.listener is not None                # fail-loud job-event listener attached
    assert wired.fetcher.closed is True              # fetcher closed on shutdown


async def test_main_tolerates_no_signal_handler_support(wired, monkeypatch):
    # Non-POSIX loops raise NotImplementedError from add_signal_handler; main() must swallow it and
    # still complete its setup + shutdown (worker/main.py lines 97-98).
    loop = asyncio.get_running_loop()

    def _no_signals(*a, **k):
        raise NotImplementedError

    monkeypatch.setattr(loop, "add_signal_handler", _no_signals)
    await main_mod.main()
    assert _FakeScheduler.last.shutdown_called is True


async def test_poll_job_runs_a_cycle(wired):
    await main_mod.main()
    poll_job = _FakeScheduler.last.jobs["poll"]

    await poll_job()
    assert len(wired.poll_calls) == 1  # the scheduled job drives one run_poll_cycle


async def test_heartbeat_job_emits_heartbeat_and_no_downtime_alert_when_fresh(wired, monkeypatch):
    created = {}
    real_init = _FakeSender.__init__

    def _spy_init(self, token, chat_id):
        real_init(self, token, chat_id)
        created["sender"] = self

    monkeypatch.setattr(_FakeSender, "__init__", _spy_init)

    await main_mod.main()
    heartbeat_job = _FakeScheduler.last.jobs["heartbeat"]
    sender = created["sender"]

    # A recent successful poll -> heartbeat sent, NO downtime alert.
    with wired.Session() as s:
        app_state_set(s, "last_successful_poll_at", utcnow().isoformat())

    await heartbeat_job()

    assert len(sender.heartbeats) == 1
    assert sender.alerts == []  # fresh poll -> no downtime alert
    with wired.Session() as s:
        assert app_state_get(s, "last_heartbeat_at") is not None


async def test_heartbeat_job_sends_downtime_alert_when_stale(wired, monkeypatch):
    # Capture the sender main() constructs so we can inspect alerts.
    created = {}
    real_init = _FakeSender.__init__

    def _spy_init(self, token, chat_id):
        real_init(self, token, chat_id)
        created["sender"] = self

    monkeypatch.setattr(_FakeSender, "__init__", _spy_init)

    await main_mod.main()
    heartbeat_job = _FakeScheduler.last.jobs["heartbeat"]
    sender = created["sender"]

    # Last successful poll far in the past (> 2x the 120s poll interval) -> downtime alert.
    with wired.Session() as s:
        app_state_set(s, "last_successful_poll_at", (utcnow() - timedelta(seconds=1000)).isoformat())

    await heartbeat_job()

    assert len(sender.heartbeats) == 1
    assert any("No successful poll" in a for a in sender.alerts)


async def test_job_event_listener_alerts_on_error_and_on_missed(wired, monkeypatch):
    created = {}
    real_init = _FakeSender.__init__

    def _spy_init(self, token, chat_id):
        real_init(self, token, chat_id)
        created["sender"] = self

    monkeypatch.setattr(_FakeSender, "__init__", _spy_init)

    await main_mod.main()
    on_event = _FakeScheduler.last.listener
    sender = created["sender"]

    on_event(types.SimpleNamespace(job_id="poll", exception=RuntimeError("boom")))
    on_event(types.SimpleNamespace(job_id="heartbeat", exception=None))
    await asyncio.sleep(0)  # let the create_task alert coroutines run

    assert any("failed" in a for a in sender.alerts)
    assert any("missed" in a for a in sender.alerts)
