# Phase 0 Research: Personal Pipeline and Workspace

This feature has **no open "NEEDS CLARIFICATION"** items — the spec resolved every product ambiguity with a
documented assumption. What follows are the **design decisions** that ground the plan in the existing
Feature 1/2 codebase (mapped by parallel exploration of `db/`, `config/`, `api/`, `notify/`, `worker/`,
`frontend/`, `tests/`, and `deploy/`). Each is recorded as Decision / Rationale / Alternatives considered.

---

## 1. New schema: two tables via one Alembic migration; 1:1 by shared PK

**Decision**: Add **`personal_records`** (PK = `project_id`, FK → `projects.id`, i.e. a shared primary key
that enforces 1:1 at the DB level) and **`attachments`** (own autoincrement `id`, FK → `projects.id`,
many-per-project) in a **single new Alembic migration** (down_revision = `8d0f765b34e3`). Reuse the existing
`UtcDateTime`, `JSONType`, and `Base`/naming-convention from `db/types.py` + `db/base.py`. Store `tags` as a
`JSONType` list of strings **on the personal record** (no join table). Store the personal `status` as a
**string slug** (not a DB enum).

**Rationale**: `Project.id` is an integer PK; a child table whose PK *is* the FK is the canonical SQLAlchemy
1:1 and makes a duplicate record structurally impossible (reinforces FR-029/SC-006). Alembic is already
configured and gated in `scripts/ci.sh` (`alembic upgrade head` on a fresh DB) with `render_as_batch=True`
for SQLite — so a real migration (not `create_all`) is the house mechanism. Tags are free-form, per-project,
single-user, and never filtered server-side in this feature → a JSON array is the simplest faithful model
(mirrors how `Project.skills` is already a JSON array searched via `cast(..., String).ilike`). The status is
a **config-driven** slug (Principle III): a native DB enum would hard-code the set and fight a configurable
status list, and would break if the owner renames/removes a stage.

**Alternatives considered**:
- *Personal record with its own surrogate `id` + unique(`project_id`)*: works, but a shared PK is simpler and makes 1:1 a structural guarantee, not a constraint to remember.
- *`personal_tags` join table*: over-engineered for single-user free-form labels with no global taxonomy (explicitly out of scope); adds a table and joins for no query benefit.
- *DB `Enum` for status*: violates config-over-code; removing/renaming a stage would orphan or reject existing rows.
- *Status-change history table*: the spec needs only "when the status last changed" (FR-008) → a single `status_changed_at` column suffices; a full history table is deferred (non-destructive, can be added later).

---

## 2. Personal status set: config-driven ordered list of {key,label}

**Decision**: Store the status set as a new `settings` row **`personal_statuses`** (`json`), an **ordered list
of `{ "key": <slug>, "label": <Arabic display> }`**. Default:

```json
[
  {"key": "new",           "label": "جديد"},
  {"key": "interested",    "label": "مهتم"},
  {"key": "applied",       "label": "تقدّمت"},
  {"key": "in_discussion", "label": "قيد النقاش"},
  {"key": "won",           "label": "ربح"},
  {"key": "lost",          "label": "خسارة"},
  {"key": "ignored",       "label": "تجاهل"}
]
```

Conventions enforced in `personal/statuses.py`: the **first entry's key is the default** ("new"); the key
**`applied`** is the stage that triggers the applied-date rule; the board renders columns in list order; a
stored status whose key is no longer in the configured list is shown under a clearly-labeled **fallback
column** (non-destructive, Edge Cases).

**Rationale**: Keys are stable identifiers persisted on records; labels are Arabic-first display (Principle
V) and editable without code (Principle III), matching how Feature 2's `settings_spec` already carries Arabic
labels. Separating key from label lets the owner relabel a stage without rewriting every record. Identifying
"default" by position and "applied" by a reserved key keeps the automation rules (FR-005, FR-019) declarative.

**Alternatives considered**:
- *Two parallel settings (keys array + labels map)*: more rows, easy to desync; one ordered list is atomic.
- *English labels by default*: the dashboard is Arabic-first/RTL; Arabic labels are the right default, English is one config edit away.
- *In-app status-set editor*: explicitly out of scope; the set is changed in configuration this feature.

---

## 3. A single surface-agnostic personal-layer service

**Decision**: Put every personal mutation in `src/mostaql_notifier/personal/service.py` — sync, session-based
functions: `get_or_create(session, project_id)`, `toggle_favorite`, `set_status`, `add_tags`/`remove_tags`,
`set_applied`, `set_outcome` (won/lost), `hide`/`unhide`, `set_notes`, `move`/`reorder`. The FastAPI routers
**and** the inbound bot call these; neither reimplements the rules. The service centralizes: lazy
get-or-create, the **applied-once** rule (set `applied_at = today` on first entry into `applied`, never
overwrite — FR-005), stamping `status_changed_at` on a real status change (FR-008), won-amount ≥ 0
validation, and last-write-wins board updates.

**Rationale**: "Acting from Telegram and the dashboard affects the same single record; the two surfaces stay
consistent" (FR-029, SC-006) is only trustworthy if both surfaces share one implementation. The existing API
already separates serialization helpers from query logic; a service module fits the house style and is
directly unit-testable without HTTP or Telegram.

**Alternatives considered**:
- *Logic in the routers, bot calls the API over HTTP*: couples the bot to the running API, adds a network hop and an auth story for an internal caller, and risks drift if either path is edited alone.
- *Duplicate logic in bot and API*: guarantees eventual divergence of the applied-once / status-stamp rules.

---

## 4. Inbound Telegram bot: a separate long-polling process

**Decision**: Build the inbound side as a **separate process** `mostaql-notifier-bot`
(`src/mostaql_notifier/bot/`, new `[project.scripts]` entry, new compose service reusing `Dockerfile.api`,
new systemd unit). It uses **`python-telegram-bot`'s `Application` with long-poll `getUpdates`** (already a
dependency), registers a `CallbackQueryHandler` (the inline buttons), `CommandHandler`s (`/find /pause
/resume /health /stats`), and a `ConversationHandler` / force-reply for "Add note". Every handler first
checks `update.effective_chat.id == int(telegram_chat_id)` and silently ignores anything else. It obtains DB
sessions via the existing `get_sessionmaker()` and calls the personal service + stats helpers. It coordinates
with the worker **only through the DB** (`watcher_paused`).

**Rationale**: A separate process gives fault isolation (a bot crash never stalls the poll loop, and vice
versa) and matches the established multi-process architecture (worker / api / frontend already run
separately, supervised by compose/systemd, sharing SQLite via WAL). Long-poll `getUpdates` is **outbound-
initiated**, so there is **no inbound port and no public webhook** — satisfying "scraper/worker never
publicly exposed" and portability (Principles IX, X). The worker keeps its existing outbound `ExtBot` sender;
the bot process is the single `getUpdates` consumer for the token (Telegram allows exactly one), so there is
no conflict. All cross-process coordination is a settings row, which is already the config mechanism.

**Alternatives considered**:
- *Run the bot as a coroutine inside the worker process*: fewer moving parts, but couples lifecycles (a bot exception can take down polling) and complicates the worker's shutdown; rejected for robustness.
- *Webhook instead of long-poll*: needs a public HTTPS endpoint/port → violates "never publicly exposed" and breaks single-box/NAT portability; rejected.
- *Drive bot actions by calling the dashboard API*: see §3 — rejected.

**Callback_data codec** (`notify/format.py` build + `bot/callbacks.py` parse): compact `pf:{action}:{project_id}`
with `action ∈ {fav, app, dis, note}` and `project_id` the integer PK (e.g. `pf:fav:123`) — well within
Telegram's 64-byte `callback_data` limit (the DB id is far shorter than `mostaql_id`). "Open" is a Telegram
**URL button** (`project.url`), not a callback. Tapping resolves the project by id, applies the action via the
service (favorite toggles; applied/dismiss are idempotent no-ops if already so), answers the callback, and
**edits the message** to confirm — harmless on repeat or on an old message; a missing project answers gracefully.

---

## 5. Inline buttons on outbound notifications

**Decision**: Extend `notify/format.py` with a `build_project_keyboard(project)` returning a
`telegram.InlineKeyboardMarkup` (rows: [Favorite, Applied], [Dismiss, Add note], [Open→url]); extend
`TelegramSender._send` and `send_project_notification` to accept and pass `reply_markup`. The existing dedup
(`notifications_log.dedup_key`) and `project.notified` flow is unchanged.

**Rationale**: The sender already uses `ExtBot.send_message(..., parse_mode="HTML")`; adding `reply_markup` is
the one supported parameter needed and keeps the at-least-once/dedup guarantees intact (Principle VI). Keeping
keyboard construction in `format.py` mirrors where the message text is already built and keeps `telegram.py`
transport-only.

**Alternatives considered**:
- *Attach buttons in `telegram.py`*: leaks presentation into transport; rejected for separation of concerns.

---

## 6. Pause/resume: a `watcher_paused` settings flag, checked in the poll job, surfaced separately

**Decision**: Add `settings` row **`watcher_paused`** (`bool`, default `false`). In the worker, check it in
the poll job wrapper (right where the circuit-breaker check already short-circuits the cycle in `poll.py`)
and, when paused, **skip the cycle quietly** — do **not** write a `scrape_run` row. Expose the paused state
through `/health` (bot), a new `paused` field on `HomeOverview`, and a dashboard pause toggle + `control`
endpoints that mirror `/pause` `/resume`.

**Rationale**: The existing circuit breaker already models "skip this cycle," so the seam exists. Writing a
`blocked` run for an *intentional* pause would turn Feature 2's health light red (blocked ⇒ red) and read as
a fault — wrong. Skipping quietly keeps the last real run as the health basis and surfaces "paused" as a
distinct, first-class state (Principle VI: the owner can always tell the system is intentionally idle, not
broken). A settings flag is the config-driven, restart-surviving, cross-process coordination channel both the
bot and the dashboard already have access to.

**Alternatives considered**:
- *Record a `blocked`/`paused` scrape_run*: pollutes health and the run history with non-faults; rejected. (No `paused` member exists on `RunStatus`, and adding one would still risk the red-light semantics.)
- *Store pause in `app_state` instead of `settings`*: `app_state` is for worker-internal runtime state (e.g. circuit-breaker timers); `watcher_paused` is an owner-facing tunable → `settings` is the right home and is already reachable from the dashboard/bot.

---

## 7. File uploads: validate hard, store outside the web path, stream through gated endpoints

**Decision**: Add **`python-multipart`** to the `[api]` extra (FastAPI `UploadFile` needs it). Validate every
upload by **(a)** extension in the configured allowed set, **(b)** declared content-type, **(c)**
**magic-byte sniff** (`%PDF-` for PDF; `PK\x03\x04` + OOXML for DOCX; UTF-8 text for Markdown), and **(d)**
size ≤ `upload_max_bytes` (stream with a hard cap; reject before fully buffering an oversize file). On any
failure: **store nothing**, return a clear `400/422` message. Persist to
`attachments_dir/{project_id}/{uuid}.{ext}` with `stored_name = "{uuid}.{ext}"`; keep `original_name` in the
DB for display. Serve via **gated** `GET /api/attachments/{id}/download` (Content-Disposition: attachment) and
`/preview` (inline for PDF, text body for Markdown), each setting an explicit `Content-Type` and
`X-Content-Type-Options: nosniff`, streamed with `FileResponse`/`StreamingResponse` — **never** via
`StaticFiles`. `attachments_dir` is an **env/secret** (`attachments_dir: str = "./data/attachments"`), default
under the backed-up `./data` volume; add `data/attachments/` to `.gitignore`.

**Rationale**: This is the highest-risk surface and Constitution IX is explicit: validate by type+size, store
safely (no execution, correct content-type, non-traversable paths), never publicly exposed. Sniffing magic
bytes defeats a renamed-extension upload; a server-generated UUID stored name removes all user-controlled
path input (no traversal, no collision — covers the "duplicate / very long / Arabic / unsafe filename" edge
cases while preserving the original for display). The storage **path** is a deployment concern (like
`DATABASE_URL`), so it belongs in env/secrets, not the runtime settings table — and keeping it under `./data`
makes it part of the existing portable, restorable backup set (Principle X).

**Alternatives considered**:
- *`StaticFiles` mount for downloads*: would expose a directory and bypass the auth gate; rejected outright.
- *Store files as BLOBs in SQLite*: bloats the DB and its WAL, complicates backup/streaming, and fights the "files on disk, backed up" model; rejected.
- *Trust the client-declared content-type/extension only*: trivially spoofed; magic-byte sniffing is required.
- *Put `attachments_dir` in the settings table*: it is a path tied to the deployment/volume, not a behavior tunable; env/secrets matches `database_url` and portability.

---

## 8. Board model: engaged subset, ordered by `board_position`, last-write-wins moves

**Decision**: The board reads **engaged, non-hidden** projects — `(favorite = true OR status != default
'new') AND hidden = false` — grouped into columns by the configured status order, each column ordered by
**`board_position`** (a `Float` on the personal record; reorders rewrite affected positions, midpoint
insertion where cheap). `GET /api/board` returns columns+cards; `POST /api/board/move` takes
`{project_id, to_status, position}` and, via the service, sets status (applying the applied-once rule when
`to_status == 'applied'`), stamps `status_changed_at`, and assigns `board_position` — **last-write-wins**, so
rapid successive moves converge (FR-023). Cards carry the read-only project facts (title, hiring rate, budget,
tier, bids, age, tags).

**Rationale**: The engaged criterion comes straight from the spec/assumptions; computing it in one SQL
predicate keeps the board and the feed's filters consistent. A float position is the simplest persistent
manual-order that supports cheap reordering without renumbering the whole column; last-write-wins is the
correct single-user concurrency model and needs no locking.

**Alternatives considered**:
- *Integer positions renumbered on every move*: more writes per drag; a float (or large-gap int) avoids cascades.
- *Fractional-index strings (e.g. LexoRank)*: robust at scale but overkill for a single user's small board.
- *Derive the board purely client-side from the feed*: would duplicate the engaged/ordering logic in TS and risk drift; a dedicated endpoint keeps one source of truth.

---

## 9. Frontend libraries & the "not the Next.js you know" caveat

**Decision**: Add, pinned and React-19-compatible: **`@dnd-kit/core` + `@dnd-kit/sortable` +
`@dnd-kit/utilities`** (Kanban DnD with a keyboard sensor for FR-034), and **`react-markdown` + `remark-gfm`
+ `rehype-sanitize`** (notes preview with XSS-safe rendering). Vendor four new Base-UI primitives under
`components/ui/`: **`dropdown-menu`** (row quick actions), **`dialog`** (file preview / confirm), **`textarea`**
(notes editor), **`tabs`** (edit/preview). PDF preview uses a native `<iframe>`/`<embed>` against the gated
`/preview` URL (no PDF library). Markdown editing is a styled `<textarea>` (no heavyweight editor). New routes
(`/board`) are auto-protected by the existing `proxy.ts` matcher. **Before writing any frontend code**, read
`frontend/node_modules/next/dist/docs/` as `frontend/AGENTS.md` mandates ("this is NOT the Next.js you know"
— e.g. `proxy.ts` replaces `middleware.ts`, Tailwind v4 CSS-config, Base UI not Radix).

**Rationale**: `@dnd-kit` is the actively-maintained, hooks-based, accessibility-friendly DnD library with no
React-19 peer issues (react-beautiful-dnd is deprecated). `react-markdown`+`rehype-sanitize` renders the
owner's markdown without `dangerouslySetInnerHTML`, satisfying the "served safely / never executed" spirit
for note content. Reusing Base UI + CVA keeps the four new primitives consistent with the existing kit and
RTL-aware. The AGENTS.md caveat is load-bearing: the stack diverges from training-data Next.js, so the
implementer must consult the vendored docs to avoid wrong conventions (already proven by `proxy.ts`).

**Alternatives considered**:
- *react-beautiful-dnd / react-dnd*: deprecated or heavier with weaker React-19/RTL stories; rejected.
- *A full rich-text/markdown editor (TipTap, MDXEditor)*: far more surface and bundle than "a textarea with preview" needs; rejected.
- *A PDF.js viewer component*: unnecessary — the browser's native PDF viewer via `<iframe>` covers inline preview; keeps the bundle small.

---

## 10. Backups & portability for the new state

**Decision**: Both new tables live in the same SQLite file already backed up; `attachments_dir` defaults under
`./data`, which is the mounted, backed-up volume in `deploy/docker-compose.yml`. Document `ATTACHMENTS_DIR` in
`.env.example`, ignore `data/attachments/` in `.gitignore`, and note in `quickstart.md` that a backup must
include both the DB **and** the attachments directory (FR-032, Principle X).

**Rationale**: Keeping attachments inside the existing portable data volume makes "included in backups" and
"VPS move is a redeploy" true by construction, with no new backup machinery.

**Alternatives considered**:
- *A separate attachments volume/path outside `./data`*: would need its own backup wiring and risks being forgotten; co-locating under `./data` is simplest and safe.
