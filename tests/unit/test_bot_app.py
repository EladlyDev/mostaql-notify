"""Tests for the bot's app builder (``bot/app.py``) and console entrypoint (``bot/__main__.py``).

``is_owner`` is the single owner-gate every handler passes through, so its fail-closed branches
(missing chat, unparsable ``TELEGRAM_CHAT_ID``) are exercised exhaustively. ``build_application``
is asserted to register exactly the expected handler set on a real (offline) PTB ``Application``.
``run()`` is driven both directly and as a ``__main__`` entrypoint with ``build_application`` /
``run_polling`` faked — **no real network or polling is ever started**.
"""
from __future__ import annotations

import runpy
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mostaql_notifier.config import secrets as secrets_mod


@pytest.fixture
def clear_secrets_cache():
    """Reset the ``lru_cache`` on ``get_secrets`` around each test so per-test env wins (and leaks to
    no other test)."""
    secrets_mod.get_secrets.cache_clear()
    yield
    secrets_mod.get_secrets.cache_clear()


# ================================================================================================
# app.is_owner
# ================================================================================================

def test_is_owner_missing_chat_is_false(clear_secrets_cache):
    """No ``effective_chat`` → not the owner (fail closed), without ever reading the chat id."""
    from mostaql_notifier.bot.app import is_owner

    update = SimpleNamespace(effective_chat=None)
    assert is_owner(update) is False


def test_is_owner_matching_chat_is_true(monkeypatch, clear_secrets_cache):
    """A chat id equal to the configured ``TELEGRAM_CHAT_ID`` is the owner."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
    secrets_mod.get_secrets.cache_clear()
    from mostaql_notifier.bot.app import is_owner

    update = SimpleNamespace(effective_chat=SimpleNamespace(id=424242))
    assert is_owner(update) is True


def test_is_owner_non_matching_chat_is_false(monkeypatch, clear_secrets_cache):
    """A different chat id is rejected."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
    secrets_mod.get_secrets.cache_clear()
    from mostaql_notifier.bot.app import is_owner

    update = SimpleNamespace(effective_chat=SimpleNamespace(id=999999))
    assert is_owner(update) is False


def test_is_owner_unparsable_chat_id_is_false(monkeypatch, clear_secrets_cache):
    """A non-numeric ``TELEGRAM_CHAT_ID`` → ``int()`` raises → treated as not the owner (the except)."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "notanint")
    secrets_mod.get_secrets.cache_clear()
    from mostaql_notifier.bot.app import is_owner

    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1))
    assert is_owner(update) is False


# ================================================================================================
# app.build_application
# ================================================================================================

def test_build_application_registers_expected_handlers():
    """The built ``Application`` carries exactly one ``CallbackQueryHandler``, six ``CommandHandler``
    (find/pause/resume/health/stats + Feature-4 top), and one ``MessageHandler``."""
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
    )

    from mostaql_notifier.bot.app import build_application

    application = build_application("123456:TESTTOKEN")
    assert isinstance(application, Application)

    # application.handlers is a dict keyed by group; flatten the lists.
    flat = [h for group in application.handlers.values() for h in group]

    assert sum(isinstance(h, CallbackQueryHandler) for h in flat) == 1
    assert sum(isinstance(h, MessageHandler) for h in flat) == 1

    command_handlers = [h for h in flat if isinstance(h, CommandHandler)]
    assert len(command_handlers) == 6
    registered = set().union(*(h.commands for h in command_handlers))
    assert registered == {"find", "pause", "resume", "health", "stats", "top"}


# ================================================================================================
# __main__.run
# ================================================================================================

def test_run_missing_token_raises_and_never_polls(monkeypatch, clear_secrets_cache):
    """An empty ``TELEGRAM_BOT_TOKEN`` makes ``require_telegram`` fail loud *before* the application is
    built or polling starts."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
    secrets_mod.get_secrets.cache_clear()

    from mostaql_notifier.bot import __main__ as bot_main

    built = []
    monkeypatch.setattr(bot_main, "build_application", lambda *a, **k: built.append(a) or MagicMock())

    with pytest.raises(RuntimeError):
        bot_main.run()

    assert built == []  # build_application never reached


def test_run_builds_and_starts_long_poll(monkeypatch, clear_secrets_cache):
    """The happy path builds the application with the configured token and blocks on
    ``run_polling(allowed_updates=Update.ALL_TYPES)`` — both faked, no network."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
    secrets_mod.get_secrets.cache_clear()

    from telegram import Update

    from mostaql_notifier.bot import __main__ as bot_main

    fake_app = SimpleNamespace(run_polling=MagicMock())
    seen_tokens = []

    def fake_build(token):
        seen_tokens.append(token)
        return fake_app

    monkeypatch.setattr(bot_main, "build_application", fake_build)

    bot_main.run()

    assert seen_tokens == ["123456:TESTTOKEN"]
    fake_app.run_polling.assert_called_once_with(allowed_updates=Update.ALL_TYPES)


def test_run_as_script_entrypoint_invokes_run_polling(monkeypatch, clear_secrets_cache):
    """Executing the module as ``__main__`` (the console-script path) reaches ``run()`` and starts the
    faked long-poll — covers the ``if __name__ == "__main__": run()`` guard end to end."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
    secrets_mod.get_secrets.cache_clear()

    # Patch the source ``build_application`` so the fresh ``from .app import build_application`` in the
    # re-executed module picks up the fake.
    from mostaql_notifier.bot import app as bot_app

    fake_app = SimpleNamespace(run_polling=MagicMock())
    monkeypatch.setattr(bot_app, "build_application", lambda token: fake_app)

    # Drop any cached import so runpy executes the module cleanly as the script entrypoint.
    sys.modules.pop("mostaql_notifier.bot.__main__", None)
    runpy.run_module("mostaql_notifier.bot.__main__", run_name="__main__")

    fake_app.run_polling.assert_called_once()
