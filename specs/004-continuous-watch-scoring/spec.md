# Feature Specification: Continuous Watching and Opportunity Scoring

**Feature Branch**: `004-continuous-watch-scoring`  
**Created**: 2026-06-28  
**Status**: Draft  
**Input**: User description: "Mostaql Notifier — Feature 4: continuous watching and opportunity scoring. Add a single 0–100 opportunity score that ranks qualified projects from configurable weighted components with a stored per-component breakdown, and a separate polite re-check loop that re-visits open and recently-closed projects to track their bid trajectory, status, and final outcome over time, recomputing the score on every re-check while open. Surface the score (column, sort, filter, detail breakdown bars), a project lifecycle (bid chart, status timeline, outcome), a green/yellow/red 'still good?' freshness signal, automatic Mostaql-status updates plus an optional auto personal-status transition, and the score, a 'Why?' breakdown, and a /top command in Telegram."

## User Scenarios & Testing *(mandatory)*

This feature turns raw collection into judgement. Features 1–3 collect qualifying projects, let the owner
browse and tune them on an RTL dashboard, and layer a personal pipeline, workspace, and Telegram actions on
top. But every project is still judged exactly once, at the moment it is found, and never looked at again:
the owner cannot tell which qualified projects are the *best* ones, and has no idea what became of a project
after seeing it. This feature adds the two capabilities that close that gap — a **single opportunity score**
that ranks qualified projects, and a **watch-over-time loop** that keeps re-checking them to track
competition, status, and final outcome. It is the heaviest backend feature; the trajectory data it gathers
is the foundation for the later analytics features (which this feature deliberately does not build).

Two invariants from the constitution govern everything here. First, **non-destructive history** (Principle
IV): every re-check appends a timestamped snapshot, scores and snapshots and outcomes are retained and
backed up, and no automatic process ever deletes or overwrites the owner's own data — including a personal
status the owner set deliberately. Second, **polite, fail-closed behaviour** (Principles II and VII): the
re-check loop is exactly as polite as the initial watcher (bounded batches, randomized delays, backoff,
block detection, and never re-checking a single project more often than the configured interval, paused
when the watcher is paused), and ambiguous endings are recorded as *unknown* rather than guessed.

The five user stories below are prioritized. **User Story 1 (the opportunity score)** is the foundation —
it defines the score that the feed, the detail view, the re-check loop, and Telegram all consume. **User
Story 2 (the watch-over-time loop)** is the backbone that gathers the trajectory and outcome, and recomputes
the score over a project's open life. Stories 3–5 are additional surfaces over the data those two produce
and each can be built, tested, and demonstrated on its own.

### User Story 1 - Rank every qualified project by a single opportunity score (Priority: P1)

As the sole owner, I want every qualified project — including ones already collected before this feature —
ranked by a single 0–100 opportunity score computed from configurable weighted components, so I instantly
know which projects to pursue first. For every project I want the stored **breakdown** — how much each
component contributed — so I can see and trust *why* a project scored what it did, not just the number. In
the projects feed I want a score column, the ability to sort by score, and a filter by score range; on a
project's detail view I want the breakdown shown as per-component bars alongside the currently active
weights. All of the model's weights and tuning values live in settings; nothing about the model is fixed in
code, and changing a weight takes effect without a code change.

**Why this priority**: The score is the headline value of the feature and the thing every other story
consumes — the re-check loop recomputes it, the freshness signal and Telegram both surface it. With only
this story shipped, the owner can already rank, sort, and filter qualified projects by a trustworthy,
explainable score and stop guessing which to bid on. It is the MVP.

**Independent Test**: Seed the database with qualified projects (some collected before this feature, with
varied client hiring rates, hire volumes, budgets, tiers, bid counts, and ages). Run the scoring backfill
and confirm every qualified project receives a 0–100 score with a stored per-component breakdown. In the
feed, confirm the score column appears, sorting by score orders the list correctly, and a score-range filter
narrows it. Open a project and confirm the breakdown renders as per-component bars beside the active
weights, and that the bars (with the weights) account for the displayed total. Change a weight in settings
and re-score, and confirm both the number and the bars change accordingly with no code change.

**Acceptance Scenarios**:

1. **Given** a qualified project with a client hiring rate, hire count, budget, tier, bid count, and posted-at time, **When** it is scored, **Then** it receives a single 0–100 opportunity score and a stored breakdown recording each component's contribution.
2. **Given** qualified projects that were collected before this feature, **When** the scoring backfill runs, **Then** each of them also gets a 0–100 score and breakdown (no qualified project is left unscored).
3. **Given** two clients with the same hiring rate but very different numbers of projects, **When** their projects are scored, **Then** the one based on more projects contributes more on the hiring-rate component (a low-sample rate is shrunk toward the neutral baseline).
4. **Given** the projects feed, **When** I sort by score, **Then** projects order from highest to lowest score; **and When** I filter by a score range, **Then** only projects whose score falls in that range are shown.
5. **Given** a project's detail view, **When** I open it, **Then** I see the per-component contributions as bars alongside the active weights, and the components combine to the displayed total score.
6. **Given** the scoring weights and tuning values in settings, **When** I change a weight (or a tuning value) and projects are re-scored, **Then** the scores and breakdowns reflect the change with no code change and no redeploy.
7. **Given** weights that do not sum to exactly one, **When** scoring runs, **Then** the weights are normalized (not rejected) and the resulting score is still a valid 0–100 value.
8. **Given** a project whose budget is one-sided (only a minimum or only a maximum) or whose budget midpoint sits above the diminishing-returns cap, **When** it is scored, **Then** the budget component is computed without error and the cap bounds its contribution.

---

### User Story 2 - Watch each project over time: trajectory, lifecycle, and outcome (Priority: P2)

As the sole owner, I want the system to keep watching each project on a separate, configurable schedule
(independent of the fast new-project poll) — re-visiting projects that are still open, and ones that
recently closed — so I can see how fast bids pile up, whether a project is still worth bidding on, and
whether it ended up hired or not. On each re-check the system refreshes the project's current bid count and
its status on Mostaql (open / closed / awarded), refreshes the client's stats if they have gone stale,
appends a timestamped snapshot (bid count, status, score), and — while the project is open — recomputes the
opportunity score so the ranking always reflects reality. It captures each project's final outcome (still
open, closed with no hire, or hired) and, where the ending is genuinely unclear, leaves it unknown rather
than guessing. It stops actively tracking a project once it has been closed for a configurable grace period
(default 72 hours after close). On a project's detail view I want its lifecycle: a chart of bid count over
time, a timeline of its status changes, and its final outcome. The loop must be just as polite as the
initial watcher and must pause when the watcher is paused.

**Why this priority**: The re-check loop is the backbone that produces the trajectory, the live score, and
the outcome — the data the freshness signal, the lifecycle view, and the later analytics all depend on. It
depends on User Story 1 (it recomputes the score) but delivers its own complete, demonstrable value: a
living history of every tracked project. It is sequenced second because the score must exist before the loop
can recompute it.

**Independent Test**: With several open qualified projects, run the re-check loop. Confirm each project gets
a fresh snapshot recording its current bid count, status, and recomputed score, that the loop works in
bounded batches with the same delays/backoff/block-detection as the initial watcher, and that it never
re-checks a single project more often than the configured interval. Drive a project's bid count up across
re-checks and confirm its snapshots record the climb and its score drops. Close a project between re-checks
and confirm its status flips to closed, its score stops being recomputed, and its outcome is captured
(awarded → hired; closed with no visible award → closed-no-hire; ambiguous → unknown). Advance time past the
grace period and confirm the project is no longer actively re-checked. On the detail view confirm the bid
chart, status timeline, and final outcome render. Pause the watcher mid-cycle and confirm the loop stops.

**Acceptance Scenarios**:

1. **Given** the re-check loop runs on its own configurable interval, **When** it processes an open tracked project, **Then** it refreshes that project's current bid count and Mostaql status, refreshes the client's stats if they are stale, and appends a timestamped snapshot of bid count, status, and score.
2. **Given** an open project, **When** it is re-checked, **Then** its opportunity score is recomputed from the refreshed data, so the value shown reflects the most recent check.
3. **Given** a project whose bid count rises sharply between re-checks, **When** it is re-scored, **Then** its score drops (its competition component worsens) and its snapshots record the climb.
4. **Given** a project that closes between re-checks, **When** the loop next sees it, **Then** its status becomes closed, it is marked no longer actionable, and the score is no longer recomputed for it.
5. **Given** a project that Mostaql marks awarded, **When** its outcome is captured, **Then** it is recorded as **hired**; **given** a project that simply closed with no visible award, **Then** it is recorded as **closed, no hire**; **given** an ending that is genuinely unclear, **Then** it is left **unknown** (never assumed hired).
6. **Given** a project that has been closed for longer than the configured grace period (default 72 hours), **When** the loop runs, **Then** that project is no longer actively re-checked.
7. **Given** a re-check that is blocked or fails for one project, **When** the loop continues, **Then** that project is logged and skipped and the other projects in the batch are still processed (one failure never crashes or stalls the cycle).
8. **Given** the watcher is paused (from any surface), **When** the re-check loop would run or is mid-cycle, **Then** it does not perform further re-checks until the watcher is resumed.
9. **Given** a project's detail view, **When** I open it, **Then** I see a chart of its bid count over time, a timeline of its status changes, and its final outcome.
10. **Given** the re-check loop, **When** it accesses Mostaql, **Then** it uses bounded batches with the same randomized delays, exponential backoff, and block/structure-change detection as the initial watcher, and never re-checks a single project more often than the configured interval.

---

### User Story 3 - See at a glance whether a project is still worth bidding on (Priority: P3)

As the sole owner, I want each project to carry an at-a-glance "still good?" freshness indicator derived from
its trajectory — green when it is fresh and uncrowded, yellow when it is cooling (bids climbing, project
aging), and red when it is crowded or closed — shown both in the feed and on the detail view, so a crowded
or closed project no longer *looks* attractive even if its raw score was once high. The thresholds that
separate green, yellow, and red are read from settings.

**Why this priority**: The freshness signal turns the trajectory data from User Story 2 into an instant
visual judgement, which is the everyday "should I still bid?" decision. It depends on the trajectory and
status from Story 2, so it is sequenced after it, but it is an independent, separately testable surface that
adds clear value on its own.

**Independent Test**: Take projects at different points in their life — a brand-new uncrowded one, an aging
one with climbing bids, and a crowded or closed one — and confirm each shows the right colour (green /
yellow / red) in both the feed and the detail view, consistent with its trajectory. Adjust a freshness
threshold in settings and confirm the boundary where a project flips colour moves accordingly. Confirm a
closed or crowded project reads red regardless of its earlier score.

**Acceptance Scenarios**:

1. **Given** a fresh, uncrowded project (recently posted, few bids, low bid rate), **When** its freshness signal is computed, **Then** it shows green in both the feed and the detail view.
2. **Given** an aging project whose bids are climbing, **When** its freshness signal is computed, **Then** it shows yellow (cooling).
3. **Given** a crowded project (high bid count or high bid rate) or a closed project, **When** its freshness signal is computed, **Then** it shows red and no longer looks attractive.
4. **Given** the freshness thresholds in settings, **When** I change a threshold, **Then** the green/yellow/red boundaries move accordingly with no code change.
5. **Given** a project with too little trajectory to judge a trend (e.g. only one snapshot), **When** its freshness signal is computed, **Then** it degrades to a sensible indicator based on what is known (e.g. age and current bid count) rather than erroring.

---

### User Story 4 - Keep status current automatically, and optionally flag missed projects (Priority: P4)

As the sole owner, I want the re-check loop to keep each project's Mostaql status (open / closed / awarded)
updated automatically so the dashboard always reflects reality without my touching it. And — only if I turn
it on — I want an optional automatic transition of *my personal* status: a project I marked "Interested" but
never applied to, that then closes, gets flagged "Expired / Missed" so it leaves my active consideration.
This automatic personal-status change never touches projects I have already applied to, won, or lost; it is
off by default and toggleable; every such change is reversible and recorded with a timestamp; and no
automatic change ever deletes my data or overwrites a status I set deliberately.

**Why this priority**: Keeping the Mostaql status current is a natural, low-risk by-product of the re-check
loop, and the optional missed-project flag saves the owner from manually tidying stale "Interested" items.
It is sequenced after the loop (Story 2) and the personal record it builds on (Feature 3), and it carries
the most safety constraints, so it is gated carefully and defaults off.

**Independent Test**: With the loop running, close a project on Mostaql and confirm its scraped status
updates to closed automatically. With the optional auto personal-status toggle **off** (default), close a
project the owner marked "Interested" and confirm the personal status is unchanged. Turn the toggle **on**,
close another "Interested"-but-not-applied project, and confirm it is flagged "Expired / Missed", that the
change is timestamped and recorded as automated, and that it can be reversed. Confirm that projects the owner
marked Applied, Won, or Lost are never auto-changed, that a status the owner set deliberately is never
overwritten, and that no automatic change deletes any notes, tags, files, or other personal data.

**Acceptance Scenarios**:

1. **Given** the re-check loop and a project whose Mostaql status changes (e.g. open → closed or → awarded), **When** the loop re-checks it, **Then** the project's scraped status is updated automatically to match.
2. **Given** the optional auto personal-status toggle is **off** (default), **When** an "Interested"-but-not-applied project closes, **Then** my personal status is left unchanged.
3. **Given** the toggle is **on**, **When** an "Interested"-but-not-applied project closes, **Then** its personal status is automatically transitioned to "Expired / Missed", and the change is timestamped and recorded as automated.
4. **Given** the toggle is on, **When** a project I marked Applied, Won, or Lost closes, **Then** its personal status is never auto-changed.
5. **Given** an automatic personal-status change, **When** it is applied, **Then** it is reversible and never overwrites a status I set deliberately, and it never deletes any personal data (notes, tags, files, outcomes).
6. **Given** the auto personal-status toggle, **When** I turn it on or off, **Then** the behaviour follows the toggle immediately (the toggle is read from settings, not hard-coded).

---

### User Story 5 - See the score, ask why, and pull the top projects in Telegram (Priority: P5)

As the sole owner, now that scores exist, I want each project notification in Telegram to include the
project's opportunity score and its tier, a "Why?" button that replies with the score breakdown for that
project, and a `/top [n]` command that lists the current top N open projects by score with their links — so
I can judge and rank opportunities directly from chat without opening the dashboard.

**Why this priority**: This is a high-convenience surface that puts the score where the owner first sees a
project, but it only re-presents data User Story 1 already produces, so it is sequenced last. It depends on
the score (Story 1) and on Feature 1/3's existing Telegram notification channel, inline buttons, and bot
commands.

**Independent Test**: Trigger a project notification and confirm it now shows the project's score and tier.
Tap "Why?" and confirm the bot replies with that project's per-component score breakdown. Send `/top` and
`/top 5` and confirm the bot replies with the current top open projects by score (the default count, then
five), each with its link, ordered highest-first, and that closed projects are excluded. Send `/top` when
fewer than N open projects exist and confirm a sensible shorter list (or friendly message), and tap "Why?"
on a project that has since closed and confirm it still returns the last known breakdown without error.

**Acceptance Scenarios**:

1. **Given** a project notification, **When** it is sent, **Then** it includes the project's opportunity score and its tier alongside the existing facts.
2. **Given** a project notification with a "Why?" button, **When** I tap it, **Then** the bot replies with that project's per-component score breakdown.
3. **Given** `/top` with no argument, **When** I send it, **Then** I receive the current top open projects by score (a configurable default count) with their links, ordered highest score first.
4. **Given** `/top n`, **When** I send it with a number, **Then** I receive the top N open projects by score with their links.
5. **Given** `/top` when fewer than the requested number of open projects exist, **When** I send it, **Then** I receive the available projects (a shorter list) or a friendly "no open projects" message, never an error.
6. **Given** a "Why?" tap on a project that has since closed or whose notification is old, **When** I tap it, **Then** the bot returns the last known breakdown gracefully (idempotent, no error).

---

### Edge Cases

- **Low-sample client (few projects)**: A hiring rate based on very few projects is shrunk toward the neutral baseline on the hiring-rate component, so a high rate from two projects counts for less than the same rate from many; the existing low-sample flag stays honest (the score never *hides* low confidence, it dampens it).
- **One-sided or capped budget**: A project with only a minimum or only a maximum budget is scored from the bound that is present; a budget midpoint above the diminishing-returns cap is clamped to the cap's contribution. Tier 2 (fallback-floor) projects are scaled down on the budget component. A project with no usable budget figure contributes the component's floor, not an error.
- **First re-check vs long history**: A project re-checked for the first time has no prior snapshot, so bid velocity cannot be computed from history — its competition component falls back to current bid count and age; a project with a long snapshot history computes velocity from the trajectory.
- **Project closes between re-checks**: Its status flips to closed, its score is frozen at the last open value (no longer recomputed), it is marked no longer actionable, and its freshness signal reads red.
- **Closed-and-awarded vs closed-no-award vs ambiguous**: An explicit award records **hired**; a plain close with no visible award records **closed, no hire**; a genuinely unclear ending records **unknown** (fail-closed — never assumed hired).
- **Grace-period boundary**: A project keeps being re-checked until it has been closed for the configured grace period (default 72h), then stops; a project that re-opens or is updated within the grace window is still tracked.
- **Re-check blocked or failing for one project**: That single project is logged and skipped; the rest of the batch proceeds; repeated blocks raise the same health alert and backoff as the initial watcher.
- **Watcher paused mid-cycle**: Pausing the watcher pauses the re-check loop too; an in-progress cycle stops re-checking and does not resume until the watcher is resumed.
- **Weights that do not sum to one**: The weights are normalized (scaled to sum to one) rather than rejected, so the score stays a valid 0–100 value.
- **All-zero or missing components**: A project missing optional inputs (e.g. unknown bid count or unknown posted-at time) is still scored from the components that are available; missing inputs contribute their component floor and never crash scoring.
- **Score on non-qualified projects**: Only qualified projects are scored and ranked; disqualified or still-pending projects carry no score and are excluded from score sort/filter and from `/top`.
- **Auto personal-status safety**: With the auto-transition on, only an "Interested"-but-not-applied project that closes is flagged "Expired / Missed"; Applied/Won/Lost and any deliberately-set status are never touched, the change is reversible and timestamped, and nothing is deleted.
- **Configuration takes effect live**: Changing any weight, tuning value, the re-check interval, the grace period, a freshness threshold, the `/top` default, or an auto-status toggle takes effect on the next scoring/loop cycle with no code change.

## Requirements *(mandatory)*

### Functional Requirements

#### Part A — Opportunity score & ranking

- **FR-001**: The system MUST compute a single opportunity score on a 0–100 scale for every qualified project, combining the configured weighted components into one ranked value.
- **FR-002**: The score MUST be computed from these components, each individually configurable: (a) client hiring rate, confidence-adjusted so a rate from few projects is shrunk toward a neutral baseline; (b) client hire volume / reliability, rewarding a proven hiring track record with diminishing returns; (c) project budget, higher scoring higher with diminishing returns above a configurable cap, with Tier 2 (fallback-floor) projects scaled down on this component; (d) competition, where few bids and a low rate of bids relative to how long the project has been open both score higher; (e) freshness, where newer projects score higher and the score decays with age since posting; and (f) a small client-rating adjustment from the client's average rating and how many reviews back it.
- **FR-003**: By default the hiring-rate component MUST carry the largest weight, and all default weights MUST be defined in settings (not as code literals).
- **FR-004**: For every scored project the system MUST store the score's **breakdown** — how much each component contributed — so the owner can see and trust why a project scored what it did.
- **FR-005**: The system MUST apply scoring to all currently qualified projects, including ones collected before this feature (a backfill), so no qualified project is left unscored.
- **FR-006**: The projects feed MUST gain a score column, the ability to sort by score, and a filter by score range; these MUST combine with the existing Feature 2/3 filters.
- **FR-007**: The project detail view MUST show the score breakdown as per-component bars alongside the currently active weights, such that the components and weights visibly explain the total.
- **FR-008**: Every weight and tuning value of the scoring model MUST be read from settings at runtime and MUST NOT be hard-coded; changing any of them MUST change the score without a code change or redeploy.
- **FR-009**: Weights that do not sum to exactly one MUST be normalized (scaled to sum to one) rather than rejected, and the resulting score MUST remain a valid 0–100 value.
- **FR-010**: Scoring MUST consume the existing two-tier budget classification from Feature 1 (it reads the tier; it MUST NOT redefine the tier rule), and MUST handle one-sided budgets and budgets above the diminishing-returns cap without error.
- **FR-011**: Only qualified projects MUST be scored and ranked; disqualified or still-pending projects MUST carry no score and MUST be excluded from score-based sort, filter, and `/top`.

#### Part B — Watch-over-time loop, trajectory & outcome

- **FR-012**: The system MUST run a re-check loop on a separate, configurable interval, independent of the fast new-project poll, that re-visits projects that are still open and ones that have closed within the configurable grace period.
- **FR-013**: On each re-check the system MUST refresh the project's current bid count and its Mostaql status (open / closed / awarded), and MUST refresh the client's stats if they have gone stale (reusing the existing client-refresh staleness rule).
- **FR-014**: On each re-check the system MUST append a timestamped snapshot capturing at least the project's bid count, status, and score at that moment; snapshots MUST accumulate into a per-project trajectory and MUST NOT overwrite earlier snapshots.
- **FR-015**: While a project is open, the system MUST recompute its opportunity score on every re-check, so the displayed value always reflects the most recent check; once a project is closed, the system MUST stop recomputing its score and mark it no longer actionable.
- **FR-016**: The system MUST capture each project's final outcome as one of: still open, closed with no hire, or hired (awarded). It MUST record **hired** only where Mostaql makes the award explicit, **closed, no hire** where a project simply closed with no visible award, and MUST leave the outcome **unknown** where the ending is genuinely unclear — it MUST NEVER assume hired (fail-closed).
- **FR-017**: The system MUST stop actively re-checking a project once it has been closed for the configurable grace period (default 72 hours after close).
- **FR-018**: The system MUST track, per project, whether it is still being actively re-checked and when it was last checked, and MUST NEVER re-check a single project more often than the configured re-check interval.
- **FR-019**: The re-check loop MUST be as polite as the initial watcher: bounded batches, randomized inter-request delays, low/serial concurrency, exponential backoff on 429/403, and block/structure-change detection with a health alert — it MUST NOT behave like an aggressive crawler.
- **FR-020**: A re-check that is blocked or fails for one project MUST be logged and skipped without crashing or stalling the rest of the batch; the remaining projects MUST still be processed.
- **FR-021**: The re-check loop MUST honor the watcher's paused state: when the watcher is paused the loop MUST NOT perform further re-checks, including when a pause occurs mid-cycle, and MUST resume on the next cycle after the watcher is resumed.
- **FR-022**: The project detail view MUST show the project's lifecycle: a chart of bid count over time, a timeline of its status changes, and its final outcome.
- **FR-023**: The re-check loop MUST NOT die silently: failures MUST be logged, alert the owner (via the existing health-alert channel), and retry under backoff.

#### Part C — Freshness signal, automatic status & Telegram score

- **FR-024**: The system MUST derive an at-a-glance freshness ("still good?") signal for each project from its trajectory — **green** for fresh and uncrowded, **yellow** for cooling (bids climbing, project aging), and **red** for crowded or closed — and MUST show it in both the feed and the detail view.
- **FR-025**: The freshness-signal thresholds MUST be read from settings and MUST NOT be hard-coded; a project with too little trajectory to judge a trend MUST degrade to a sensible indicator from what is known rather than erroring.
- **FR-026**: The system MUST keep each project's scraped Mostaql status (open / closed / awarded) updated automatically from the re-check loop.
- **FR-027**: The system MUST support an **optional** automatic personal-status transition, **off by default** and toggleable from settings: when enabled, a project the owner marked "Interested" but never applied to that then closes MUST be transitioned to "Expired / Missed".
- **FR-028**: The automatic personal-status transition MUST NEVER touch a project the owner marked Applied, Won, or Lost, MUST NEVER overwrite a status the owner set deliberately, and MUST NEVER delete any personal data (notes, tags, files, outcomes).
- **FR-029**: Every automatic personal-status change MUST be reversible and recorded with a timestamp and an indication that it was automated (so the owner can distinguish and undo it).
- **FR-030**: Each project notification in Telegram MUST include the project's opportunity score and its tier.
- **FR-031**: Each project notification MUST include a "Why?" inline button that, when tapped, replies with that project's per-component score breakdown; tapping it on an old or since-closed project MUST return the last known breakdown gracefully (idempotent, no error).
- **FR-032**: The bot MUST support a `/top [n]` command that lists the current top N open projects by opportunity score with their links, ordered highest-first; `n` MUST default to a configurable value when omitted, closed projects MUST be excluded, and a request for more than exist MUST return the available projects or a friendly message rather than an error.

#### Cross-cutting: configuration, correctness, observability & history

- **FR-033**: Every value this feature introduces — all scoring weights and tuning values (neutral baseline and shrinkage strength, diminishing-returns caps, Tier-2 budget scale, decay/age parameters, rating-adjustment bounds), the re-check interval, the tracking grace period, the freshness thresholds, the `/top` default count, and the auto-status toggle — MUST be read from settings and MUST NOT be hard-coded.
- **FR-034**: All re-parsed values (bid counts, percentages) MUST correctly handle Arabic-Indic digits and the "لم يحسب بعد" (not-yet-calculated) state as a first-class case, consistent with Feature 1; timestamps (snapshots, status changes, last-checked, close time) MUST be stored in UTC and displayed in the owner's timezone.
- **FR-035**: All trajectory data, scores, breakdowns, outcomes, and tracking state MUST be retained, included in the backup set, and MUST NEVER be deleted or overwritten by automation except by the additive append of new snapshots and the recompute of the live score on open projects.
- **FR-036**: This feature MUST NOT take any action on mostaql.com beyond reading (no bidding, messaging, or any write/submit action); all re-checks are reads only.
- **FR-037**: Every scored-project surface (feed score column/sort/filter, detail breakdown and lifecycle, freshness signal) MUST sit behind the dashboard's existing authentication and MUST render Arabic content right-to-left.

### Constitutional Alignment *(how this feature honors the gates)*

This feature touches scraping (the re-check loop), qualification/scoring, time-series storage, automatic
status changes, and notifications, so per the constitution it states explicitly how it honors the relevant
gates:

- **II. Polite, Non-Aggressive Access**: The re-check loop reuses the initial watcher's politeness exactly — bounded batches, randomized delays, serial-level concurrency, reused/cached client profiles, exponential backoff, and block/structure-change detection — and never re-checks a single project more often than the configured interval (FR-018, FR-019); pausing the watcher pauses the loop (FR-021).
- **III. Config Over Code**: All scoring weights and tuning values, the re-check interval, the grace period, the freshness thresholds, the `/top` default, and the auto-status toggle are read from settings; nothing about the model is fixed in code (FR-008, FR-009, FR-025, FR-033).
- **IV. Idempotent Ingestion & Non-Destructive History**: Snapshots are appended, never overwritten; trajectory, scores, outcomes, and tracking state are retained and backed up; automation never deletes owner data and never overwrites a deliberately-set personal status (FR-014, FR-028, FR-029, FR-035).
- **V. Arabic-First Correctness**: Re-parsed bid counts and percentages handle Arabic-Indic digits and the not-yet-calculated state; timestamps are UTC, displayed in the owner's timezone; scored surfaces render right-to-left (FR-034, FR-037).
- **VI. Fail Loud**: The re-check loop never dies silently — failures log, alert, and retry under backoff; one project's failure never stalls the batch; the watcher's paused state remains visible (FR-020, FR-021, FR-023).
- **VII. Conservative, Fail-Closed Qualification**: Outcome capture is fail-closed — ambiguous endings are recorded unknown, never assumed hired; low-sample hiring rates are shrunk toward the neutral baseline rather than trusted at face value; only qualified projects are scored (FR-002, FR-011, FR-016).
- **VIII. No Platform Automation**: All re-checks are reads only; the loop, the scoring, the auto-status updates, and the Telegram surfaces never write or act on mostaql.com (FR-036).
- **IX. Local Security Hygiene**: Every scored-project surface and bot reply sits behind the existing single-owner authentication; no new public surface is added (FR-037).
- **X. Deployment-Portable**: All new state — scores, breakdowns, snapshots, outcomes, tracking state, and the new settings — is portable and part of the restorable backup set, with no machine-specific assumptions (FR-033, FR-035).

### Out of Scope (built in later features)

The following are explicitly NOT part of this feature and MUST NOT be built here:

- Any score-based notification threshold or gating — every qualified project still notifies, now carrying a score; gating notifications by score comes later.
- Tiered instant-vs-digest delivery, digests, and quiet hours.
- All aggregate analytics — posting heatmaps, average-bids-vs-age curves across projects, the share of projects hired vs not, "projects hired that I didn't apply to," and the funnel. This feature gathers the per-project trajectory and outcome data those will aggregate, but builds none of the charts itself (the per-project bid chart and status timeline on the detail view are in scope; cross-project aggregates are not).
- The client trend-history table and the clients directory.
- Multiple saved searches and additional categories.
- Any new in-app editor for the scoring model itself (weights and tuning values are configuration-driven this feature; editing them is done in settings, not through a dedicated model-builder UI).

### Key Entities

- **Opportunity Score**: A 0–100 ranking for a qualified project, with a stored per-component breakdown (the contribution of hiring rate, hire volume, budget, competition, freshness, and rating adjustment). Recomputed over the project's open life; frozen at the last open value once closed. Attaches to a project; computed from project + client facts and the configured weights.
- **Project Snapshot**: A timestamped record of one project at one moment — its bid count, status, and score. Many per project, forming the project's trajectory. Append-only, retained, and backed up.
- **Outcome**: A project's final disposition — still open, closed with no hire, or hired (awarded) — with **unknown** as the fail-closed default for genuinely ambiguous endings. One per project, set by the re-check loop.
- **Tracking State**: Per project, whether it is still being actively re-checked and when it was last checked; used to enforce the re-check interval and to stop tracking after the grace period.
- **Freshness Signal**: A derived green / yellow / red indicator of whether a project is still worth bidding on, computed from its trajectory against configurable thresholds. Derived for display from the latest snapshot and the project's age, not stored as a separate source of truth.
- **Scoring Model Settings** *(configuration)*: The component weights and all tuning values (neutral baseline and shrinkage strength, diminishing-returns caps, Tier-2 budget scale, freshness decay/age parameters, rating-adjustment bounds), plus the re-check interval, grace period, freshness thresholds, `/top` default count, and auto-status toggle. Read at runtime; never hard-coded.
- **Project** *(existing, extended)*: The collected Mostaql project. This feature reads its budget, tier, bid count, posted-at, and status to score it, updates its scraped status from the loop, and attaches the score, snapshots, outcome, and tracking state. Its tier classification (Feature 1) is consumed, not redefined.
- **Client** *(existing, read for scoring)*: The project's poster; its hiring rate, hire count/volume, average rating, and review count feed the score. Refreshed by the loop when stale; never written destructively.
- **Personal Project Record** *(existing, from Feature 3)*: The owner's personal layer. The optional auto-transition may set its status to "Expired / Missed" under the strict, reversible, non-destructive rules above; it is otherwise untouched by this feature.
- **Scrape Run / Watcher Polling State** *(existing)*: The re-check loop logs its runs like the watcher and honors the same paused/running state that `/pause` and `/resume` set.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every qualified project — including 100% of those collected before this feature — has a 0–100 opportunity score, and the owner can sort and filter the feed by it.
- **SC-002**: The owner can open any project and see, in plain per-component bars beside the active weights, why it scored what it did, and the components visibly combine to the displayed total.
- **SC-003**: Open projects are automatically re-checked on the configured schedule, and for any tracked project the owner can see a chart of how its bids grew and a timeline of its status changes.
- **SC-004**: A project that closes stops being re-checked after the configured grace period and shows a final outcome of hired, closed-no-hire, or unknown — with ambiguous endings recorded as unknown 100% of the time (never assumed hired).
- **SC-005**: A project's "still good?" indicator reflects its real trajectory: a crowded or closed project reads red and no longer looks attractive, while a fresh uncrowded one reads green.
- **SC-006**: Changing a scoring weight, a tuning value, the re-check interval, the grace period, a freshness threshold, or an auto-status toggle in settings takes effect on the next cycle with no code change and no redeploy.
- **SC-007**: Telegram project notifications show the score and tier, the "Why?" button returns the project's per-component breakdown, and `/top [n]` returns the current top open projects by score with links.
- **SC-008**: A high hiring rate from very few projects is dampened relative to the same rate from many projects (low-sample clients are shrunk toward the neutral baseline), and the existing low-sample flag remains accurate.
- **SC-009**: The re-check loop stays within polite bounds — bounded batches, randomized delays, serial-level concurrency, and backoff on 100% of rate-limit/block responses — and never re-checks a single project more often than the configured interval; pausing the watcher stops the loop.
- **SC-010**: With the optional auto personal-status transition on, only "Interested"-but-not-applied projects that close are flagged "Expired / Missed"; Applied/Won/Lost and deliberately-set statuses are never auto-changed, every auto-change is reversible and timestamped, and no automated process ever deletes personal data (verified by running re-check cycles and confirming personal data is unchanged).

## Assumptions

- **Builds on Features 1–3**: This feature reuses the existing local database, settings/configuration store, the scraper/parser and its politeness/backoff/block-detection, the client-refresh staleness rule, the scheduler, the projects feed and project detail (extended here), the dashboard authentication/session, the Telegram bot/notification channel with inline buttons and bot commands, and the watcher's paused/running state. No new scraping target or category is introduced.
- **Score scale and combination**: The opportunity score is a single 0–100 value; the six components each produce a normalized sub-score combined by the configured weights, which are normalized to sum to one before combination. The default weights have the hiring-rate component largest (assumed roughly: hiring rate 0.35, competition 0.20, hire volume 0.15, budget 0.15, freshness 0.10, rating adjustment 0.05); the exact defaults live in settings and are tunable.
- **Confidence shrinkage**: A client's hiring rate is pulled toward a configurable neutral baseline in proportion to how few projects it is based on (a low-sample rate counts for less); the baseline and the shrinkage strength are configured, not hard-coded. This complements — and does not replace — the existing low-sample flag.
- **Diminishing returns and caps**: Hire volume and budget use diminishing returns (additional volume/budget adds progressively less); the budget component has a configurable cap above which extra budget does not raise the score, and Tier 2 (fallback-floor) projects are scaled down on the budget component by a configurable factor.
- **Competition and bid velocity**: The competition component combines the current bid count with the *rate* of bids relative to time open; bid velocity is computed from the trajectory when at least two snapshots exist, and falls back to current bid count and age on the first re-check (no prior snapshot).
- **Freshness decay**: The freshness component decays with age since posting via a configurable decay (e.g. a half-life), so newer projects score higher; the freshness *signal* (green/yellow/red) is a separate, threshold-based view derived from the trajectory, distinct from the freshness *component* of the score.
- **Re-check interval and grace period defaults**: The re-check interval is independent of the fast new-project poll and defaults to a slower cadence (assumed on the order of ~30 minutes), and the tracking grace period defaults to 72 hours after close; both live in settings and are tunable.
- **Outcome inference is fail-closed**: An explicit Mostaql award records hired; a plain close with no visible award records closed-no-hire; anything genuinely ambiguous records unknown. The system never infers a hire from absence of evidence.
- **Scoring scope**: Only qualified projects are scored; disqualified and still-pending projects carry no score. Backfill scores all currently qualified projects once when the feature is first deployed, and the loop keeps open projects' scores live thereafter.
- **"Expired / Missed" status**: The optional auto-transition introduces (or reuses) a personal status value "Expired / Missed" within the configurable status set; it is only ever set by automation on an "Interested"-but-not-applied project that closes, is recorded as automated and timestamped, and is reversible by the owner.
- **`/top` semantics**: `/top` ranks currently open, qualified, tracked projects by their latest score; the default count is configurable, closed projects are excluded, and requesting more than exist returns the available list or a friendly message.
- **Manual refresh**: The dashboard reflects new scores, snapshots, and statuses on a manual refresh; live streaming is not required (consistent with Features 2 and 3).
- **Notifications unchanged in gating**: Every qualified project still notifies exactly as before; this feature only adds the score and tier to the message and the "Why?" button — it does not gate, tier, batch, or delay delivery (those are explicitly out of scope).

## Dependencies

- **Feature 1 (watcher)**: the scraper/parser, the polite-access and backoff/block-detection machinery, the client-refresh staleness rule, the two-tier budget classification (consumed, not redefined), the scheduler, the ScrapeRun logging, and the paused/running watcher state.
- **Feature 2 (dashboard)**: the application shell, owner authentication/session, the projects feed, the project detail view, and the settings UI/store — all extended here for the score column/sort/filter, the breakdown and lifecycle on detail, and the new tunables.
- **Feature 3 (personal pipeline & Telegram actions)**: the personal record and its configurable status set (for the optional auto personal-status transition), and the Telegram notification channel, inline buttons, and bot-command framework (for the score, the "Why?" button, and `/top`).
- **Settings store**: MUST hold all new tunables (weights, tuning values, re-check interval, grace period, freshness thresholds, `/top` default, auto-status toggle) so they take effect at runtime without code changes.
- **Backup process**: MUST include the new scores, breakdowns, snapshots, outcomes, and tracking state so all trajectory history is portable and restorable.
