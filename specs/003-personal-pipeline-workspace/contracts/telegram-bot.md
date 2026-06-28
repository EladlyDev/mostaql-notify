# Contract: Inbound Telegram Bot (Part D)

The second interface this feature exposes, alongside the HTTP API. A **separate long-polling process**
(`mostaql-notifier-bot`) consumes Telegram updates via `getUpdates` and acts on the **same personal record**
as the dashboard by calling `personal/service.py`. There is no webhook and no inbound port (Constitution IX/X).

## Authorization (Constitution I & IX)

- Every update (callback query, command, message) is handled **only** when
  `update.effective_chat.id == int(TELEGRAM_CHAT_ID)` (the existing secret). All other chats are **silently
  ignored** — no reply, no action. The bot serves exactly one owner.

## Outbound notification keyboard (sent by the worker)

Each qualifying project notification (built in `notify/format.py`, sent by `notify/telegram.py`) carries an
inline keyboard:

```
[ ⭐ مفضّل (Favorite) ]   [ ✅ تقدّمت (Applied) ]
[ 🙈 إخفاء (Dismiss) ]    [ 📝 ملاحظة (Add note) ]
[ 🔗 فتح على مستقل (Open) ]
```

- The first four are **callback buttons**; **Open** is a Telegram **URL button** → `project.url` (no callback,
  no state change).
- `callback_data` format (≤ 64 bytes): **`pf:{action}:{project_id}`**, `action ∈ {fav, app, dis, note}`,
  `project_id` = the integer DB primary key. Examples: `pf:fav:123`, `pf:app:123`, `pf:dis:123`, `pf:note:123`.

## Callback actions

| Button | `action` | Effect (via `personal/service.py`, lazily creating the record) | Confirmation |
|---|---|---|---|
| Favorite | `fav` | `toggle_favorite(project_id)` | Edit message / answer: "★ مفضّل" or "☆ أُزيل من المفضّلة" |
| Applied | `app` | `set_status(project_id, "applied")` → sets `applied_at` if unset (FR-005) | "✅ سُجّل التقديم" (or "سبق التسجيل") |
| Dismiss | `dis` | `hide(project_id)` | "🙈 تم الإخفاء" |
| Add note | `note` | start the **add-note conversation** (below) | force-reply prompt |
| Open | — | URL button to `project.url`; no callback | — |

**Idempotency & old messages (FR-026, SC-008)**: every callback resolves the project by id and applies the
service mutation; Favorite toggles, Applied/Dismiss are no-ops once already in that state. A second tap, or a
tap on an old/expired notification, converges to the same state and answers harmlessly; if the project no
longer exists the bot answers "المشروع غير موجود" without error. After acting, the handler **answers the
callback query** (removes the Telegram spinner) and edits the message to reflect the new state.

## Add-note conversation

1. On `pf:note:{id}`, the bot replies with a `ForceReply` prompt ("✏️ اكتب ملاحظتك للمشروع") and records the
   pending target for this chat (per-chat pending project id; survives restart via `app_state`, or a
   `ConversationHandler` state).
2. The owner's next message text is **appended** to that project's `notes` via `service.set_notes(...)`
   (append, never overwrite — non-destructive), and the bot confirms "📝 حُفظت الملاحظة".
3. A non-text reply or a cancel clears the pending state gracefully.

## Commands

| Command | Behavior | Reads/Writes |
|---|---|---|
| `/find <keyword>` | Search the owner's projects (title/description/skills, like Feature 2's search), reply with the top N matches and their Mostaql links (friendly "لا نتائج" when none). | read-only |
| `/pause` | Set `watcher_paused = true`. Idempotent ("متوقّف مؤقتًا بالفعل" if already paused). | writes `settings.watcher_paused` |
| `/resume` | Set `watcher_paused = false`. Idempotent. | writes `settings.watcher_paused` |
| `/health` | Reply with the latest scrape run's **status + found/new/updated/error counts**, the last-successful-scrape time, **and the paused state** (so an intentional idle is distinguishable from a fault — Constitution VI). | read-only |
| `/stats` | Reply with **found today**, **qualified today**, **total projects/clients**, and **count of projects in each pipeline stage** (per configured status). | read-only |

`/pause` and `/resume` write only the shared `watcher_paused` flag that the worker honors on its next cycle;
neither the bot nor the dashboard performs any scrape or any write to mostaql.com (Constitution VIII).

## Consistency with the dashboard (FR-029, SC-001)

All callback/command mutations go through the same `personal/service.py` and `settings` rows the FastAPI
routers use, so an action taken in Telegram is reflected on the dashboard's single record on its next refresh,
and vice-versa. There is never more than one personal record per project (PK = `project_id`).

## Process & lifecycle

- Entrypoint: `mostaql-notifier-bot` (`src/mostaql_notifier/bot/__main__.py:run`), an `asyncio` long-poll
  `Application` (python-telegram-bot v21). Single `getUpdates` consumer for the token (the worker only sends).
- Obtains DB sessions via `get_sessionmaker()`; reads `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` from `Secrets`.
- Supervised like the worker (compose `restart: unless-stopped` / systemd `Restart=always`); failures are
  logged and the process is restarted (Constitution VI).
