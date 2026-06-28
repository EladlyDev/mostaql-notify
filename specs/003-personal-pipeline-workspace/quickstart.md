# Quickstart: Personal Pipeline and Workspace (Feature 3)

Adds the owner's personal layer over Features 1 + 2. Now **four** processes share `./data/mostaql.db` (WAL):
the **worker** (polls + sends notifications with action buttons), the new **bot** (handles button taps and
commands), the **API**, and the **frontend**. Uploaded files live under `./data/attachments` (backed up with
the DB).

## Prerequisites

- Features 1 + 2 set up: `.venv`, `.env` with `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`,
  and the dashboard secrets; DB migrated and ideally seeded with collected projects.
- Node 20+ and npm.

## 1. Add the Feature 3 config to `.env`

Append to the gitignored `.env` (mirror as blanks/defaults in `.env.example`):

```dotenv
# Feature 3 — personal pipeline & workspace
ATTACHMENTS_DIR=./data/attachments    # where uploaded files are stored (under the backed-up data volume)
```

- `TELEGRAM_CHAT_ID` (already set in Feature 1) doubles as the **bot's owner allowlist** — the bot ignores
  every other chat.
- The configurable **status set**, **max upload size**, and **allowed types** are `settings` rows seeded on
  first run (`personal_statuses`, `upload_max_bytes`, `upload_allowed_types`) — edit them in the DB to retune,
  no redeploy (Constitution III). `watcher_paused` is also a `settings` row (default false).

## 2. Apply the migration + new deps

```bash
.venv/bin/pip install -e ".[api,dev]"        # api extra now includes python-multipart
.venv/bin/alembic upgrade head               # creates personal_records + attachments
mkdir -p ./data/attachments                  # also auto-created by the API on startup
```

## 3. Run the four processes (each in its own shell)

```bash
# worker (poll loop + notifications with inline buttons)
.venv/bin/python -m mostaql_notifier

# inbound bot (button taps + /find /pause /resume /health /stats) — NEW
.venv/bin/mostaql-notifier-bot

# API
.venv/bin/uvicorn mostaql_notifier.api.app:app --reload --port 8000

# frontend
cd frontend && npm install && echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local && npm run dev
```

New frontend deps pulled in by `npm install` (added to `package.json`): `@dnd-kit/core`, `@dnd-kit/sortable`,
`@dnd-kit/utilities` (board), `react-markdown`, `remark-gfm`, `rehype-sanitize` (notes).

> Frontend note: this stack is **not** stock Next.js — before editing frontend code, read
> `frontend/node_modules/next/dist/docs/` as `frontend/AGENTS.md` mandates (e.g. `proxy.ts`, not
> `middleware.ts`; Tailwind v4 CSS config; Base UI primitives). New routes like `/board` are auto-protected
> by `proxy.ts`.

## 4. Use it

1. **Feed** (`/projects`): each row/card now shows a favorite indicator + personal status and a quick-action
   menu (favorite / set status / hide). Filter by personal status or favorites-only; hidden projects are
   excluded until you choose "show hidden".
2. **Detail** (`/projects/{id}`): personal controls (favorite, status, tags, applied date, won amount / lost
   reason, hide) + a status-changed timeline; a **workspace** with a markdown notes editor (+ preview) and a
   drag-and-drop file area (PDF/DOCX/MD), each file listed with name/type/size/date, previewable (MD/PDF) or
   downloadable (DOCX/PDF), renamable and deletable.
3. **Board** (`/board`): one column per status; drag cards between columns (into "Applied" records today);
   reorder within a column to set priority. A pause/resume toggle mirrors the bot.
4. **Telegram**: tap a notification's buttons (Favorite / Applied / Dismiss / Add note / Open); send
   `/find <kw>`, `/pause`, `/resume`, `/health`, `/stats`. Anything you do here shows up on the dashboard.

## 5. One-command bring-up (docker-compose)

```bash
cd deploy
docker compose up --build
# worker + bot + api (:8000) + frontend (:3000) sharing ../data (db + attachments)
```

The compose file gains a **`bot`** service (reuses `Dockerfile.api`, `command: mostaql-notifier-bot`) and
mounts the same `../data` volume so attachments persist and are backed up.

## Backups (Feature 3 — FR-032, constitution X)

A backup MUST capture **both** the database **and** the attachments directory, since notes/statuses/tags
live in the DB while uploaded files live on disk:

- `./data/mostaql.db` (+ its `-wal`/`-shm` sidecars) — personal records, tags, notes, board order.
- `./data/attachments/` (or wherever `ATTACHMENTS_DIR` points) — the uploaded PDF/DOCX/MD files.

Both default to living under the single backed-up `./data` volume, so backing up `./data` covers everything;
restoring it on a new box is a redeploy with no code changes. Personal data is **never** deleted by
automation — only owner-initiated deletes remove it (constitution IV).

## Verifying the contract (tests)

```bash
.venv/bin/pytest tests -q              # personal service, board, attachments (incl. security), bot handlers, control
cd frontend && npm test                # board reducer, markdown sanitize, row-menu, upload-validation messaging
bash scripts/ci.sh                     # full gate: alembic upgrade + ruff + pytest + frontend lint/test/build
```

## Smoke checks mapping to success criteria

- **SC-001/SC-006**: favorite + set stage + tag + applied/won from the dashboard, then from a Telegram button —
  one record, identical on both, no duplicate.
- **SC-002**: write markdown notes + drag in a PDF/DOCX/MD → validated, listed, previewable/downloadable;
  restart the API → still there.
- **SC-003**: on `/board`, drag a card to a new column (status updates; into "Applied" records the date) and
  reorder → persists across reload.
- **SC-004**: from Telegram act on a fresh project + `/pause` then `/resume` (worker skips then resumes next
  cycle) + `/health` + `/stats`.
- **SC-005**: upload a `.zip`/image (rejected: unsupported type) and an >`upload_max_bytes` file (rejected: too
  large) → nothing stored; run a watcher cycle → personal data + files unchanged.
- **SC-007**: Arabic titles/tags/notes/filenames render RTL across feed, detail, workspace, board.
- **SC-008**: tap a Telegram button twice / on an old notification → same end state, confirming reply, no error.
- **SC-009**: empty board columns and a project with no notes/files → clean empty states.
- **SC-010**: hide a project → leaves the active feed + board but the record, notes, and files remain and it
  can be restored via "show hidden".
```
