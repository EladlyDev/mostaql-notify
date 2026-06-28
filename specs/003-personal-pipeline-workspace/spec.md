# Feature Specification: Personal Pipeline and Workspace

**Feature Branch**: `003-personal-pipeline-workspace`  
**Created**: 2026-06-25  
**Status**: Draft  
**Input**: User description: "Mostaql Notifier — Feature 3: the personal pipeline and workspace. Add the owner's personal layer on top of the read-only watcher and dashboard: track which projects I care about, what stage each is at, tag them, record applied dates and outcomes, keep markdown notes and uploaded files per project, and run a drag-and-drop pipeline board — all surfaced both in the dashboard and through quick actions and bot commands on the Telegram notifications I already receive. This is the first feature that writes project data of my own."

## User Scenarios & Testing *(mandatory)*

This feature adds the owner's **personal layer** on top of Features 1 (the watcher) and 2 (the read-only
dashboard). It is the first feature that writes the owner's own project data. The personal layer is kept
strictly separate from the watcher's scraped facts: nothing the owner does here ever creates, edits, or
deletes a scraped project or client record. A project carries no personal data until the owner first
interacts with it; that first interaction lazily creates a single personal record for the project, which
every surface (feed, detail, workspace, board, and Telegram) then reads and writes consistently. Per the
project constitution, none of the owner's personal data — favorites, statuses, tags, applied dates,
outcomes, notes, files, or board order — is ever deleted or overwritten by automation; only the owner
deletes it, and all of it is backed up.

The four parts below are independently valuable and are prioritized as four user stories. User Story 1
(the CRM core) is the foundation: it owns the single personal record that User Stories 2, 3, and 4 all
read and write. Each later story is an additional surface or capability over that record and can be built,
tested, and demonstrated on its own.

### User Story 1 - Track and stage the projects I'm pursuing (Priority: P1)

As the sole owner, from the projects feed (per-row quick actions) and from a project's detail view, I mark
a project as a favorite, set its personal status from a configurable set (default: New, Interested,
Applied, In Discussion, Won, Lost, Ignored), add free-form tags, record the date I applied, record a won
amount when I mark it Won and a reason when I mark it Lost, and hide a project to remove it from my active
view without deleting anything. A project I have never touched is treated as status "New" and not a
favorite, and gains its own personal record the first moment I act on it. The projects feed grows a
personal-status indicator and a favorite indicator, filters for personal status and favorites-only, and
per-row quick actions (favorite, set status, hide); the detail view grows the same controls plus a small
timeline of when the status last changed. Nothing I do here changes the scraped project or client facts.

**Why this priority**: This is the foundation of the whole feature — it defines and owns the single
personal record per project that the workspace, the board, and the Telegram actions all read and write.
With only this story, the owner can already favorite, stage, tag, and record outcomes for every collected
project, replacing the external spreadsheet. It is the MVP.

**Independent Test**: Seed the database with collected projects. From the feed and the detail view,
favorite a project, set its status, add and remove tags, set it to Applied (and confirm the applied date
is recorded), set another to Won (record an amount) and another to Lost (record a reason), and hide one.
Confirm that: a single personal record is created on first interaction and not before; the feed shows the
personal-status and favorite indicators and the new filters work; the detail timeline shows when the
status last changed; hidden projects leave the active feed but remain stored and retrievable; and no
scraped project or client record was created, modified, or deleted by any of these actions.

**Acceptance Scenarios**:

1. **Given** a project I have never touched, **When** I favorite it from the feed, **Then** a personal record is created for it, it shows as favorited, and its scraped fields are unchanged.
2. **Given** a project with no personal record, **When** I view it in the feed, **Then** it displays as status "New" and not-favorited without yet having a stored record.
3. **Given** a project, **When** I set its personal status (e.g. to Interested) from a feed quick action or the detail view, **Then** the status indicator updates and the change is timestamped.
4. **Given** a project, **When** I add free-form tags and later remove one, **Then** the tag set updates and persists.
5. **Given** a project, **When** I set its status to Applied, **Then** today's date is recorded as the applied date if none was already set.
6. **Given** a project, **When** I set its status to Won and enter a won amount, **Then** the amount is saved; **and When** I set another to Lost and enter a reason, **Then** the reason is saved.
7. **Given** a project, **When** I hide/dismiss it, **Then** it is removed from the active feed and board but no data is deleted and I can still find it via a "show hidden" filter and restore it.
8. **Given** any personal action above, **When** it completes, **Then** no scraped project or client record is created, modified, or deleted.
9. **Given** a project whose status I have changed, **When** I open its detail view, **Then** I see a small timeline indicating when the status last changed.
10. **Given** the feed, **When** I filter by personal status or enable favorites-only (alone or combined with the existing Feature 2 filters), **Then** only matching projects are shown.

---

### User Story 2 - Keep notes and files per project (Priority: P2)

As the owner, each project has its own workspace where I write and edit notes in a markdown editor with a
rendered preview, and attach files by dragging and dropping them in. Only PDF, DOCX, and Markdown files are
accepted; every upload is validated by type and by a configurable maximum size and rejected with a clear
message if it fails. I see every file for the project listed with its name, type, size, and upload date; I
can rename or delete any of them and attach as many as I like. I preview Markdown and PDF files inline and
download DOCX and PDF files. My notes and files persist, are part of the backup, and are never deleted by
any automated process — only I delete them.

**Why this priority**: Notes and working files are central to "everything about an opportunity lives in one
place." The workspace builds on the personal record from User Story 1 but is an independent, separately
testable surface that delivers immediate value on its own.

**Independent Test**: Open a project's workspace. Write and save markdown notes and confirm the rendered
preview. Drag in a valid PDF, a valid DOCX, and a valid Markdown file and confirm each is stored and listed
with name, type, size, and upload date. Attempt an unsupported type and an oversized file and confirm each
is rejected with a clear, specific message and nothing is stored. Preview a Markdown and a PDF inline;
download a DOCX and a PDF. Rename and delete a file. Restart the application and confirm notes and files
survive. Confirm files are not reachable from any public path and require authentication, and that running
an automated watcher cycle never removes them.

**Acceptance Scenarios**:

1. **Given** a project, **When** I write markdown notes and save, **Then** they persist and a rendered preview shows the formatting.
2. **Given** the workspace, **When** I drag in a valid PDF, DOCX, or Markdown file within the size limit, **Then** it is stored and appears in the file list with its name, type, size, and upload date.
3. **Given** the workspace, **When** I try to upload a file of an unsupported type (e.g. an image, archive, or executable), **Then** it is rejected with a clear "unsupported type" message and nothing is stored.
4. **Given** the workspace, **When** I try to upload a file larger than the configured maximum size, **Then** it is rejected with a clear "too large" message and nothing is stored.
5. **Given** an uploaded Markdown or PDF file, **When** I preview it, **Then** it renders inline; **and Given** an uploaded DOCX or PDF, **When** I download it, **Then** I receive the original file.
6. **Given** several files on a project, **When** I rename or delete one, **Then** the change is reflected and only my (owner-initiated) delete removes a file.
7. **Given** an upload whose name is a duplicate, very long, written in Arabic, or contains unsafe characters, **When** it is stored, **Then** the original name is preserved for display while the stored file uses a safe, non-colliding, non-traversable name.
8. **Given** notes and files exist on a project, **When** the application or watcher restarts or an automated cycle runs, **Then** the notes and files are intact (never auto-deleted) and are included in the backup set.
9. **Given** a file preview or download endpoint, **When** an unauthenticated request reaches it, **Then** it is refused; files are never served from a public web path and are never executed.

---

### User Story 3 - Run my pipeline on a drag-and-drop board (Priority: P3)

As the owner, I open a board view with one column per personal status and see the projects I am actively
pursuing as cards grouped under their current status. The board shows only projects I have engaged with —
favorited or moved off the default "New" status — not every scraped project, and not the ones I have
hidden. I drag a card from one column to another to change its status; moving a card into "Applied"
automatically records today as the applied date. I drag cards to reorder them within a column to set my own
priority, and that order persists. Each card shows enough to be useful at a glance: title, client hiring
rate, budget and tier, bid count, age, and any tags.

**Why this priority**: The drag-and-drop board is the headline "run my freelancing pipeline" experience. It
re-presents and manipulates the same personal record that User Story 1 owns, so it depends on that story,
but it adds high-value pipeline-management interaction that the feed alone does not provide.

**Independent Test**: Engage several projects (favorite some, set various statuses). Open the board and
confirm: there is one column per personal status; only engaged, non-hidden projects appear; dragging a card
to another column changes its status; dragging a card into "Applied" records today as the applied date;
reordering cards within a column persists across a reload; each card shows title, hiring rate, budget and
tier, bid count, age, and tags; empty columns render as valid drop targets; and several quick moves in
succession settle to a single consistent final state.

**Acceptance Scenarios**:

1. **Given** projects I have engaged with, **When** I open the board, **Then** I see one column per personal status with each engaged project as a card under its current status.
2. **Given** a project I have never touched (status New, not favorited) or one I have hidden, **When** I view the board, **Then** it does not appear on the board.
3. **Given** a card, **When** I drag it from one column to another (e.g. Interested → Applied), **Then** its personal status changes accordingly, and moving into "Applied" records today as the applied date if none was already set.
4. **Given** a column with several cards, **When** I drag cards to reorder them, **Then** the new order persists across reloads.
5. **Given** a card, **When** I look at it, **Then** it shows the project title, client hiring rate, budget and tier, bid count, age, and any tags.
6. **Given** a status with no engaged projects, **When** the board renders, **Then** that column appears as an empty, clearly-labeled drop target without error.
7. **Given** I make several reorder and status changes in quick succession, **When** they settle, **Then** the final state is consistent (the last action wins) with no duplicated, lost, or orphaned cards.
8. **Given** cards with Arabic titles and tags, **When** they render, **Then** they display correctly right-to-left.
9. **Given** I am using a keyboard, **When** I move a card to a different column or position, **Then** I can change its status and order without a pointing device.

---

### User Story 4 - Act from Telegram and control the watcher (Priority: P4)

As the owner, the project notifications I already receive in Telegram gain inline action buttons —
Favorite, Applied, Dismiss, Add note, and Open — so I can act on a project the moment it arrives. Tapping a
button updates my single personal record for that project: Favorite toggles the favorite flag; Applied sets
the status to Applied and records the applied date; Dismiss hides the project; Add note prompts me to type a
note that is saved to the project; Open just gives me the direct link to the project on Mostaql. After I
tap, the message updates to confirm the new state, and tapping the same thing twice (or tapping an old
notification) does no harm. I also get bot commands: `/find <keyword>` searches my tracked projects and
replies with the top matches and their links; `/pause` pauses the watcher's polling and `/resume` resumes
it; `/health` replies with the last scrape's status and counts; and `/stats` replies with basic figures —
found and qualified today, totals, and how many projects sit in each pipeline stage.

**Why this priority**: Acting the moment a project arrives, and controlling the watcher from chat, is a
high-convenience surface — but it operates on the same personal record the dashboard already manages, so it
is sequenced last. It also depends on User Story 1's record semantics and on the existing Feature 1 Telegram
channel and watcher loop.

**Independent Test**: Trigger a project notification and confirm it carries the five inline buttons. Tap
each and confirm the personal record updates correctly (Favorite toggles; Applied sets status and applied
date; Dismiss hides; Add note saves typed text; Open returns the Mostaql link with no state change) and the
message updates to confirm. Tap the same button twice and tap a button on an old notification, confirming
both are harmless. Run each command and confirm: `/find` returns the top matching tracked projects with
links; `/pause` then `/resume` stop and restart the watcher's polling on its next cycle; `/health` returns
the last scrape's status and counts; `/stats` returns today's found/qualified, totals, and per-stage
counts. Finally, confirm an action taken in Telegram is reflected on the same record in the dashboard, and
vice versa.

**Acceptance Scenarios**:

1. **Given** a project notification, **When** it arrives, **Then** it shows inline buttons: Favorite, Applied, Dismiss, Add note, and Open.
2. **Given** the notification, **When** I tap Favorite, **Then** the project's personal record toggles its favorite flag and the message updates to confirm the new state.
3. **Given** the notification, **When** I tap Applied, **Then** the status becomes Applied, the applied date is recorded (if not already set), and the message confirms.
4. **Given** the notification, **When** I tap Dismiss, **Then** the project is hidden (removed from the active feed and board) and the message confirms.
5. **Given** the notification, **When** I tap Add note and type text, **Then** the text is saved to that project's notes and the message confirms.
6. **Given** the notification, **When** I tap Open, **Then** I receive the direct link to the project on Mostaql and no personal state changes.
7. **Given** any of the buttons, **When** I tap it twice or tap it on an old notification, **Then** the end state is the same as a single tap and nothing breaks (the action is idempotent).
8. **Given** `/find <keyword>`, **When** I send it, **Then** I receive the top matching tracked projects with their links (or a friendly "no matches" reply).
9. **Given** `/pause` and later `/resume`, **When** the watcher next cycles, **Then** it stops polling after `/pause` and resumes after `/resume`, and issuing the same command twice is harmless.
10. **Given** `/health`, **When** I send it, **Then** I receive the last scrape's status and its found / new / updated / error counts.
11. **Given** `/stats`, **When** I send it, **Then** I receive how many projects were found and qualified today, the totals, and the count of projects in each pipeline stage.
12. **Given** an action I took in Telegram, **When** I open the dashboard (or vice versa), **Then** the same single personal record reflects it on both surfaces.

---

### Edge Cases

- **No personal record yet**: Any action from any surface (feed, detail, workspace, board, or Telegram) on a project with no personal record creates that record atomically as part of the action, defaulting unset fields (status "New", not favorited, no tags).
- **Same project acted on from both surfaces**: Acting from Telegram and the dashboard on the same project converges on one personal record; concurrent or rapid actions resolve last-write-wins with no duplicate or conflicting records.
- **Rejected uploads**: Wrong-type and oversized uploads are rejected with a clear, specific message; nothing is stored and the existing file list and notes are unchanged.
- **Problematic filenames**: Duplicate, very long, Arabic, or unsafe-character filenames are stored under a safe, non-colliding, non-traversable name while the original name is preserved for display; no filename can escape the configured storage location.
- **Rapid board changes**: Reordering and status changes in quick succession settle to a single consistent final state without losing or duplicating cards.
- **Telegram replays**: A button tapped more than once, or tapped on an old/expired notification, is handled gracefully and idempotently (a confirming or "already done" response, never an error or a double effect).
- **Empty states**: Empty board columns, and projects with no notes and no files, render clear, valid empty states rather than errors.
- **Hidden then acted on**: A hidden project remains hidden until the owner explicitly restores it; other actions (e.g. a status change recorded via Telegram) update the record without silently un-hiding it, and the owner can always find and restore hidden projects.
- **Status set changed in configuration**: If the configured status set changes (a stage renamed or removed) while records hold an old value, existing records keep their stored status and surface in a clearly-labeled fallback rather than disappearing (non-destructive).
- **Invalid outcome input**: A non-numeric or negative won amount, or an empty lost reason, is rejected with a clear message and not saved.
- **Unreadable file preview**: Previewing a corrupt or unreadable file degrades to a clear message or a download offer rather than crashing.
- **Watcher already paused/running**: `/pause` when already paused and `/resume` when already running are harmless no-ops with a clear reply.
- **Pause visibility**: While the watcher is paused, its paused state is discoverable (e.g. via `/health`) so the owner can tell the system is intentionally idle rather than broken.

## Requirements *(mandatory)*

### Functional Requirements

#### Personal record & CRM core (Part A)

- **FR-001**: The system MUST maintain exactly one personal record per project, created lazily on the owner's first interaction with that project (favorite, status change, tag, applied/outcome, note, file, hide, or board move). A project with no personal record MUST be treated as status "New" and not-favorited.
- **FR-002**: The owner MUST be able to toggle a project's favorite flag on and off from both the projects feed (per-row quick action) and the project detail view.
- **FR-003**: The owner MUST be able to set a project's personal status to any value in the configurable status set (default: New, Interested, Applied, In Discussion, Won, Lost, Ignored) from feed quick actions and the detail view.
- **FR-004**: The owner MUST be able to add and remove free-form tags/labels on a project.
- **FR-005**: The owner MUST be able to record an applied date for a project; transitioning a project's status into "Applied" (from any surface) MUST record today's date as the applied date when no applied date is already set, and MUST NOT overwrite an existing applied date.
- **FR-006**: When a project's status is "Won", the owner MUST be able to record a won amount; when it is "Lost", the owner MUST be able to record a lost reason. Won amount MUST be validated as a non-negative number.
- **FR-007**: The owner MUST be able to hide/dismiss a project, which removes it from the active feed and the board without deleting any data; hidden projects MUST remain stored, discoverable via a "show hidden" filter, and restorable.
- **FR-008**: Status changes MUST be timestamped, and the detail view MUST show a small timeline indicating at least when the status last changed.
- **FR-009**: The projects feed MUST gain a personal-status indicator, a favorite indicator, filters for personal status and favorites-only (combinable with the existing Feature 2 filters), per-row quick actions (favorite, set status, hide), and MUST exclude hidden projects from the active view by default while offering a way to view them.
- **FR-010**: The personal layer MUST be entirely separate from the watcher's scraped data; no personal action MUST ever create, modify, or delete any scraped project or client record.

#### Workspace: notes & files (Part B)

- **FR-011**: Each project MUST have a workspace providing a markdown notes editor with a rendered preview; notes MUST persist on the project's personal record.
- **FR-012**: The owner MUST be able to attach files to a project by drag-and-drop, and MUST be able to attach multiple files per project.
- **FR-013**: The system MUST accept only the configured allowed file types (default: PDF, DOCX, Markdown) and MUST validate every upload by type and against a configurable maximum size, rejecting a failing upload with a clear, specific message and storing nothing.
- **FR-014**: The workspace MUST list every file for a project showing its name, type, size, and upload date, and MUST let the owner rename or delete any file.
- **FR-015**: The system MUST let the owner preview Markdown and PDF files inline and download DOCX and PDF files, returning the original file content on download.
- **FR-016**: Uploaded files MUST be stored outside any public web path, in a configurable storage location, served only to the authenticated owner, referenced by safe (sanitized, non-traversable) storage names, and MUST never be executed; the original filename MUST be retained for display.
- **FR-017**: Notes and uploaded files MUST be retained, included in backups, and MUST NEVER be deleted or overwritten by any automated process; only owner-initiated deletion removes them.

#### Pipeline board: Kanban (Part C)

- **FR-018**: The board MUST present one column per personal status (from the configurable set) and place each engaged project as a card under its current status.
- **FR-019**: The board MUST show only engaged projects — those that are favorited or have been moved off the default "New" status — and MUST exclude untouched and hidden projects.
- **FR-020**: Dragging a card to another column MUST change that project's personal status; moving a card into "Applied" MUST record today's applied date per FR-005.
- **FR-021**: Reordering cards within a column MUST set and persist the owner's manual priority order for that column.
- **FR-022**: Each card MUST show the project title, client hiring rate, budget and tier, bid count, age, and any tags.
- **FR-023**: Rapid successive reorder and status changes MUST resolve to a single consistent final state (last action wins) without duplicating, losing, or orphaning cards, and empty columns MUST render as valid, clearly-labeled drop targets.

#### Telegram quick actions & commands (Part D)

- **FR-024**: Each project notification MUST include inline action buttons: Favorite, Applied, Dismiss, Add note, and Open (a direct link to the project on Mostaql).
- **FR-025**: Tapping an action MUST update the same single personal record: Favorite toggles the favorite flag; Applied sets status to Applied and records the applied date; Dismiss hides the project; Add note prompts for text and saves it to the project's notes; Open returns the Mostaql link and changes no personal state.
- **FR-026**: After an action, the notification message MUST update to confirm the new state, and repeating the same action (including on an old or expired notification) MUST be idempotent and harmless.
- **FR-027**: The bot MUST support these commands: `/find <keyword>` (search the owner's tracked projects and reply with the top matches and their links), `/pause` (pause the watcher's polling), `/resume` (resume polling), `/health` (reply with the last scrape's status and its found/new/updated/error counts), and `/stats` (reply with projects found and qualified today, the totals, and the count of projects in each pipeline stage).
- **FR-028**: `/pause` and `/resume` MUST control the watcher's polling through shared configuration/state that the watcher honors on its next cycle; neither the bot nor the dashboard MUST perform any scrape or any write action on mostaql.com itself.

#### Cross-cutting: consistency, configuration, presentation & safety

- **FR-029**: Actions from Telegram and from the dashboard MUST converge on one personal record per project, keeping the two surfaces consistent with no duplicate or conflicting records.
- **FR-030**: All owner-authored content — tags, notes (including rendered preview), and uploaded-file display names — MUST render right-to-left for Arabic and correctly handle mixed Arabic / Latin / digit content.
- **FR-031**: Every configurable value introduced by this feature — the status set and its labels, the allowed file types, the maximum upload size, and the storage location — MUST be read from configuration and MUST NOT be hard-coded.
- **FR-032**: All personal data — favorites, statuses, tags, applied dates, outcomes, notes, files, and board order — MUST NEVER be deleted by automation; only owner-initiated deletion removes it, and all of it MUST be included in backups.
- **FR-033**: Every personal-layer screen and every file preview/download endpoint MUST sit behind the dashboard's existing authentication; personal data and files MUST never be served to an unauthenticated requester.
- **FR-034**: The board and all controls MUST be clean, fast, and responsive on phone and laptop, and MUST be keyboard-operable, including a keyboard-accessible alternative to drag-and-drop for changing a card's status and order.
- **FR-035**: The personal record MUST include a reminder date field that is stored but inert in this feature — nothing reads it to drive behavior or notifications (reserved for a later feature).

### Constitutional Alignment *(how this feature honors the gates)*

This feature touches owner-data storage, notifications, and file uploads, so per the constitution it states
explicitly how it honors the relevant gates:

- **I. Personal & Single-Box**: The personal layer serves only the owner; there is no second user, role, or sharing surface. Authorization reuses Feature 2's single-owner password gate (FR-033).
- **III. Config Over Code**: The status set and labels, allowed file types, maximum upload size, and storage location are all read from configuration (FR-031).
- **IV. Idempotent Ingestion & Non-Destructive History**: One personal record per project (FR-001, FR-029); automation never deletes or overwrites owner data, and notes/files/statuses/tags are retained and backed up (FR-017, FR-032); a configuration change to the status set never erases stored statuses (Edge Cases).
- **V. Arabic-First Correctness**: Tags, notes, and filenames render right-to-left and handle mixed Arabic/Latin/digit content (FR-030); dates are stored in UTC and shown in the owner's timezone (Assumptions).
- **VI. Fail Loud**: `/health` and `/stats` expose run status, counts, and the watcher's paused/running state so the owner can always tell the system's state from chat (FR-027, Edge Cases); Telegram delivery remains at-least-once with deduplication and idempotent actions (FR-026).
- **VIII. No Platform Automation**: The only action on the platform is the owner following the "Open" link; `/pause`, `/resume`, and all quick actions write only to the owner's local data and the watcher's polling state — never to mostaql.com (FR-025, FR-028).
- **IX. Local Security Hygiene**: Uploads are validated by type and size, stored outside any public web path with safe non-traversable names, served only to the authenticated owner, and never executed (FR-013, FR-016, FR-033).
- **X. Deployment-Portable**: The attachment storage location is configurable and its contents are part of the portable, restorable backup set (FR-031, FR-032), with no machine-specific assumptions.

### Out of Scope (built in later features)

The following are explicitly NOT part of this feature and MUST NOT be built here:

- The opportunity score and anything that depends on it — including a score-breakdown action, a top-by-score command, and a score-threshold command.
- Re-checking projects over time, and any automatic status change driven by a project closing (e.g. auto-flagging a missed project). The only automatic record in this feature is setting the applied date when a project moves into "Applied".
- Digests, tiered delivery, and quiet hours.
- Analytics, heatmaps, funnels, and the tips engine.
- Reminders / follow-up surfacing and any notification driven by the reminder date — the field exists (FR-035) but nothing acts on it yet.
- Bulk multi-select actions.
- The clients directory, watchlist, and blacklist.
- Multiple saved searches and additional categories.
- Any in-app editor for the status set itself (the set is configuration-driven this feature; editing it is done in configuration, not through a dedicated UI).

### Key Entities

- **Personal Project Record**: The owner's layer for one project. Attributes: favorite flag; personal status (a value from the configurable status set); tags (free-form labels); applied date; won amount; lost reason; notes (markdown); board position (manual order within a status column); hidden/dismissed flag; the time the status last changed; and a reminder date (reserved, inert this feature). Exactly one per project, created lazily on first interaction, keyed to the project. Owner-owned and never auto-deleted.
- **Attachment**: A file the owner uploaded for a project. Attributes: original filename (for display), file type (PDF / DOCX / Markdown), size, the safe storage reference/path, and the upload timestamp. Many attachments per project. Owner-owned, retained, backed up, and never auto-deleted.
- **Personal Status**: The configurable set of pipeline stages (default: New, Interested, Applied, In Discussion, Won, Lost, Ignored) and their labels. Defines the board's columns and the feed's status filter. Read from configuration.
- **Project** *(existing, read-only here)*: The collected Mostaql project. The personal record attaches to it; the personal layer never writes to it. Card fields (title, hiring rate via client, budget, tier, bid count, age) and the Mostaql link are read from it.
- **Client** *(existing, read-only here)*: The project's poster; its hiring rate is shown on board cards and in the feed. Never written by this feature.
- **Scrape Run** *(existing, read-only here)*: One watcher poll cycle's record; drives `/health` and `/stats` counts.
- **Watcher Polling State** *(shared with the watcher)*: The paused/running state that `/pause` and `/resume` set and the watcher honors on its next cycle. Not a scrape or platform write.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From either the dashboard or a Telegram button, the owner can favorite a project, set its stage, tag it, and record that they applied and what it was worth, and the resulting single personal record is identical across both surfaces within one refresh.
- **SC-002**: The owner can open any project, write markdown notes, and drag in a PDF, DOCX, or Markdown file; the file is validated, stored, listed with its metadata, and either previewable or downloadable, and both notes and file survive an application restart.
- **SC-003**: The owner can run the pipeline on the board — move a card to a new stage (its status updates), have moving it into "Applied" record the date, and reorder cards to set priority — and the new stage and order persist across a reload.
- **SC-004**: From Telegram, the owner can act on a freshly-arrived project (favorite, applied, dismiss, add note) and pause/resume the watcher and check its health and stats, and those effects appear in the dashboard.
- **SC-005**: A disallowed or oversized file is rejected 100% of the time with a clear message and nothing is stored, and no personal data is ever lost to an automated process (verified by running watcher cycles and confirming personal data and files are unchanged).
- **SC-006**: There is never more than one personal record per project: acting on the same project from both Telegram and the dashboard never creates a duplicate or a conflicting record.
- **SC-007**: Arabic content — project titles, tags, notes, and uploaded-file display names — renders correctly right-to-left across the feed, detail view, workspace, and board, including mixed Arabic/Latin/digit strings.
- **SC-008**: Tapping a Telegram action twice, or tapping it on an old notification, produces exactly the same end state as a single tap, with a confirming response and no error or double effect.
- **SC-009**: Empty board columns and projects with no notes or files present clear, valid empty states with no errors.
- **SC-010**: Hiding/dismissing a project removes it from the active feed and the board while leaving its personal record, notes, and files fully intact and restorable.

## Assumptions

- **Builds on Features 1 and 2**: This feature reuses the existing local database, settings/configuration store, dashboard application shell, owner authentication/session, projects feed and project detail (extended here), the Telegram bot/notification channel, and the watcher's polling loop. No new project/client data model is introduced; the personal layer is added alongside.
- **Single user, single box** (Principle I): The personal layer is owner-only; "authentication" is Feature 2's single shared password gate, not an account system. There is no multi-user, sharing, or role surface.
- **One record per project, created lazily**: The personal record is one-to-one with a project, keyed by the project's identity; absence of a record means status "New" and not-favorited, and the first owner action creates it.
- **Status set is configuration-driven**: The status set and its labels live in configuration and default to the seven named stages; this feature does not include a dedicated in-app editor for the status set (changing it is a configuration change, per Principle III). If a status is later removed or renamed, existing records keep their stored value and surface in a clearly-labeled fallback rather than disappearing.
- **Hide/dismiss is distinct from the "Ignored" status**: Hiding is a separate flag that removes a project from the active feed and board regardless of its status; "Ignored" is just one of the pipeline statuses. A hidden project stays hidden until the owner restores it.
- **Board engagement rule**: A project appears on the board if and only if it is favorited or its status is not the default "New", and it is not hidden.
- **Applied date semantics**: The applied date is set to today on the first transition into "Applied" from any surface (feed, detail, board, or Telegram) and is not overwritten if one already exists.
- **Outcome fields**: Won amount is an owner-entered, non-negative number (no currency conversion or computation; the project's currency is assumed for display); lost reason is owner-entered free text.
- **Upload defaults are configured**: Allowed types default to PDF, DOCX, and Markdown, and the maximum upload size has a sensible configured default (assumed on the order of ~10 MB); the exact values live in configuration and can be changed without a code change.
- **Attachment storage**: Files are stored at a configurable path under the application's data directory, outside any public web path, and that path is included in the backup set so the data is portable and restorable (Principle X).
- **Tags are free-form per project**: There is no global tag taxonomy or tag-management UI in this feature; tags are simple per-project labels.
- **Telegram idempotency & control**: Quick actions are keyed to the project's personal record so replays converge to the same state (at-least-once with deduplication, Principle VI); `/pause` and `/resume` flip shared polling state that the watcher reads at the start of each cycle — the watcher remains the only process that scrapes (Principles II, VIII).
- **`/find` searches the owner's tracked projects**: The search covers the owner's projects (matching the keyword across title/description/skills as in Feature 2's search, biased to those the owner is tracking) and returns the top matches with links; an empty result returns a friendly message.
- **Manual refresh**: The dashboard reflects new data and cross-surface changes on a manual refresh; live streaming is not required (consistent with Feature 2).
- **Timezone & encoding**: Timestamps (applied date, status-changed time, upload date) are stored in UTC and displayed in the owner's configured timezone; UTF-8 is used end to end (Principle V).
- **Reminder date is reserved**: The reminder date field is stored but nothing in this feature reads it.

## Dependencies

- **Feature 1 (watcher)**: the populated local database (projects, clients, scrape runs, settings), the Telegram bot and notification pipeline, the configuration/settings store, and the polling loop that `/pause`, `/resume`, `/health`, and `/stats` observe and control.
- **Feature 2 (dashboard)**: the application shell, owner authentication/session, the projects feed, and the project detail view — all extended by this feature.
- **Watcher cooperation**: the watcher MUST read its polling-enabled state and its configuration at the start of each cycle so that `/pause`, `/resume`, and configuration changes take effect on the next run.
- **Backup process**: the backup MUST include the new personal-data tables/records and the attachment storage location so that all owner data is portable and restorable (Principle X).
