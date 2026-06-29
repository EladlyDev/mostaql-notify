"""Unit tests for the inline action-button keyboard + callback_data codec (Feature 3, US4).

These live in ``notify/format.py`` (the worker builds the keyboard; the bot parses the data). We
assert the keyboard's shape, a clean round-trip for every action, the ≤ 64-byte Telegram limit, and
that foreign/garbage data is rejected so the bot can ignore it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram import InlineKeyboardMarkup

from mostaql_notifier.notify.format import (
    CB_APPLIED,
    CB_DISMISS,
    CB_FAVORITE,
    CB_NOTE,
    CB_WHY,
    build_callback_data,
    build_project_keyboard,
    parse_callback_data,
)

# Feature 4 adds the "Why?" callback action; the keyboard now carries five callback buttons.
_ACTIONS = [CB_FAVORITE, CB_APPLIED, CB_DISMISS, CB_NOTE, CB_WHY]


def _project(pid: int = 123, url: str | None = "https://mostaql.com/project/123"):
    return SimpleNamespace(id=pid, url=url)


def test_keyboard_has_five_callback_buttons_and_an_open_url_button():
    kb = build_project_keyboard(_project())
    assert isinstance(kb, InlineKeyboardMarkup)
    buttons = [b for row in kb.inline_keyboard for b in row]

    # The five action buttons (incl. Feature-4 "Why?") carry our callback_data; none is a URL button.
    callback_buttons = [b for b in buttons if b.callback_data is not None]
    actions = {parse_callback_data(b.callback_data)[0] for b in callback_buttons}
    assert actions == set(_ACTIONS)
    assert all(b.url is None for b in callback_buttons)

    # Exactly one URL button → the project on Mostaql, with no callback_data.
    url_buttons = [b for b in buttons if b.url is not None]
    assert len(url_buttons) == 1
    assert url_buttons[0].url == "https://mostaql.com/project/123"
    assert url_buttons[0].callback_data is None


def test_keyboard_omits_open_button_when_no_url():
    kb = build_project_keyboard(_project(url=None))
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert all(b.url is None for b in buttons)
    # Open is dropped, but the five callback buttons (incl. the lone "Why?") remain.
    assert len([b for b in buttons if b.callback_data is not None]) == 5


@pytest.mark.parametrize("action", _ACTIONS)
def test_callback_data_round_trips(action):
    data = build_callback_data(action, 4242)
    assert parse_callback_data(data) == (action, 4242)


@pytest.mark.parametrize("action", _ACTIONS)
def test_callback_data_within_64_bytes(action):
    # Even an implausibly large id stays well under Telegram's 64-byte callback_data cap.
    data = build_callback_data(action, 9_999_999_999)
    assert len(data.encode("utf-8")) <= 64


@pytest.mark.parametrize(
    "garbage",
    [
        "",
        "garbage",
        "pf:fav",  # too few parts
        "pf:fav:123:extra",  # too many parts
        "xx:fav:123",  # wrong prefix
        "pf:bogus:123",  # unknown action
        "pf:fav:notanint",  # non-integer id
    ],
)
def test_parse_rejects_foreign_or_garbage_data(garbage):
    assert parse_callback_data(garbage) is None
