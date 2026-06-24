# Feature Specification: Browse-and-Tune Dashboard

**Feature Branch**: `002-browse-tune-dashboard`  
**Created**: 2026-06-23  
**Status**: Draft  
**Input**: User description: "Mostaql Notifier — Feature 2: the browse-and-tune dashboard. A private, fast, clean web dashboard for the sole owner to browse, filter, and inspect the projects and clients the watcher has collected, inspect a project and its client in depth, and tune the watcher's thresholds — read-mostly, the only thing it changes is configuration."

## User Scenarios & Testing *(mandatory)*

This feature is **read-mostly**: every screen except Settings is view-only. The dashboard reads the
same local database the Feature 1 watcher writes, and the only data it ever changes is the watcher's
configuration values. It never triggers a scrape, never sends a notification, and never writes to
project or client records.

### User Story 1 - Secure access and browse the projects feed (Priority: P1)

As the sole owner, I open the dashboard on my laptop or phone, log in once with my shared password,
and land on a fast, clean feed of every project the watcher has collected. I switch between a dense
table view and a roomier card view, and for each project I see its title, client name and the
client's hiring rate, budget range with its tier label (Tier 1 / Tier 2), current bid count, age
(both relative — "x minutes/hours ago" — and the absolute timestamp), site status (open / closed /
unknown), whether it qualified, and a link out to Mostaql. I sort by posted time (default, newest
first), budget, bid count, or hiring rate, and I narrow the feed with filters (tier; budget range;
minimum hiring rate; bid-count range; posted within the last N hours; site status; a qualified-only
toggle) and a keyword search across title, description, and skills that works in Arabic and English.
The feed is paginated and stays fast as I filter and sort. All Arabic content renders right-to-left
and correctly, including mixed Arabic/English/Latin-digit text.

**Why this priority**: The feed is the reason the dashboard exists — a single place to review
everything collected and triage opportunities at a glance. With only this story (plus the login gate
that protects it), the owner already has a usable, valuable product that replaces scrolling Telegram
history and hand-querying the database. It is the MVP.

**Independent Test**: Seed the database with a representative set of collected projects/clients, start
the dashboard, log in with the configured password, and confirm the feed lists every project with all
required fields, that table/card toggle works, that each sort and each filter (and combinations)
produce correct, fast results, that keyword search matches Arabic and English terms, that pagination
works, and that Arabic text renders RTL. Confirm an unauthenticated visitor is redirected to login.

**Acceptance Scenarios**:

1. **Given** the dashboard is running and I am not logged in, **When** I open any dashboard URL, **Then** I am sent to the login screen and cannot see any project data until I authenticate.
2. **Given** the correct shared password, **When** I submit it on the login screen, **Then** I am granted a session that persists across page loads and navigation without re-entering the password.
3. **Given** the wrong password, **When** I submit it, **Then** I am refused with a clear message and shown no project data.
4. **Given** I am logged in and the watcher has collected projects, **When** I open the projects feed, **Then** I see a list (default: posted time, newest first) where each row/card shows title, client name, client hiring rate, budget range with Tier 1/Tier 2 label, bid count, relative age and absolute timestamp, site status, qualified indicator, and a working link to Mostaql.
5. **Given** the feed is showing, **When** I toggle between table view and card view, **Then** the same projects are presented in the chosen layout and my choice is reflected immediately.
6. **Given** the feed is showing, **When** I sort by budget, bid count, or hiring rate (ascending or descending), **Then** the list reorders correctly and quickly.
7. **Given** the feed is showing, **When** I apply filters — e.g. Tier 1, site status = open, minimum hiring rate = 80%, bid count ≤ 5, posted within last 6 hours, qualified-only — **Then** only matching projects remain, the filters combine (logical AND), and results return quickly.
8. **Given** the feed is showing, **When** I type an Arabic keyword or an English keyword into search, **Then** projects whose title, description, or skills contain that term (in the matching language) are shown.
9. **Given** more projects than fit on one page, **When** I page through the feed, **Then** I can reach every project and the active filters/sort persist across pages.
10. **Given** projects with Arabic titles and mixed Arabic/English/Latin-digit content, **When** they render in the feed, **Then** text direction is right-to-left, numbers and budgets stay readable, and long titles do not break the layout.

---

### User Story 2 - Inspect a project and its client in depth (Priority: P2)

As the owner, I open any project from the feed and see its full information and complete description
laid out right-to-left, alongside a client panel showing the client's reputation — hiring rate;
number of projects posted / open / hired; average rating and review count; total spent; member-since;
verification status; and country. Below the client's stats I see the other projects from this same
client that the watcher has already collected, each linking to its own detail view, and I have a link
out to the project on Mostaql.

**Why this priority**: Triage from the feed gets me a shortlist; the decision to bid needs the full
description and the client's track record in one place. It builds directly on the feed and is the
natural second step, but the feed is usable without it.

**Independent Test**: From a seeded database, open a project's detail view and confirm the full
description renders correctly RTL, the client panel shows every listed reputation field (handling
missing/unknown values gracefully), the same client's other collected projects are listed and link to
their own detail views, and the Mostaql link works.

**Acceptance Scenarios**:

1. **Given** a project in the feed, **When** I open it, **Then** I see its full details and complete description rendered right-to-left, plus a link out to the project on Mostaql.
2. **Given** the project's client is known, **When** I view the detail page, **Then** the client panel shows hiring rate, projects posted/open/hired, average rating and review count, total spent, member-since, verification status, and country.
3. **Given** the client has other projects the watcher has collected, **When** I view the detail page, **Then** those projects are listed below the client stats and each links to its own detail view.
4. **Given** a client whose hiring rate is "not yet calculated" (لم يحسب بعد) or who is missing budget/bid/rating fields, **When** I view the detail page, **Then** those fields display gracefully as unknown/not-calculated rather than as zero, an error, or a blank that looks like data.
5. **Given** a very long Arabic description with mixed Arabic-English-digit strings, **When** it renders, **Then** it is readable, correctly directioned, and does not overflow or corrupt the layout.

---

### User Story 3 - Tune the watcher's thresholds without touching the database (Priority: P3)

As the owner, I open a Settings page that shows the watcher's existing, editable configuration values
— polling interval, how often client profiles refresh, the primary and fallback budget floors, the
fallback target / buffer / window, and the minimum hiring rate. I change a value, the form validates
it (sensible range, correct type), and on save the watcher honors it on its next run. This replaces
editing the database by hand, and an invalid entry is rejected with a clear message rather than saved.

**Why this priority**: It removes the last reason to touch the database directly, but the watcher
keeps running on its current settings without it, so it ranks below browsing and inspection.

**Independent Test**: Open Settings, confirm it displays the current values of each listed setting,
change the primary budget floor to a valid new value and save, confirm the persisted configuration the
watcher reads now holds the new value (and the watcher uses it on its next run); then submit an invalid
value (wrong type or out of range) and confirm it is rejected with a clear message and the stored value
is unchanged.

**Acceptance Scenarios**:

1. **Given** the watcher's configuration exists, **When** I open Settings, **Then** I see the current value of each editable setting: polling interval, client-profile refresh interval, primary budget floor, fallback budget floor, fallback target, fallback buffer, fallback window, and minimum hiring rate.
2. **Given** a valid new value for a setting, **When** I save, **Then** the change is persisted to the same configuration store the watcher reads, and the watcher applies it on its next run.
3. **Given** an invalid value (wrong type, or outside the sensible range for that setting), **When** I try to save, **Then** the save is rejected with a clear message identifying the problem and the previously stored value is left unchanged.
4. **Given** I save a settings change, **When** the save completes, **Then** the dashboard never triggers a scrape or a notification as a side effect — only the configuration value changes.

---

### User Story 4 - Glance at system health and today's activity (Priority: P3)

As the owner, I land on a small Home/overview with at-a-glance figures that don't depend on
not-yet-built features: how many projects were found today, how many qualified today, total projects
and clients tracked, and the time of the last successful scrape with a simple health indicator —
green if recent runs succeeded, red if the latest run failed or was blocked.

**Why this priority**: A quick "is it alive and what came in today" view is reassuring and useful, but
it summarizes data the feed already exposes, so it is the lowest priority of the four.

**Independent Test**: From a seeded database with a mix of scrape runs (including a recent success and,
separately, a failed/blocked latest run), open Home and confirm each figure is correct and the health
indicator is green after a recent success and red when the latest run failed or was blocked.

**Acceptance Scenarios**:

1. **Given** projects were found and qualified today, **When** I open Home, **Then** I see today's found count, today's qualified count, total projects tracked, and total clients tracked.
2. **Given** the most recent scrape run succeeded recently, **When** I open Home, **Then** the last-successful-scrape time is shown and the health indicator is green.
3. **Given** the latest scrape run failed or was blocked, **When** I open Home, **Then** the health indicator is red and signals that attention is needed.
4. **Given** a fresh database with no runs yet, **When** I open Home, **Then** every figure shows a sensible empty/zero state and the health indicator reflects "no successful run yet" rather than a false green.

---

### Edge Cases

- **Fresh database, no data**: Feed, detail, Home, and Settings each show a sensible empty state (e.g. "No projects collected yet") rather than errors or blank screens.
- **Filter matches nothing**: The feed shows a clear "no projects match these filters" empty state with an easy way to clear/relax filters, distinct from the "no data at all" state.
- **Unknown / not-yet-calculated client signals**: A client with hiring rate "لم يحسب بعد" (stored as not-calculated, distinct from 0%) or missing budget/bid/rating fields is displayed as unknown/not-calculated, never as zero or a parse error; such projects still appear in the feed.
- **Very long Arabic titles/descriptions and mixed Arabic-English-Latin-digit strings**: Render correctly RTL, stay readable, and do not break or overflow layout in either table or card view.
- **Backend or database unavailable**: Screens show a clear error state ("dashboard can't reach its data right now") rather than a crash, white screen, or misleading empty state.
- **Loading**: Screens show a clear loading state while data is being fetched, distinct from empty and error states.
- **Invalid settings input**: Rejected with a clear, specific message; the stored configuration is never left in a corrupt or partially-saved state.
- **Stale view vs. new data**: New projects collected by the watcher after a screen loaded appear on a manual refresh; live streaming is not required and its absence is not an error.
- **Login disabled by configuration**: When the owner turns the login gate off via configuration, every screen is reachable directly without a password, and turning it back on restores the gate.
- **Session persistence**: Once logged in, navigating between screens and reloading does not force re-authentication until the session ends.

## Requirements *(mandatory)*

### Functional Requirements

#### Application shell & presentation (A)

- **FR-001**: The dashboard MUST present a consistent application shell with persistent navigation to Home, Projects feed, and Settings, and a way to sign out.
- **FR-002**: The layout MUST be responsive and usable on both a laptop and a phone screen.
- **FR-003**: All Arabic content MUST render right-to-left, and mixed Arabic/English/Latin-digit content MUST render with correct direction while keeping numbers and budgets readable.
- **FR-004**: The interface MUST be visually clean, modern, and fast; perceived responsiveness of navigation, filtering, and sorting is a hard requirement, not optional polish.

#### Authentication (B)

- **FR-005**: The dashboard MUST gate every screen behind authentication; an unauthenticated visitor MUST be sent to a login screen and MUST NOT see any project, client, or settings data.
- **FR-006**: Authentication MUST use a single shared password; a correct password MUST establish a session that persists across navigation and reloads until sign-out or session expiry.
- **FR-007**: The login gate MUST be disengageable via configuration, so the owner can run the dashboard with no password when they choose, and re-enable it via configuration.
- **FR-008**: The shared password MUST be supplied via configuration/secret storage and MUST NOT be committed to the repository.

#### Projects feed (C)

- **FR-009**: The feed MUST list all collected projects and MUST offer both a table view and a card view, toggled by the owner.
- **FR-010**: Each project in the feed MUST show: title, client name, client hiring rate, budget range, tier label (Tier 1 / Tier 2), bid count, age as both relative ("x minutes/hours ago") and absolute timestamp, site status (open/closed/unknown), a qualified indicator, and a link out to the project on Mostaql.
- **FR-011**: The feed MUST be sortable by posted time (default, newest first), budget, bid count, and hiring rate, in both directions.
- **FR-012**: The feed MUST be filterable by tier, budget range, minimum hiring rate, bid-count range, age (posted within the last N hours), site status, and a qualified-only toggle; multiple active filters MUST combine as logical AND.
- **FR-013**: The feed MUST provide a keyword search across project title, description, and skills that matches both Arabic and English text.
- **FR-014**: The feed MUST be paginated, and applied filters and sort MUST persist while paging.
- **FR-015**: Filtering and sorting MUST remain fast for the expected local data volume; the owner MUST NOT perceive meaningful lag when changing filters or sort.

#### Project detail & client panel (D)

- **FR-016**: A project detail view MUST show the project's full information and complete description rendered right-to-left.
- **FR-017**: The detail view MUST include a client panel showing hiring rate; projects posted / open / hired; average rating and review count; total spent; member-since; verification status; and country.
- **FR-018**: The detail view MUST list the other projects from the same client that the watcher has already collected, each linking to its own detail view.
- **FR-019**: The detail view MUST include a link out to the project on Mostaql.
- **FR-020**: Missing or not-yet-calculated client/project fields (e.g. hiring rate "لم يحسب بعد", absent budget/bid/rating) MUST be displayed as unknown/not-calculated, never as zero or as a parse error.

#### Settings (E)

- **FR-021**: A Settings page MUST display and allow editing of the watcher's existing editable configuration values: polling interval, client-profile refresh interval, primary budget floor, fallback budget floor, fallback target, fallback buffer, fallback window, and minimum hiring rate.
- **FR-022**: Settings edits MUST be validated for correct type and sensible range before saving; invalid input MUST be rejected with a clear, specific message and MUST NOT be persisted.
- **FR-023**: Saved settings MUST be written to the same configuration store the watcher reads, so the watcher honors them on its next run, with no manual database editing required.
- **FR-024**: The Settings page MUST NOT expose or allow editing of configuration that is out of scope for this feature; it edits only the listed watcher tunables.

#### Home / overview (F)

- **FR-025**: A Home/overview MUST show: projects found today, projects qualified today, total projects tracked, total clients tracked, the time of the last successful scrape, and a simple health indicator.
- **FR-026**: The health indicator MUST be green when recent runs succeeded and red when the latest run failed or was blocked, and MUST NOT show false green when there has been no successful run.

#### Read-mostly & safety guarantees (cross-cutting)

- **FR-027**: The dashboard MUST treat project and client data as read-only; it MUST NEVER create, modify, or delete project or client records. Configuration (settings) is the only data it writes.
- **FR-028**: The dashboard MUST NEVER trigger a scrape, a re-scan, or a notification as a side effect of any action.
- **FR-029**: The dashboard MUST read the same data store the watcher writes and MUST reflect newly collected projects on a manual refresh; live streaming is explicitly not required.
- **FR-030**: Every screen MUST present distinct, clear empty, loading, and error states, including no-data-yet, no-filter-match, and backend/database-unavailable.
- **FR-031**: Project and client detail and the Home overview MUST be laid out so later additions (opportunity score, freshness/"still good?" signals, CRM fields, richer analytics) can slot in without restructuring; those additions are out of scope here.

### Out of Scope (built in later features)

The following are explicitly NOT part of this feature and MUST NOT be built here: the opportunity
score and any ranking, score column, or "why this score" view; re-checking projects over time,
bid-count-over-time charts, a "still good?" freshness signal, and site-status timelines; the personal
CRM (favorites, personal status, tags, applied dates, outcomes, notes, file uploads, Kanban board);
Telegram inline buttons and bot commands; digests and quiet hours; rich analytics, heatmaps, funnels,
and the tips engine; the clients directory, watchlist, and blacklist; multiple saved searches and
additional categories. The dashboard also never auto-bids or takes any action on Mostaql.

### Key Entities *(read from the watcher's existing data store)*

- **Project**: A collected Mostaql development project. Attributes used here: Mostaql id, title, full description, link/URL, category, skills, budget range (min/max) and currency, tier (Tier 1 / Tier 2), bid count, posted time, scraped time, site status (open/closed/unknown), qualified/eval status, and its owning client. Read-only to the dashboard.
- **Client**: The poster of one or more projects. Attributes used here: name, hiring rate (which may be not-yet-calculated and distinct from 0%), projects posted/open, hires count, average rating and review count, total spent, country, member-since, and verification status. Read-only to the dashboard. A client links to the set of its collected projects.
- **Scrape Run**: A record of one watcher poll cycle: start/finish time, found/new/updated/error counts, and outcome status (success / partial / failed / blocked). Read-only; drives the Home counts, last-successful-scrape time, and health indicator.
- **Setting**: A typed, named watcher configuration value. The only entity the dashboard writes — and only the subset listed in FR-021. Validated on write; consumed by the watcher on its next run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The owner can open the dashboard on a laptop or phone, log in, and browse every project the watcher has collected, with all required per-project fields visible in both table and card views.
- **SC-002**: The owner can narrow the feed to a specific slice — e.g. open Tier-1 projects above a chosen hiring rate with few bids, sorted newest-first — in under 10 seconds and with no perceptible lag on the result.
- **SC-003**: For any project, the owner can open its detail view, read the full Arabic description correctly laid out right-to-left, see every listed client reputation field, and reach the same client's other collected projects.
- **SC-004**: The owner can change a watcher threshold (e.g. the primary budget floor) from Settings and have the watcher honor the new value on its next run, without ever editing the database by hand.
- **SC-005**: Invalid settings input is rejected 100% of the time with a clear message, and never leaves the watcher configuration in a corrupt or partially-saved state.
- **SC-006**: Arabic content and mixed Arabic/English/Latin-digit text render correctly (direction, readability of numbers/budgets, no layout breakage) across every screen, including very long titles and descriptions.
- **SC-007**: Every screen presents a correct, distinct state for each of: data present, no data yet, no filter match, loading, and backend/database unavailable.
- **SC-008**: The Home health indicator is green within one refresh of a recent successful scrape and red when the latest run failed or was blocked, with no false green before any successful run.
- **SC-009**: No dashboard action ever writes to project or client records or triggers a scrape or notification — verifiable by confirming those data stores and side-effect channels are untouched after exercising every screen.

## Assumptions

- **Single user, single box**: The dashboard serves only the owner on their own machine; there is no multi-user, role, or onboarding surface (per the project constitution). The "login" is a single shared password, not an account system.
- **Shared data store**: The dashboard reads the same local database the Feature 1 watcher already writes, and writes only to the existing settings/configuration store the watcher reads. No new project/client data model is introduced.
- **Editable settings = the watcher's existing tunables**: The eight settings in FR-021 map to the watcher's current configuration keys (polling interval, client-profile refresh interval, primary and fallback budget floors, fallback target, fallback buffer, fallback window, minimum hiring rate). Other existing configuration values remain editable only via the database in this feature.
- **Tier labels**: "Tier 1 / Tier 2" reflect the tier the watcher already assigns to each project; the dashboard displays that tier and does not recompute it.
- **Qualified indicator**: "Whether it qualified" reflects the watcher's existing evaluation status; baseline/first-run projects (recorded but never evaluated) are shown as not-qualified/not-evaluated rather than as a failure.
- **Manual refresh**: New data appears on page refresh; real-time push/streaming is intentionally out of scope.
- **Timezone**: Absolute timestamps are shown in the owner's configured timezone, with UTC as the stored basis (per the constitution); relative ages ("x minutes ago") are derived from the same basis.
- **Local security posture**: Even bound to localhost the dashboard sits behind the password gate by default (constitution IX), with the configuration toggle the only supported way to disable it.
- **Performance basis**: "Fast" is judged against the expected personal, low-volume local dataset, not against large-scale or multi-user load.

## Dependencies

- The Feature 1 watcher and its populated local database (projects, clients, scrape runs, settings) must exist; the dashboard is a read-mostly view over them.
- The watcher must continue to read its configuration from the shared settings store at the start of each run, so dashboard-saved changes take effect on the next run.
