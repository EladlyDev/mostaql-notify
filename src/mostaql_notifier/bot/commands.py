"""Owner commands: ``/find /pause /resume /health /stats`` (Feature 3, US4).

``/find`` is read-only search (same predicate as Feature 2's projects list). ``/pause`` · ``/resume``
flip only the shared ``watcher_paused`` settings flag the worker honors on its next cycle — never
mostaql.com (Constitution VIII) — via the exact mechanism ``api/routers/control.py`` uses, and are
idempotent. ``/health`` and ``/stats`` report the shared ``personal/stats.py`` figures, so the bot
and the dashboard show identical numbers.
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import ContextTypes

from ..config.settings_store import SettingsStore, _serialize
from ..db.models import Project, Setting
from ..personal import statuses
from ..personal.stats import compute_health, compute_stats
from .app import is_owner, session_scope

log = logging.getLogger("mostaql.bot")

_PAUSED_KEY = "watcher_paused"
_FIND_LIMIT = 10


def _like_escape(term: str) -> str:
    """Escape LIKE/ILIKE metacharacters so a search term matches literally (mirrors projects.py)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _or_dash(value: object) -> object:
    """Render ``None`` (e.g. no scrape run yet) as an em dash for friendly output."""
    return "—" if value is None else value


def _set_paused(session: Session, value: bool) -> None:
    """Persist the ``watcher_paused`` flag — same settings-row mechanism as routers/control.py."""
    row = session.get(Setting, _PAUSED_KEY)
    if row is not None:
        row.value = _serialize(value, "bool")
        row.value_type = "bool"
    else:
        session.add(Setting(key=_PAUSED_KEY, value=_serialize(value, "bool"), value_type="bool"))
    session.commit()


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/find <keyword>`` — search title/description/skills; reply top matches + Mostaql links."""
    if not is_owner(update):
        return
    message = update.message
    if message is None:
        return
    keyword = " ".join(context.args).strip() if context.args else ""
    if not keyword:
        await message.reply_text("الاستخدام: /find <كلمة>")
        return

    pattern = f"%{_like_escape(keyword)}%"
    with session_scope() as session:
        projects = session.scalars(
            select(Project)
            .where(
                Project.title.ilike(pattern, escape="\\")
                | Project.description.ilike(pattern, escape="\\")
                | sa.cast(Project.skills, sa.String).ilike(pattern, escape="\\")
            )
            .order_by(Project.scraped_at.desc())
            .limit(_FIND_LIMIT)
        ).all()
        lines = [
            f"• {p.title or '(بدون عنوان)'}\n{p.url}".rstrip() if p.url else f"• {p.title or '(بدون عنوان)'}"
            for p in projects
        ]

    if not lines:
        await message.reply_text("لا نتائج")
        return
    await message.reply_text("\n\n".join(lines))


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/pause`` — set ``watcher_paused = true`` (idempotent)."""
    if not is_owner(update):
        return
    message = update.message
    if message is None:
        return
    with session_scope() as session:
        if SettingsStore(session).get_bool(_PAUSED_KEY):
            await message.reply_text("متوقّف مؤقتًا بالفعل")
            return
        _set_paused(session, True)
    await message.reply_text("⏸️ تم الإيقاف المؤقت")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/resume`` — set ``watcher_paused = false`` (idempotent)."""
    if not is_owner(update):
        return
    message = update.message
    if message is None:
        return
    with session_scope() as session:
        if not SettingsStore(session).get_bool(_PAUSED_KEY):
            await message.reply_text("يعمل بالفعل")
            return
        _set_paused(session, False)
    await message.reply_text("▶️ تم الاستئناف")


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/health`` — latest run status + counts, last-successful time, and paused state."""
    if not is_owner(update):
        return
    message = update.message
    if message is None:
        return
    with session_scope() as session:
        h = compute_health(session)
    last = h["last_successful_scrape"]
    last_text = last.isoformat(timespec="minutes") if last is not None else "—"
    lines = [
        "🩺 الصحة",
        f"الحالة: {'⏸️ متوقّف مؤقتًا' if h['paused'] else '✅ يعمل'}",
        f"آخر تشغيل: {_or_dash(h['latest_run_status'])}",
        (
            f"عُثر {_or_dash(h['found_count'])} · جديد {_or_dash(h['new_count'])} · "
            f"محدّث {_or_dash(h['updated_count'])} · أخطاء {_or_dash(h['error_count'])}"
        ),
        f"آخر نجاح: {last_text}",
    ]
    await message.reply_text("\n".join(lines))


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/stats`` — today's found/qualified, totals, and per-stage counts (Arabic labels)."""
    if not is_owner(update):
        return
    message = update.message
    if message is None:
        return
    with session_scope() as session:
        s = compute_stats(session)
        ordered = statuses.list_statuses(session)
    per_stage = s["per_stage"]
    stage_lines = [f"  {st['label']}: {per_stage.get(st['key'], 0)}" for st in ordered]
    lines = [
        "📊 الإحصائيات",
        f"اليوم: عُثر {s['found_today']} · مؤهّل {s['qualified_today']}",
        f"الإجمالي: مشاريع {s['total_projects']} · عملاء {s['total_clients']}",
        f"الحالة: {'⏸️ متوقّف مؤقتًا' if s['paused'] else '✅ يعمل'}",
        "المراحل:",
        *stage_lines,
    ]
    await message.reply_text("\n".join(lines))
