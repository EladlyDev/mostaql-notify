"""Config-driven personal status set (Feature 3, research §2).

The status set is a single ``settings`` row ``personal_statuses`` — an **ordered** list of
``{"key": <slug>, "label": <Arabic display>}``. Conventions enforced here so the automation rules
(FR-005, FR-019) stay declarative:

* the **first entry's key is the default** (a project with no record is treated as this status);
* the reserved key ``applied`` is the stage that triggers the applied-date rule;
* the board renders columns in list order;
* a stored status whose key is no longer configured is shown via a clearly-labelled **fallback**
  (never erased — constitution IV).

Keys are stable identifiers persisted on records; labels are Arabic-first, relabel-able without a
migration (constitution III/V).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config.settings_store import SettingsStore

#: The reserved slug whose first entry stamps ``applied_at`` (FR-005).
APPLIED_KEY = "applied"

#: Last-resort default if the configured list is ever empty/malformed.
_FALLBACK_DEFAULT = "new"


def _load(session: Session) -> list[dict]:
    """The configured ordered ``[{key,label}]`` list (defensive against a malformed row)."""
    raw = SettingsStore(session).get_json("personal_statuses")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict) and "key" in item:
            out.append({"key": str(item["key"]), "label": str(item.get("label", item["key"]))})
    return out


def list_statuses(session: Session) -> list[dict]:
    """The configured ordered ``[{key,label}]`` list (board column order, feed filter options)."""
    return _load(session)


def default_status(session: Session) -> str:
    """The default slug — the first configured entry (FR-019). Falls back to ``"new"``."""
    statuses = _load(session)
    return statuses[0]["key"] if statuses else _FALLBACK_DEFAULT


def valid_keys(session: Session) -> set[str]:
    """The set of currently-configured status slugs."""
    return {s["key"] for s in _load(session)}


def is_valid(session: Session, key: str) -> bool:
    """True iff ``key`` is a currently-configured status slug (settable)."""
    return key in valid_keys(session)


def label_for(session: Session, key: str) -> str:
    """The Arabic display label for a slug; returns the slug itself if it was removed from config
    (the fallback path — keeps a stale record readable rather than erasing it)."""
    for s in _load(session):
        if s["key"] == key:
            return s["label"]
    return key
