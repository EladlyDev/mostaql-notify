---
description: "Task list for Feature 3 — Personal Pipeline and Workspace"
---

# Tasks: Personal Pipeline and Workspace

**Input**: Design documents from `/specs/003-personal-pipeline-workspace/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml, contracts/telegram-bot.md

**Tests**: Test tasks are included for the security- and correctness-critical paths the spec's per-story
Independent Tests and Success Criteria demand — the shared personal service & status config (foundational),
the personal API + feed filters (US1), **upload validation/traversal/auth** (US2), the board move rules
(US3), and the **bot owner-authz/idempotency + pause** (US4). Pure-presentation pieces are covered by the
quickstart smoke checks in Polish.

**Organization**: Tasks are grouped by user story. The shared personal-layer **service**, the two new tables,
and the status config are **foundational** (every story consumes them); each story then adds its own surface
(API + UI, and for US4 the bot) as an independently testable vertical slice. Backend-before-UI is preserved
within each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 / US4 (Setup, Foundational, Polish carry no story label)

## Path Conventions

- **Backend** (existing Python package/venv): `src/mostaql_notifier/{db,personal,storage,api,notify,bot,worker,config}/`, tests in `tests/`
- **Frontend** (existing Next.js app): `frontend/`
- **Migrations**: `alembic/versions/`; **Deploy**: `deploy/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies, config keys, and leaf scaffolding for backend and frontend.

- [X] T001 [P] In `pyproject.toml`, add `python-multipart>=0.0.9` to the `[api]` optional-dependency group (FastAPI `UploadFile`) and add a `mostaql-notifier-bot = "mostaql_notifier.bot.__main__:run"` entry under `[project.scripts]`.
- [X] T002 [P] In `src/mostaql_notifier/config/secrets.py`, add `attachments_dir: str = "./data/attachments"` to `Secrets`; document `ATTACHMENTS_DIR` in `.env.example`; add `data/attachments/` to `.gitignore`.
- [X] T003 [P] In `src/mostaql_notifier/config/settings_store.py`, add four `DEFAULTS` rows: `watcher_paused` (`False`,`bool`), `personal_statuses` (the 7-entry ordered `[{key,label}]` list from research §2, `json`), `upload_max_bytes` (`10485760`,`int`), `upload_allowed_types` (`["pdf","docx","md"]`,`json`).
- [X] T004 [P] In `frontend/package.json`, add and install `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` (board) and `react-markdown`, `remark-gfm`, `rehype-sanitize` (notes); confirm React-19 peers resolve.
- [X] T005 [P] Vendor four Base-UI primitives under `frontend/components/ui/` — `dropdown-menu.tsx`, `dialog.tsx`, `textarea.tsx`, `tabs.tsx` — following the existing CVA + RTL-aware pattern (`@base-ui/react` menu/dialog/tabs; native `<textarea>` for the editor).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The two new tables + migration, the configurable status helpers, and the **surface-agnostic
personal-layer service** that the API *and* the bot both call. **No user story can be completed until this is
done** — it is the single source of truth for "one record, consistent across surfaces" (FR-029, SC-006).

**⚠️ CRITICAL**: The service, status config, and migration are cross-cutting — US1–US4 all depend on them.

- [X] T006 In `src/mostaql_notifier/db/models.py`, add `PersonalRecord` (PK `project_id` FK→`projects.id`; `favorite`, `status` str default `"new"`, `tags` JSONType `[]`, `applied_at`, `won_amount` Numeric, `lost_reason` Text, `notes` Text default `""`, `board_position` Float default `0.0`, `hidden` bool, `status_changed_at`, `reminder_at`, `created_at`, `updated_at` — all UtcDateTime where dated) and `Attachment` (`id` PK, `project_id` FK, `original_name`, `stored_name` unique, `file_type`, `content_type`, `size_bytes`, `uploaded_at`); add `Project.personal` (uselist=False) and `Project.attachments` relationships; add the indexes from data-model.md.
- [X] T007 Generate the Alembic migration in `alembic/versions/` (`alembic revision -m "personal layer"`, down_revision `8d0f765b34e3`) creating `personal_records` + `attachments` with the same column types/indexes as T006; verify `alembic upgrade head` applies cleanly on a fresh temp DB. Depends on T006.
- [X] T008 [P] Create `src/mostaql_notifier/personal/statuses.py`: read `personal_statuses` from the settings store; expose the ordered `[{key,label}]`, the default slug (first entry), the reserved `applied` slug, a label lookup, key validation, and the fallback for a stored key no longer configured. Depends on T003.
- [X] T009 Create `src/mostaql_notifier/personal/service.py` (sync, session-based): `get_or_create(session, project_id)`, `toggle_favorite`, `set_status` (validate via statuses, stamp `status_changed_at`, **applied-once** rule), `set_applied`, `set_outcome` (won_amount ≥ 0 / lost_reason), `set_tags`/`add_tags`/`remove_tags`, `hide`/`unhide`, `set_notes` (append + replace), `move`/`reorder` (status + `board_position`, last-write-wins). Enforces exactly one record per project. Depends on T006, T008.
- [X] T010 [P] Create `src/mostaql_notifier/personal/stats.py`: shared figures for `/stats` and `/health` — found-today, qualified-today (owner-tz day boundary → UTC), total projects/clients, per-stage counts over engaged records, paused state, and the latest run status. Depends on T008.
- [X] T011 [P] In `tests/api/conftest.py`, add row factories `make_personal_record(session, **over)` and `make_attachment(session, **over)` with valid defaults, matching the existing `make_project`/`make_client` style. Depends on T006.
- [X] T012 [P] In `src/mostaql_notifier/api/app.py`, extend CORS `allow_methods` to add `PATCH` and `DELETE`, and ensure `attachments_dir` exists on startup (create it in the lifespan). Depends on T002.
- [X] T013 [P] Unit tests in `tests/unit/test_personal_statuses.py`: default slug = first entry, `applied` slug resolves, unknown key rejected by validation, removed-from-config key surfaces via the fallback. Depends on T008.
- [X] T014 [P] Unit tests in `tests/unit/test_personal_service.py`: get-or-create is idempotent (one record), favorite toggles, `set_status` validates + stamps `status_changed_at`, **applied-once** (second →applied keeps the original date), won_amount < 0 rejected, hide/unhide, `set_notes` appends, `move`/`reorder` last-write-wins. Depends on T009.

**Checkpoint**: Schema migrated, status config + personal service unit-tested, factories + CORS ready. User-story work can begin (in parallel if staffed).

---

## Phase 3: User Story 1 — Track and stage the projects I'm pursuing (Priority: P1) 🎯 MVP

**Goal**: From the feed (quick actions) and the detail view, favorite/set-status/tag/record-applied/won/lost/hide a project; the feed gains personal indicators + filters; the detail gains the controls + a status-changed timeline. One lazily-created record per project; scraped data untouched.

**Independent Test**: Seed projects; favorite/status/tag/applied/won/lost/hide from feed and detail; confirm a single record is created on first touch, the feed shows personal indicators and the new filters work, the detail timeline shows the last status change, hidden projects leave the active feed but persist, and no scraped project/client row changed.

### Tests for User Story 1 ⚠️

- [X] T015 [P] [US1] `tests/api/test_personal_api.py`: `GET .../personal` returns defaults when no record; `PATCH` creates-on-first-touch (single record) and sets favorite/status/tags/applied/won/lost/hidden; unknown status → 422; won_amount < 0 → 422; setting status=applied twice does not move `applied_at`; the favorite-toggle endpoint flips state; unauthenticated → 401.
- [X] T016 [P] [US1] `tests/api/test_projects_personal_filters.py`: `GET /api/projects` returns the personal projection defaulted when no record; `personal_status`, `favorites_only`, and `include_hidden` filters work and compose with Feature 2 filters; hidden excluded by default.

### Implementation for User Story 1

- [X] T017 [US1] In `src/mostaql_notifier/api/schemas.py`, add `PersonalRecord` + `PersonalUpdate` DTOs and extend `ProjectListItem` (favorite, personal_status, personal_status_label, tags, hidden) and `ProjectDetail` (embed `personal`) per contracts/openapi.yaml.
- [X] T018 [US1] Create `src/mostaql_notifier/api/routers/personal.py` (`GET`/`PATCH /api/projects/{id}/personal`, `POST /api/projects/{id}/personal/favorite`) delegating to `personal/service.py`; 404 if the project is missing; register the router (auth-gated) in `app.py`. Depends on T017, T009.
- [X] T019 [US1] Extend `src/mostaql_notifier/api/routers/projects.py`: LEFT JOIN `personal_records`, add the personal projection to `to_list_item`, add `personal_status`/`favorites_only`/`include_hidden` query params, and embed the `personal` record in `GET /api/projects/{id}`. Depends on T017, T009.
- [X] T020 [P] [US1] Create `frontend/components/personal/` — `FavoriteToggle`, `StatusSelect`, `TagEditor`, `OutcomeFields` (won/lost), `HideButton`, `ProjectRowMenu` (dropdown) — using the new UI primitives; status options come from config; bidi-safe Arabic.
- [X] T021 [P] [US1] Extend `frontend/lib/types.ts` (personal DTOs + `ProjectListItem`/`ProjectDetail` personal fields), `frontend/lib/api.ts` (get/patch personal, toggle favorite), and create `frontend/lib/usePersonal.ts` (mutations invalidating `["projects"]`, `["project", id]`, `["board"]`).
- [X] T022 [US1] Wire quick actions into the feed: show favorite + personal-status indicators and the `ProjectRowMenu` in `frontend/components/ProjectTable.tsx` and `ProjectCard.tsx`; add personal-status + favorites-only + show-hidden controls to `frontend/components/Filters.tsx` (+ `useProjects.ts` query state). Depends on T019, T020, T021.
- [X] T023 [US1] Add a personal-controls card + a status-changed timeline to `frontend/app/projects/[id]/page.tsx` (favorite, status, tags, applied date, won/lost outcome, hide). Depends on T019, T020, T021.
- [X] T024 [P] [US1] `frontend/components/__tests__/projectRowMenu.test.tsx`: renders the quick actions, lists status options from config, and invokes the mutation hooks.

**Checkpoint**: MVP — favorite/stage/tag/outcome/hide from feed + detail, one consistent record, scraped data read-only.

---

## Phase 4: User Story 2 — Keep notes and files per project (Priority: P2)

**Goal**: A per-project workspace: a markdown notes editor with preview, and drag-drop PDF/DOCX/MD uploads validated by type + size, listed with metadata, previewable (MD/PDF) or downloadable (DOCX/PDF), renamable/deletable, stored safely and never auto-deleted.

**Independent Test**: Open the workspace; write+save markdown (see preview); upload valid PDF/DOCX/MD (stored + listed); attempt an unsupported type and an oversized file (both rejected with a clear message, nothing stored); preview MD/PDF, download DOCX; rename and delete; restart the API and confirm survival; confirm files require auth and are not under a public path.

### Tests for User Story 2 ⚠️

- [X] T025 [P] [US2] `tests/api/test_attachments_api.py` (**security-critical**): valid PDF/DOCX/MD upload stored + listed with metadata; unsupported type → 400 (nothing stored); oversize → 413 (nothing stored); magic-byte mismatch (renamed extension) → rejected; duplicate/very-long/Arabic/unsafe-character filename safe-stored with the original retained for display and no traversal; download/preview/rename/delete require auth (401 unauth); delete removes both row and file.
- [X] T026 [P] [US2] `tests/unit/test_attachment_storage.py`: the storage layer validates ext + content-type + magic bytes + size, generates a safe `{uuid}.{ext}` stored name under `{attachments_dir}/{project_id}/`, and never derives a path from `original_name`.

### Implementation for User Story 2

- [X] T027 [US2] Create `src/mostaql_notifier/storage/attachments.py`: validate(file) → (type, size) against `upload_allowed_types`/`upload_max_bytes` with magic-byte sniffing (`%PDF-`, OOXML `PK\x03\x04`, UTF-8 text); `save` to `{attachments_dir}/{project_id}/{uuid}.{ext}`; `open_stream`/`delete`; resolve `attachments_dir` from `Secrets`. Depends on T002, T003.
- [X] T028 [US2] In `src/mostaql_notifier/api/schemas.py`, add `AttachmentItem` and `AttachmentListResponse` DTOs.
- [X] T029 [US2] Create `src/mostaql_notifier/api/routers/attachments.py`: `GET`/`POST /api/projects/{id}/attachments` (multipart upload → validate+store, 400/413/422 on failure with nothing stored), `PATCH /api/attachments/{aid}` (rename display name), `DELETE /api/attachments/{aid}` (row + file), `GET .../download` (FileResponse, `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`), `GET .../preview` (inline PDF / `text/markdown` body / 415 for DOCX); register the router (auth-gated) in `app.py`. Depends on T027, T028.
- [X] T030 [P] [US2] Create `frontend/components/workspace/` — `MarkdownEditor` (textarea + tabs preview via `react-markdown`+`remark-gfm`+`rehype-sanitize`), `FileDropzone` (drag-drop, client-side type/size hint), `FileList` (name/type/size/date + rename/delete), `FilePreviewDialog` (iframe for PDF, rendered MD, download for DOCX).
- [X] T031 [P] [US2] Extend `frontend/lib/api.ts` (attachments list/upload via `FormData`/rename/delete; build preview/download URLs), add `frontend/lib/useAttachments.ts` (list/upload/rename/delete + invalidation), and the attachment types in `frontend/lib/types.ts`.
- [X] T032 [US2] Add the workspace card to `frontend/app/projects/[id]/page.tsx`: the notes editor (saves through the personal `PATCH … {notes}`) + the file area (FileDropzone + FileList), with empty states for no-notes/no-files. Depends on T030, T031, T023.
- [X] T033 [P] [US2] `frontend/components/__tests__/markdownEditor.test.tsx`: preview renders markdown and **sanitizes** script/dangerous HTML; upload-rejection messages render for wrong-type/too-large.

**Checkpoint**: Workspace — markdown notes + validated, safely-stored, previewable/downloadable files that survive a restart.

---

## Phase 5: User Story 3 — Run my pipeline on a drag-and-drop board (Priority: P3)

**Goal**: A board with one column per status showing only engaged (favorited or moved-off-`new`), non-hidden projects; drag between columns to change status (into Applied records the date); reorder within a column to set priority; cards show title, hiring rate, budget+tier, bids, age, tags.

**Independent Test**: Engage several projects; open `/board`; confirm columns = configured statuses (incl. empty), only engaged non-hidden cards appear, dragging changes status (into Applied records today), reordering persists across reload, cards show the required fields, and rapid moves settle consistently.

### Tests for User Story 3 ⚠️

- [X] T034 [P] [US3] `tests/api/test_board_api.py`: `GET /api/board` returns columns in configured order including empty ones, only engaged non-hidden projects, and a fallback column for a removed-status key; `POST /api/board/move` changes status, records `applied_at` on →applied, persists `board_position`, is last-write-wins, 404s a missing project, and requires auth.

### Implementation for User Story 3

- [X] T035 [US3] In `src/mostaql_notifier/api/schemas.py`, add `BoardCard`, `BoardColumn`, `BoardResponse`, `BoardMoveRequest` DTOs.
- [X] T036 [US3] Create `src/mostaql_notifier/api/routers/board.py`: `GET /api/board` (engaged predicate `(favorite OR status≠default) AND NOT hidden`, grouped by configured status order with empty + fallback columns, ordered by `board_position`) and `POST /api/board/move` (via `service.move`, applied-once rule, last-write-wins); register the router (auth-gated) in `app.py`. Depends on T035, T009, T008.
- [X] T037 [P] [US3] Create `frontend/components/board/` — `Board`, `BoardColumn`, `BoardCard` — with `@dnd-kit` (`DndContext` + `SortableContext` + a keyboard sensor for FR-034); RTL-aware columns.
- [X] T038 [P] [US3] Create `frontend/lib/useBoard.ts` (board query + move mutation with optimistic update + invalidation), add board calls to `frontend/lib/api.ts`, and board types to `frontend/lib/types.ts`.
- [X] T039 [US3] Assemble `frontend/app/board/page.tsx` (board + loading/empty states) and add the "اللوحة" (Board) link to `frontend/components/Nav.tsx`. Depends on T037, T038.
- [X] T040 [P] [US3] `frontend/components/__tests__/board.test.tsx`: columns build from config, a card move invokes the move mutation, an empty column renders as a valid drop target.

**Checkpoint**: The drag-and-drop pipeline board works over the engaged subset.

---

## Phase 6: User Story 4 — Act from Telegram and control the watcher (Priority: P4)

**Goal**: Inline action buttons on each project notification (Favorite/Applied/Dismiss/Add note/Open) that update the same record idempotently and confirm; bot commands `/find /pause /resume /health /stats`; a dashboard pause mirror.

**Independent Test**: Trigger a notification with the five buttons; tap each (Favorite toggles, Applied sets status+date, Dismiss hides, Add note saves typed text, Open links out) and confirm the message updates; double-tap / old-message are harmless; run each command (`/find` matches+links, `/pause`→`/resume` stop/restart polling next cycle, `/health` status+counts+paused, `/stats` today + per-stage); confirm a Telegram action shows on the dashboard.

### Tests for User Story 4 ⚠️

- [X] T041 [P] [US4] `tests/unit/test_telegram_keyboard.py`: `build_project_keyboard` emits Favorite/Applied/Dismiss/Add-note callbacks + an Open URL button; the `pf:{action}:{id}` callback_data round-trips and parses; data stays ≤ 64 bytes.
- [X] T042 [P] [US4] `tests/unit/test_inbound_bot.py`: updates from a non-owner chat are ignored; callbacks call the service (fav toggles, applied sets status+date, dismiss hides, add-note appends), are idempotent on repeat/old-message, and the commands `/find /pause /resume /health /stats` produce the expected effects/replies (with a fake bot/update).
- [X] T043 [P] [US4] `tests/api/test_control_api.py` + `tests/integration/test_pause_resume.py`: `GET /api/control` + `POST /pause|resume` flip `watcher_paused`; `HomeOverview.paused` reflects it; the worker poll cycle **skips quietly when paused** (no `scrape_run` row written).

### Implementation for User Story 4

- [X] T044 [US4] In `src/mostaql_notifier/notify/format.py`, add `build_project_keyboard(project)` (the five buttons; Open → `project.url`); extend `src/mostaql_notifier/notify/telegram.py` `_send`/`send_project_notification` to accept and pass `reply_markup` (dedup/`notified` flow unchanged).
- [X] T045 [US4] In `src/mostaql_notifier/worker/poll.py`, add the `watcher_paused` gate (read the settings flag each cycle; when paused, skip the cycle without writing a `scrape_run`), placed alongside the existing circuit-breaker short-circuit.
- [X] T046 [US4] Create `src/mostaql_notifier/api/routers/control.py` (`GET /api/control`, `POST /api/control/pause|resume` flipping `watcher_paused`), add the `ControlState` schema, extend `HomeOverview` (+ `home.py`) with `paused`, and register the control router (auth-gated) in `app.py`.
- [X] T047 [US4] Create the bot package `src/mostaql_notifier/bot/` — `__main__.py` (`run()` long-poll entrypoint), `app.py` (Application builder + owner-chat authz + lifecycle), `callbacks.py` (`pf:*` → service, answer + edit-to-confirm, idempotent), `commands.py` (`/find /pause /resume /health /stats` via service + `personal/stats.py`), `conversation.py` (add-note force-reply → append notes). Depends on T009, T010, T008.
- [X] T048 [P] [US4] Create `frontend/components/PauseControl.tsx` (toggle bound to `/api/control`) and surface the paused state on `frontend/app/page.tsx` (and the board header); add control calls to `frontend/lib/api.ts`.
- [X] T049 [P] [US4] Add a `bot` service to `deploy/docker-compose.yml` (reuse `Dockerfile.api`, `command: mostaql-notifier-bot`, shared `../data` volume, `restart: unless-stopped`) and create `deploy/mostaql-notifier-bot.service` (systemd unit sibling of the worker).

**Checkpoint**: Telegram quick actions + commands + pause/resume, all converging on the same record/flag as the dashboard.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final quality pass, gates, and verification.

- [X] T050 [P] Update `scripts/ci.sh` so `ruff check` and `pytest` cover the new `src/mostaql_notifier/{personal,storage,bot}` packages and new test files, confirm `alembic upgrade head` includes the new migration, and the frontend `lint && test && build` picks up the new deps.
- [X] T051 [P] Verify `.env.example` documents `ATTACHMENTS_DIR`, `.gitignore` ignores `data/attachments/`, and add a backup note (DB **and** attachments dir) to `specs/003-personal-pipeline-workspace/quickstart.md` / project README.
- [X] T052 RTL + bidi sweep across the new surfaces (tags, notes + preview, file display names, board cards, Arabic status labels, long/mixed strings) — fixes in `frontend/`.
- [X] T053 Empty / loading / error state audit for the new surfaces: empty board columns, a project with no notes/files, upload-rejection messaging, and backend-unreachable on the board/workspace — in `frontend/app/` + `frontend/components/`.
- [X] T054 Run the `quickstart.md` smoke checks end-to-end (SC-001…SC-010): cross-surface single-record consistency, upload accept/reject, board move + applied date + reorder persistence, pause/resume, hide non-destructive, Arabic RTL, and idempotent Telegram actions.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; **blocks all user stories** (tables + migration + status config + personal service).
- **User Stories (Phase 3–6)**: each depends only on Foundational; independent of one another after that (US2's workspace card and US4's pause mirror sit on pages US1 introduces, but each story's backend + core UI is testable alone).
- **Polish (Phase 7)**: depends on the desired stories being complete.

### User-story independence

- **US1 (P1)**: after Foundational — the MVP; no dependency on US2–US4.
- **US2 (P2)**: after Foundational — storage + attachments API are standalone; the workspace card lands on the US1 detail page (build US1 first for the combined demo, but the API/storage are independently tested).
- **US3 (P3)**: after Foundational — board API + page are standalone (reuse `service.move`).
- **US4 (P4)**: after Foundational — bot + buttons + control reuse the service/flag; no UI dependency beyond the small PauseControl.

### Within each story

- Tests before implementation; schema/DTOs before the router; the router (endpoint) before the screen that consumes it; `[P]` component pieces before screen assembly.

### Parallel opportunities

- **Setup**: T001–T005 all parallel.
- **Foundational**: T008, T010, T011, T012 parallel; T009 after T008; T013/T014 after T008/T009.
- Once Foundational is done, **US1, US2, US3, US4 can be built in parallel** by different developers.
- **Within US1**: T015, T016 (tests) parallel; T020, T021 (frontend) parallel; then T022, T023.
- **Within US2**: T025, T026 (tests) parallel; T030, T031 (frontend) parallel after T027–T029.
- **Within US4**: T041, T042, T043 (tests) parallel; T044, T045, T046, T047 are mostly different files (T046 + T047 both read the settings flag but in different modules).

---

## Parallel Example: User Story 2 (the heaviest slice)

```bash
# Security tests first (parallel):
Task: "Attachment API security test in tests/api/test_attachments_api.py"
Task: "Storage-layer validation test in tests/unit/test_attachment_storage.py"

# Backend (storage → schema → router), then frontend pieces in parallel:
Task: "Workspace components in frontend/components/workspace/ (MarkdownEditor, FileDropzone, FileList, FilePreviewDialog)"
Task: "useAttachments hook + api client + types in frontend/lib/"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational (tables + migration + status config + **personal service**, all unit-tested) → 3. Phase 3 US1 → **STOP & validate**: favorite/stage/tag/outcome/hide from feed + detail, one consistent record. Demo.

### Incremental delivery

Foundation → US1 (MVP CRM) → US2 (workspace notes + files) → US3 (board) → US4 (Telegram + control), each tested and demoable independently, then Polish (CI, docs, RTL/state sweep, quickstart validation).

### Parallel team strategy

After Foundational: Dev A → US1, Dev B → US2 (storage/uploads), Dev C → US3 (board), Dev D → US4 (bot + control). The shared `personal/service.py` is frozen at the end of Foundational so stories don't contend on it.

---

## Notes

- `[P]` = different files, no dependency on an incomplete task.
- The Python schema (`db/models.py`) stays the single source of truth; the two new tables are added by **one Alembic migration**, and the new tunables are additive `settings` rows.
- **One record per project** is structural (PK = `project_id`); both the API and the bot mutate **only** through `personal/service.py` (FR-029, SC-006).
- **Non-destructive** (Constitution IV): no task deletes/overwrites personal data via automation; only owner-initiated endpoints/bot actions delete.
- **Upload safety** (Constitution IX): validate type+magic+size, UUID storage names outside any web path, gated streaming with `nosniff`, never executed.
- **No platform automation** (Constitution VIII): `/pause`·`/resume` toggle only our polling flag; "Open" is a link.
- Reminder: extend CORS to allow `PATCH`/`DELETE` (T012) and add `python-multipart` (T001) — both are easy-to-miss prerequisites for the new routers.
