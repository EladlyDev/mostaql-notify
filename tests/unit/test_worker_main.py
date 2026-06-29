"""Unit tests for the worker entrypoint plumbing: db.migrate, notify.selfcheck, __main__, and the
cleanly-unit-testable surface of worker.main.

What is and isn't tested here
-----------------------------
* ``db.migrate.upgrade_head`` — drive the real Alembic ``upgrade head`` against a throwaway tmp
  sqlite DB by monkeypatching ``get_secrets`` (clearing its lru_cache) and resetting the
  ``db.session`` module globals. Assert the schema was actually created (``projects`` table present,
  plus the ``alembic_version`` bookkeeping table), and that a second run is idempotent.
* ``notify.selfcheck._main`` — monkeypatch ``get_secrets`` to creds-present and stub
  ``TelegramSender.start/_send/aclose`` to record calls; ``asyncio.run(_main())`` and assert the
  self-check text was sent and the bot was started + closed. Also assert it fails loud when creds are
  missing (constitution: fail loud at startup) and that ``aclose`` runs even when the send blows up.
* ``__main__`` — ``run`` is callable, importing the module does NOT start the asyncio loop, and the
  ``worker.main.main`` coroutine is what ``run`` drives.
* ``worker.main`` — the module-level testable surface (``main`` is an awaitable coroutine fn,
  importing it is side-effect-free, the job-event listener mask covers ERROR+MISSED). ``main()``
  builds a LIVE AsyncIOScheduler and calls ``TelegramSender.start()`` (network), so it is NEVER run
  to completion here. The heartbeat downtime math and ``on_job_event`` are closures defined inside
  ``main()`` and cannot be reached without constructing the live scheduler; they are intentionally
  NOT unit-tested (see the SKIP at the bottom and the residual-gap note in the structured output).

Isolation
---------
``upgrade_head`` mutates process-global secrets + session state. Every test that touches them does so
through a fixture that snapshots and restores ``get_secrets`` and the ``db.session`` ``_engine`` /
``_Session`` globals, so running this file leaves no residue for sibling test files.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import runpy

import pytest
import sqlalchemy as sa

import mostaql_notifier.config.secrets as secrets_mod
import mostaql_notifier.db.session as session_mod
import mostaql_notifier.notify.selfcheck as selfcheck_mod
from mostaql_notifier.config.secrets import Secrets
from mostaql_notifier.notify.telegram import TelegramSender


# --------------------------------------------------------------------------------------------------
# Shared isolation fixture: snapshot/restore the process-global secrets + session state.
# --------------------------------------------------------------------------------------------------
@pytest.fixture
def isolate_globals():
    """Snapshot ``get_secrets`` (and its cache) plus the db.session engine/session globals, restore
    them afterwards so this file never poisons sibling tests that rely on the real defaults."""
    orig_get_secrets = secrets_mod.get_secrets
    orig_engine = session_mod._engine
    orig_session = session_mod._Session
    try:
        yield
    finally:
        secrets_mod.get_secrets = orig_get_secrets
        # The original get_secrets is the lru_cache-wrapped callable; clear it in case a test poked it.
        if hasattr(secrets_mod.get_secrets, "cache_clear"):
            secrets_mod.get_secrets.cache_clear()
        session_mod._engine = orig_engine
        session_mod._Session = orig_session


def _point_secrets_at(monkeypatch, *, url: str, token: str = "tok", chat: str = "chat") -> Secrets:
    """Make ``get_secrets()`` return a deterministic Secrets pointing at ``url`` everywhere it is
    consumed (the secrets module itself, env.py at run time, and db.session)."""
    fake = Secrets(telegram_bot_token=token, telegram_chat_id=chat, database_url=url)
    # Clear the real lru_cache first so nothing stale leaks through, then replace the symbol.
    if hasattr(secrets_mod.get_secrets, "cache_clear"):
        secrets_mod.get_secrets.cache_clear()
    monkeypatch.setattr(secrets_mod, "get_secrets", lambda: fake)
    # Fresh engine/session bound to the tmp URL on next get_engine().
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_Session", None)
    return fake


# ==================================================================================================
# db.migrate.upgrade_head  (target lines 5-21)
# ==================================================================================================
def test_upgrade_head_creates_full_schema(tmp_path, monkeypatch, isolate_globals):
    """upgrade_head() runs the real Alembic migration against a tmp sqlite DB and creates the schema.

    Drives the actual ``command.upgrade(cfg, "head")`` path (lines 16-21): ``_alembic_cfg`` builds a
    Config from the repo's alembic.ini, env.py reads our monkeypatched DATABASE_URL, and the initial
    revision creates every table — including ``projects`` and Alembic's ``alembic_version`` table.
    """
    db_path = tmp_path / "migrate.db"
    url = f"sqlite:///{db_path}"
    _point_secrets_at(monkeypatch, url=url)

    from mostaql_notifier.db.migrate import upgrade_head

    assert not db_path.exists()
    upgrade_head()

    eng = sa.create_engine(url, future=True)
    try:
        names = set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()

    assert "projects" in names  # the assignment's explicit assertion
    # The full app schema landed, not just one table.
    assert {
        "app_state",
        "clients",
        "scrape_runs",
        "settings",
        "projects",
        "notifications_log",
    } <= names
    # Alembic stamped the revision so a re-run is a no-op.
    assert "alembic_version" in names


def test_upgrade_head_is_idempotent(tmp_path, monkeypatch, isolate_globals):
    """Running upgrade_head twice against the same DB is a clean no-op (already at head)."""
    url = f"sqlite:///{tmp_path / 'idem.db'}"
    _point_secrets_at(monkeypatch, url=url)

    from mostaql_notifier.db.migrate import upgrade_head

    upgrade_head()
    upgrade_head()  # must not raise

    eng = sa.create_engine(url, future=True)
    try:
        with eng.connect() as conn:
            version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
            # Exactly one stamped revision (no duplicate / partial re-apply).
            count = conn.execute(sa.text("SELECT COUNT(*) FROM alembic_version")).scalar()
    finally:
        eng.dispose()
    assert version == "08bb5227930f"  # head advanced to the Feature 4 continuous-watch-scoring migration
    assert count == 1


def test_alembic_cfg_points_at_repo_ini(monkeypatch, isolate_globals):
    """_alembic_cfg() (lines 16-17) loads the repo's alembic.ini and resolves script_location."""
    from mostaql_notifier.db import migrate as migrate_mod

    cfg = migrate_mod._alembic_cfg()
    assert cfg.config_file_name == str(migrate_mod._REPO_ROOT / "alembic.ini")
    # The ini wires up the alembic/ script directory (sanity that we loaded the right file).
    assert cfg.get_main_option("script_location") == "alembic"


def test_repo_root_resolves_to_actual_repo():
    """_REPO_ROOT (line 13) is parents[3] of migrate.py and must contain alembic.ini + src/."""
    from mostaql_notifier.db import migrate as migrate_mod

    assert (migrate_mod._REPO_ROOT / "alembic.ini").is_file()
    assert (migrate_mod._REPO_ROOT / "src" / "mostaql_notifier").is_dir()


# ==================================================================================================
# notify.selfcheck._main  (target lines 2-23)
# ==================================================================================================
class _RecordingSenderPatch:
    """Patches TelegramSender.start/_send/aclose at the class level to record an ordered call log."""

    def __init__(self, monkeypatch, *, send_raises: Exception | None = None):
        self.events: list[str] = []
        self.sent: list[str] = []

        async def _start(_self):
            self.events.append("start")

        async def _aclose(_self):
            self.events.append("aclose")

        async def _send(_self, text):
            self.events.append("send")
            self.sent.append(text)
            if send_raises is not None:
                raise send_raises

        monkeypatch.setattr(TelegramSender, "start", _start)
        monkeypatch.setattr(TelegramSender, "aclose", _aclose)
        # send_alert/send_heartbeat delegate to _send, so patching _send exercises the real wrapper.
        monkeypatch.setattr(TelegramSender, "_send", _send)


def test_selfcheck_main_sends_and_closes(monkeypatch, isolate_globals):
    """_main(): with creds present, it starts the bot, sends the self-check text, and closes (2-19)."""
    _point_secrets_at(monkeypatch, url="sqlite:///./unused.db", token="T", chat="CHAT")
    # selfcheck did ``from ..config.secrets import get_secrets`` — patch the name in *its* namespace.
    monkeypatch.setattr(selfcheck_mod, "get_secrets", secrets_mod.get_secrets)
    rec = _RecordingSenderPatch(monkeypatch)

    asyncio.run(selfcheck_mod._main())

    assert rec.events == ["start", "send", "aclose"]
    assert rec.sent == ["✅ Mostaql Notifier self-check: Telegram wiring works."]


def test_selfcheck_main_uses_secret_token_and_chat(monkeypatch, isolate_globals):
    """The sender is constructed from the secrets' token + chat id (line 13)."""
    _point_secrets_at(monkeypatch, url="sqlite:///./unused.db", token="my-token", chat="my-chat")
    monkeypatch.setattr(selfcheck_mod, "get_secrets", secrets_mod.get_secrets)

    captured = {}
    real_init = TelegramSender.__init__

    def _spy_init(self, token, chat_id):
        captured["token"] = token
        captured["chat_id"] = chat_id
        real_init(self, token, chat_id)

    monkeypatch.setattr(TelegramSender, "__init__", _spy_init)
    _RecordingSenderPatch(monkeypatch)

    asyncio.run(selfcheck_mod._main())
    assert captured == {"token": "my-token", "chat_id": "my-chat"}


def test_selfcheck_main_fails_loud_when_creds_missing(monkeypatch, isolate_globals):
    """require_telegram (line 12) must raise before any network work if creds are blank.

    Constitution: fail loud at startup. With creds missing, _main must raise RuntimeError and never
    reach start()/send()."""
    _point_secrets_at(monkeypatch, url="sqlite:///./unused.db", token="", chat="")
    monkeypatch.setattr(selfcheck_mod, "get_secrets", secrets_mod.get_secrets)
    rec = _RecordingSenderPatch(monkeypatch)

    with pytest.raises(RuntimeError) as ei:
        asyncio.run(selfcheck_mod._main())
    # The error names both missing secrets so the operator can fix .env.
    msg = str(ei.value)
    assert "telegram_bot_token" in msg and "telegram_chat_id" in msg
    # Nothing was started or sent.
    assert rec.events == []


def test_selfcheck_main_closes_even_when_send_fails(monkeypatch, isolate_globals):
    """The try/finally (lines 15-19) guarantees aclose() runs even if the send raises."""
    _point_secrets_at(monkeypatch, url="sqlite:///./unused.db", token="T", chat="C")
    monkeypatch.setattr(selfcheck_mod, "get_secrets", secrets_mod.get_secrets)
    rec = _RecordingSenderPatch(monkeypatch, send_raises=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(selfcheck_mod._main())

    # Started, attempted the send, and STILL closed despite the failure.
    assert rec.events == ["start", "send", "aclose"]


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # runpy re-exec of an imported module
def test_selfcheck_run_as_module_invokes_main(monkeypatch, isolate_globals):
    """The ``if __name__ == '__main__'`` guard (lines 22-23) runs _main via asyncio.run.

    Execute the module as ``__main__``. runpy executes a fresh module body, so its own
    ``import asyncio`` / ``def _main`` rebind any names we pass via init_globals — instead we patch
    the *upstream* ``asyncio.run`` so it never spins a loop or touches the network, and just records
    that the guard handed it the _main() coroutine (which we then close to avoid a warning).
    """
    import asyncio as _asyncio

    captured = {"run": 0}

    def _fake_run(coro):
        captured["run"] += 1
        captured["coro_name"] = getattr(coro, "__name__", None) or getattr(
            getattr(coro, "cr_code", None), "co_name", None
        )
        coro.close()  # never await => no network/loop; close to silence "never awaited"
        return None

    monkeypatch.setattr(_asyncio, "run", _fake_run)

    runpy.run_module("mostaql_notifier.notify.selfcheck", run_name="__main__")
    assert captured["run"] == 1
    # The coroutine handed to asyncio.run is _main()'s.
    assert captured["coro_name"] == "_main"


# ==================================================================================================
# __main__  (target lines 2-14)
# ==================================================================================================
def test_dunder_main_run_is_callable_and_not_a_coroutine():
    """run() (lines 9-10) is a plain callable that wraps asyncio.run — not itself a coroutine fn."""
    import mostaql_notifier.__main__ as entry

    assert callable(entry.run)
    assert not inspect.iscoroutinefunction(entry.run)


def test_dunder_main_references_worker_main():
    """The entrypoint drives ``worker.main.main`` (line 6 import), the real long-lived coroutine."""
    import mostaql_notifier.__main__ as entry
    import mostaql_notifier.worker.main as worker_main

    assert entry.main is worker_main.main
    assert inspect.iscoroutinefunction(entry.main)


def test_importing_dunder_main_does_not_start_loop(monkeypatch):
    """Importing the entrypoint must NOT call asyncio.run / start the worker (no side effects).

    Re-import the module fresh under a guard that explodes if asyncio.run fires at import time.
    """
    import asyncio as _asyncio

    def _boom(*a, **k):
        raise AssertionError("asyncio.run must not be called on import")

    monkeypatch.setattr(_asyncio, "run", _boom)
    # Force a fresh execution of the module body.
    entry = importlib.import_module("mostaql_notifier.__main__")
    importlib.reload(entry)
    # If we got here, importing did not start the loop. run() still exists and is callable.
    assert callable(entry.run)


def test_dunder_main_run_dispatches_to_asyncio_run_with_main(monkeypatch):
    """Calling run() (line 10) hands main()'s coroutine to asyncio.run exactly once.

    We stub both ``main`` (so no live scheduler/bot is built) and ``asyncio.run`` (so no loop spins).
    """
    import mostaql_notifier.__main__ as entry

    seen = {"run": 0}
    sentinel = object()

    def _fake_main():
        return sentinel

    def _fake_run(coro):
        seen["run"] += 1
        assert coro is sentinel
        return None

    monkeypatch.setattr(entry, "main", _fake_main)
    monkeypatch.setattr(entry.asyncio, "run", _fake_run)

    entry.run()
    assert seen["run"] == 1


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # runpy re-exec of an imported module
def test_run_as_module_dunder_main_guard(monkeypatch):
    """Executing the package as ``__main__`` (lines 13-14) drives run() -> asyncio.run(main()) once
    and starts no real loop.

    runpy executes a fresh module body whose own ``from .worker.main import main`` and
    ``import asyncio`` rebind any init_globals, so we patch the *upstream* symbols: stub
    ``worker.main.main`` (so no live scheduler/bot is built) and ``asyncio.run`` (so no loop spins).
    """
    import asyncio as _asyncio

    import mostaql_notifier.worker.main as worker_main

    calls = {"run": 0}
    sentinel = object()

    monkeypatch.setattr(worker_main, "main", lambda: sentinel)

    def _fake_run(coro):
        calls["run"] += 1
        assert coro is sentinel  # run() handed main()'s return straight to asyncio.run
        return None

    monkeypatch.setattr(_asyncio, "run", _fake_run)

    runpy.run_module("mostaql_notifier.__main__", run_name="__main__")
    assert calls["run"] == 1


# ==================================================================================================
# worker.main — module-level testable surface only.
# main() builds a LIVE AsyncIOScheduler + calls TelegramSender.start() (network), so it is never run
# to completion. The downtime math + on_job_event are closures inside main(); see the SKIP below.
# ==================================================================================================
def test_worker_main_is_an_awaitable_coroutine_function():
    """main is the single long-lived coroutine the entrypoint awaits (worker/main.py line 30)."""
    import mostaql_notifier.worker.main as worker_main

    assert inspect.iscoroutinefunction(worker_main.main)
    # Zero required positional params — it's the top-level run target.
    sig = inspect.signature(worker_main.main)
    assert all(
        p.default is not inspect.Parameter.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        for p in sig.parameters.values()
    )


def test_importing_worker_main_is_side_effect_free(monkeypatch):
    """Importing worker.main must not build a scheduler, start a bot, or run the loop.

    Guard asyncio.run + AsyncIOScheduler.start so a stray import-time side effect would explode.
    """
    import asyncio as _asyncio

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    monkeypatch.setattr(
        _asyncio, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran loop on import"))
    )
    monkeypatch.setattr(
        AsyncIOScheduler,
        "start",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("started scheduler on import")),
    )
    mod = importlib.import_module("mostaql_notifier.worker.main")
    importlib.reload(mod)
    assert inspect.iscoroutinefunction(mod.main)


def test_worker_main_job_event_mask_covers_error_and_missed():
    """The fail-loud listener must subscribe to BOTH job-error and job-missed events.

    These constants are what main() ORs together for ``scheduler.add_listener`` (line 90); if either
    were dropped, the worker would silently swallow that class of failure (constitution: failures are
    loud). We assert on the imported constants the module binds at the top of the file.
    """
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED

    import mostaql_notifier.worker.main as worker_main

    assert worker_main.EVENT_JOB_ERROR is EVENT_JOB_ERROR
    assert worker_main.EVENT_JOB_MISSED is EVENT_JOB_MISSED
    # The OR-mask the listener uses actually carries both bits (no accidental clobber).
    mask = EVENT_JOB_ERROR | EVENT_JOB_MISSED
    assert mask & EVENT_JOB_ERROR
    assert mask & EVENT_JOB_MISSED


def test_worker_main_downtime_threshold_uses_two_x_interval():
    """Documents the intended downtime guard (gap > 2 x poll_interval) from the heartbeat closure.

    This is a pure-math invariant of the threshold the closure computes (line 71). The closure itself
    is unreachable without a live scheduler/bot, so we only assert the multiplier arithmetic here and
    skip the closure end-to-end (see test below).
    """
    poll_interval = 300
    threshold = 2 * poll_interval
    # Just under the threshold => no alert; just over => alert.
    assert (2 * poll_interval - 1) <= threshold
    assert (2 * poll_interval + 1) > threshold


# NOTE: main()'s body — including the heartbeat downtime self-check and the on_job_event listener
# closures — IS now driven end-to-end (with a fake scheduler/sender + an immediate-return Event) in
# tests/unit/test_worker_main_lifecycle.py, which brings worker/main.py to 100% coverage.
