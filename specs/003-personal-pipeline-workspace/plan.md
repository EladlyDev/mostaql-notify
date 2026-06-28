# Implementation Plan: Personal Pipeline and Workspace

**Branch**: `003-personal-pipeline-workspace` | **Date**: 2026-06-25 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-personal-pipeline-workspace/spec.md`

## Summary

The owner's **personal layer** on top of Features 1 (watcher) and 2 (read-only dashboard) — the first feature
that writes the owner's own project data. It adds: (A) a CRM core (favorite, personal status, tags, applied
date, won/lost outcomes, hide) surfaced as feed quick-actions and detail controls; (B) a per-project
workspace (markdown notes + validated PDF/DOCX/MD uploads with preview/download); (C) a drag-and-drop Kanban
board over the engaged projects; and (D) Telegram quick-action buttons on each notification plus the bot
commands `/find /pause /resume /health /stats`.

**Technical approach** (extends Feature 2's stack with zero schema drift): two **new SQLite tables**
(`personal_records` 1:1 with `projects` via a shared PK/FK, and `attachments` many-per-project) added by a
single **Alembic** migration; the existing models/session remain the single source of truth. A small,
**surface-agnostic personal-layer service** (`src/mostaql_notifier/personal/`) implements every mutation
(lazy get-or-create, favorite/status/tags/applied/outcome/hide/notes/reorder) so the **dashboard API** and a
**new inbound Telegram bot** converge on exactly one record per project (FR-029). New **FastAPI routers**
(personal, board, attachments, control) reuse Feature 2's auth gate, session dependency, and house style;
the projects feed and Home gain personal fields/filters and a paused indicator. File uploads are validated
(type + magic-bytes + size), stored under a configurable `attachments_dir` **outside any web path** with
UUID storage names, and streamed only through gated endpoints (Constitution IX). The **inbound bot** is a
**separate long-polling process** (`mostaql-notifier-bot`, reusing `python-telegram-bot`) that coordinates
with the worker purely through the DB (`watcher_paused` settings flag) — no webhook, no public port. The
**Next.js frontend** adds a Board page, feed quick-actions, and a detail-page workspace, pulling in
`@dnd-kit` (Kanban) and `react-markdown`+`rehype-sanitize` (notes), plus four Base-UI primitives
(dropdown-menu, dialog, textarea, tabs). Every new tunable (status set + labels, allowed types, max size,
storage path, pause flag) is config-driven (Constitution III); no personal data is ever deleted by
automation (Constitution IV).

## Technical Context

**Language/Version**: Python 3.11+ (backend + worker + bot, one venv/package); TypeScript / Node 20+ (frontend)  
**Primary Dependencies**: Backend — FastAPI + Uvicorn, SQLAlchemy 2 (existing models/session), Alembic, pydantic-settings, **python-telegram-bot[rate-limiter] v21 (already present; now also used inbound)**, **python-multipart (NEW — uploads)**, itsdangerous/passlib (existing auth). Frontend — Next.js 16, React 19, Tailwind v4, Base UI (`@base-ui/react`), TanStack Query, lucide; **NEW: `@dnd-kit/core`+`/sortable`+`/utilities` (Kanban), `react-markdown`+`remark-gfm`+`rehype-sanitize` (notes render/sanitize)**.  
**Storage**: Existing SQLite (`sqlite:///./data/mostaql.db`, WAL) — **two new tables added via Alembic**, existing tables read-only to this feature except the new ones + additive `settings` rows. Uploaded files on the filesystem under a configurable **`attachments_dir`** (default `./data/attachments`), inside the backed-up `./data` volume, outside any public web path.  
**Testing**: Backend — pytest + FastAPI `TestClient` (reuse `tests/api/conftest.py` `api_env` + row factories; add `make_personal_record`/`make_attachment`); unit tests for the personal service, status config, stats, the Telegram keyboard/callback codec, and the inbound-bot handlers (owner-chat authz, idempotency, conversation). Frontend — Vitest + Testing Library (board reducer, markdown sanitize, row-menu, upload validation messaging).  
**Target Platform**: Localhost (laptop/phone on LAN); portable to a single always-on VPS via redeploy (Constitution X).  
**Project Type**: Web application (FastAPI API + Next.js SPA) over an existing async worker package, **plus a new long-polling Telegram bot process** — four cooperating processes (worker, bot, api, frontend) sharing one SQLite file (WAL).  
**Performance Goals**: Feed/board interactions feel instant on the personal dataset (board renders the engaged subset, typically ≤ low-hundreds of cards); a quick action (favorite/status/hide) and a board move round-trip with no perceptible lag; an upload of a ≤10 MB file validates+stores in ≤ ~2 s; a Telegram button tap confirms within a couple of seconds (one Bot-API round-trip).  
**Constraints**: Non-destructive — automation NEVER deletes/overwrites personal data (IV); uploads validated by type+magic+size, stored non-traversably, served only via gated endpoints, never executed (IX); all personal endpoints + file serving behind the existing auth gate; the inbound bot acts only on the configured owner chat id (I/IX); no platform automation — `/pause`/`/resume` control only our polling, "Open" is a link (VIII); UTF-8/RTL end to end, UTC stored / owner-tz displayed (V); every new tunable read from config (III).  
**Scale/Scope**: One owner; low hundreds–low thousands of projects; a working subset engaged on the board; a few attachments per project; ~12 new HTTP endpoints, 5 bot commands + 4 callback actions + an add-note conversation, 1 new Board screen + feed/detail extensions.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Personal & Single-Box**: No accounts/roles/tenancy. The dashboard reuses Feature 2's single shared-password gate; the inbound bot authorizes **only** the configured `TELEGRAM_CHAT_ID` and ignores every other chat. **Pass.**
- [x] **II. Polite, Non-Aggressive Access**: This feature adds **no new scraping**. `/pause` only *reduces* polling; `/resume` re-enables the existing polite loop unchanged. The bot uses long-poll `getUpdates` against Telegram (not Mostaql). **Pass (no scraping introduced).**
- [x] **III. Config Over Code**: The personal-status set + labels, allowed file types, max upload size, and the pause flag live in the `settings` store; the storage path is an env/secret (`attachments_dir`). No behavior-affecting constant is hard-coded. **Pass.**
- [x] **IV. Idempotent Ingestion & Non-Destructive History**: Exactly one personal record per project (PK = `project_id`), created lazily and shared by both surfaces. Automation never deletes/overwrites notes, files, statuses, tags, or board order; only owner-initiated deletes remove them; both new tables and `attachments_dir` are inside the backed-up `./data` volume. A status removed from config does not erase records (fallback display). **Pass.**
- [x] **V. Arabic-First Correctness**: UTF-8 throughout; tags, notes, and file display names render RTL with bidi isolation; status labels are Arabic-first and config-driven; applied/status-changed/upload timestamps stored UTC, shown in `owner_timezone`. **Pass.**
- [x] **VI. Fail Loud**: `/health` reports the last scrape's status + counts **and** the paused state; `/stats` reports today's found/qualified, totals, and per-stage counts; Telegram actions are idempotent/at-least-once; the bot process logs and its failures are observable (it is restarted by its supervisor like the worker). **Pass.**
- [x] **VII. Conservative, Fail-Closed Qualification**: This feature does not qualify projects or touch the watcher's evaluation; it only organizes them personally. **N/A.**
- [x] **VIII. No Platform Automation**: No auto-bid/message/write to mostaql.com. The "Open" button is a plain link; `/pause`/`/resume` toggle only our own polling flag. **Pass.**
- [x] **IX. Local Security Hygiene**: Every personal/board/attachment/control endpoint sits behind the auth gate; uploads are validated (extension + content-type + magic-bytes + size), stored under `attachments_dir` (outside any web root) with UUID names (no path traversal), streamed via gated endpoints with explicit `Content-Type` + `X-Content-Type-Options: nosniff` + `Content-Disposition`, and never executed; secrets stay in `.env`; the bot is not publicly exposed (outbound long-poll, no inbound port). **Pass.**
- [x] **X. Deployment-Portable**: `attachments_dir` is a configurable relative path under the portable `./data` volume; the bot is one more env-configured process (compose service + systemd unit) reusing the existing image; no hostnames/absolute paths baked in; all state (DB + attachments) restorable from backup. **Pass.**

**Result**: All gates Pass / N/A. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/003-personal-pipeline-workspace/
├── plan.md              # This file
├── research.md          # Phase 0 output — key design decisions
├── data-model.md        # Phase 1 output — new tables, DTOs, settings, transitions
├── quickstart.md        # Phase 1 output — run worker + bot + api + frontend locally
├── contracts/
│   ├── openapi.yaml      # Phase 1 output — new HTTP endpoints
│   └── telegram-bot.md   # Phase 1 output — commands, inline buttons, callback_data, conversations
└── checklists/
    └── requirements.md  # From /speckit.specify
```

### Source Code (repository root)

```text
src/mostaql_notifier/
├── db/
│   └── models.py            # EXTEND — PersonalRecord (PK=project_id, 1:1) + Attachment (many) + relationships
├── personal/                # NEW — surface-agnostic personal-layer service (used by API AND bot)
│   ├── __init__.py
│   ├── service.py           # get_or_create_record; favorite/status/tags/applied/outcome/hide/unhide/notes/reorder
│   │                        #   — enforces single-record, applied-once, status_changed_at, last-write-wins
│   ├── statuses.py          # read configured status set (keys+labels) from settings; default slug, "applied" slug, validation, fallback
│   └── stats.py             # /stats + /health + Home figures (found/qualified today, totals, per-stage counts, paused)
├── storage/                 # NEW — attachment filesystem layer
│   ├── __init__.py
│   └── attachments.py       # validate (ext+content-type+magic+size); safe UUID stored name; save/open/delete; resolves attachments_dir
├── api/
│   ├── schemas.py           # EXTEND — Personal*, Board*, Attachment*, Control DTOs; add personal fields to ProjectListItem/Detail
│   ├── app.py               # EXTEND — include personal/board/attachments/control routers (gated); ensure attachments_dir exists
│   └── routers/
│       ├── projects.py      # EXTEND — load personal record; personal_status/favorites_only/include_hidden filters
│       ├── home.py          # EXTEND — add `paused` to HomeOverview
│       ├── personal.py      # NEW — GET/PATCH /api/projects/{id}/personal (+ favorite toggle convenience)
│       ├── board.py         # NEW — GET /api/board; POST /api/board/move
│       ├── attachments.py   # NEW — list/upload/rename/delete/download/preview
│       └── control.py       # NEW — GET /api/control; POST /api/control/pause|resume (mirrors bot)
├── notify/
│   ├── format.py            # EXTEND — build the inline keyboard (Favorite/Applied/Dismiss/Add note/Open) for a project
│   └── telegram.py          # EXTEND — _send / send_project_notification accept reply_markup
├── bot/                     # NEW — inbound Telegram bot (separate long-poll process)
│   ├── __init__.py
│   ├── __main__.py          # run() entrypoint → mostaql-notifier-bot console script
│   ├── app.py               # Application builder; owner-chat authz; wires handlers; lifecycle
│   ├── callbacks.py         # CallbackQueryHandler: fav/app/dis/note → personal.service; edits msg to confirm (idempotent)
│   ├── commands.py          # /find /pause /resume /health /stats
│   └── conversation.py      # "Add note" force-reply flow → append to project notes
├── worker/
│   ├── main.py              # EXTEND — (no bot here) pass owner_tz; keyboard attached on send
│   └── poll.py              # EXTEND — skip the cycle quietly when watcher_paused (no scrape_run, no false-red)
└── config/
    ├── settings_store.py    # EXTEND DEFAULTS — watcher_paused, personal_statuses, upload_max_bytes, upload_allowed_types
    └── secrets.py           # EXTEND — attachments_dir (env); reuse telegram_chat_id as the bot's owner allowlist

alembic/versions/
└── _____personal_layer.py   # NEW — create personal_records + attachments (idempotent on fresh DB; CI: alembic upgrade head)

frontend/
├── app/
│   ├── board/page.tsx              # NEW — Kanban board (engaged projects by status)
│   ├── projects/page.tsx           # EXTEND — per-row quick actions + personal-status/favorites filters
│   └── projects/[id]/page.tsx      # EXTEND — personal controls card + workspace card
├── components/
│   ├── Nav.tsx                     # EXTEND — add "اللوحة" (Board) nav link
│   ├── PauseControl.tsx            # NEW — pause/resume toggle (mirrors bot), shown on Home/Board
│   ├── personal/                   # NEW — FavoriteToggle, StatusSelect, TagEditor, OutcomeFields, HideButton, ProjectRowMenu
│   ├── board/                      # NEW — Board, BoardColumn, BoardCard, dnd wiring (@dnd-kit)
│   ├── workspace/                  # NEW — MarkdownEditor (+preview tabs), FileDropzone, FileList, FilePreviewDialog
│   └── ui/                         # NEW primitives — dropdown-menu, dialog, textarea, tabs (Base UI + CVA, RTL-aware)
└── lib/
    ├── api.ts                      # EXTEND — personal/board/attachments/control calls; multipart upload via FormData
    ├── types.ts                    # EXTEND — PersonalRecord, Board, Attachment, Control DTOs; personal fields on ProjectListItem/Detail
    ├── usePersonal.ts              # NEW — mutations (favorite/status/tags/outcome/hide/notes) + invalidate ["projects"]/["project",id]/["board"]
    ├── useBoard.ts                 # NEW — board query + move mutation (optimistic)
    └── useAttachments.ts           # NEW — list/upload/rename/delete + preview/download URLs

tests/
├── api/                            # NEW — test_personal_api, test_board_api, test_attachments_api (incl. traversal/type/size/auth), test_control_api; EXTEND test_projects_* (personal filters), test_home_* (paused)
├── unit/                           # NEW — test_personal_service, test_personal_statuses, test_stats, test_telegram_keyboard (codec), test_inbound_bot (authz/idempotency/commands/conversation)
└── integration/                    # NEW — test_pause_resume_cycle, test_telegram_actions_end_to_end (button → record → dashboard parity)

deploy/
├── docker-compose.yml              # EXTEND — add `bot` service (reuse Dockerfile.api, command: mostaql-notifier-bot); ensure ../data (attachments) mounted
├── mostaql-notifier-bot.service    # NEW — systemd unit for the bot (sibling of the worker unit)
└── (Dockerfile.api reused for the bot)

pyproject.toml                      # EXTEND — python-multipart in [api]; mostaql-notifier-bot console script
.env.example / .gitignore           # EXTEND — ATTACHMENTS_DIR documented; data/attachments/ ignored
```

**Structure Decision**: Web-application layout, continuing Feature 2. The personal-layer **service**
(`src/mostaql_notifier/personal/`) is the linchpin: both the FastAPI routers and the inbound bot call it, so
"one record, consistent across surfaces" (FR-029, SC-006) is guaranteed in one place rather than duplicated.
The inbound bot is a **separate process** (not folded into the worker) so a bot fault never stalls polling
and vice-versa; the two coordinate only through the DB (`watcher_paused`), which keeps them decoupled and
portable. Uploaded files live on the filesystem (not in SQLite) under a configurable, backed-up directory,
served exclusively through gated streaming endpoints. The schema stays single-source in Python and is
evolved by **one Alembic migration**; new tunables are additive `settings` rows seeded by `seed_defaults`.

## Complexity Tracking

> No constitution violations — table intentionally empty.
