# Feature Specification: Watch-and-Notify MVP Loop

**Feature Branch**: `001-watch-notify-loop`
**Created**: 2026-06-23
**Status**: Draft
**Input**: User description: Continuously watch the mostaql.com development-category listing and push every qualifying new project to the owner's private Telegram within minutes of posting, capturing and storing project and client data reliably and correctly as the foundation for later features.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Near-real-time alerts for qualifying development projects (Priority: P1)

As the sole owner, I want every new qualifying development project pushed to my private Telegram within minutes of being posted, carrying the facts I need to decide whether to bid, so I can be one of the first to apply and stop losing good projects to slow response.

**Why this priority**: This is the entire reason the tool exists and the foundation every later feature builds on. With only this story shipped, the owner already gets the core value — timely, filtered opportunities — and the system reliably captures and stores the data that future features depend on.

**Independent Test**: With the loop running, a new development project is posted by a client whose hiring rate is above 0% and whose budget meets the primary floor. Within roughly five minutes a single Telegram message arrives containing the project's title, budget range with its tier, the client's hiring rate, current bid count, time since posting, category, and a direct link. Running the loop again produces no second message for the same project, and a stored record holds both the raw scraped content and the parsed fields for the project and its client.

**Acceptance Scenarios**:

1. **Given** the loop is running and a new qualifying development project appears in the listing, **When** the next check runs, **Then** the project is captured once, qualified, stored with raw and parsed data, and pushed to Telegram exactly once with all required facts.
2. **Given** a project from a client whose hiring rate is exactly 0%, **When** it is evaluated, **Then** it is recorded but never notified.
3. **Given** a project from a client whose hiring rate shows "لم يحسب بعد" (not yet calculated), **When** it is evaluated, **Then** it is treated as disqualifying and never notified.
4. **Given** a project already seen and notified on an earlier check, **When** later checks run, **Then** it is never notified again.
5. **Given** a qualifying project whose budget and counts are written in Arabic-Indic digits, **When** it is parsed, **Then** the numeric values are read correctly and the notification shows the correct figures.
6. **Given** a project that is closed or not in the development category, **When** it is evaluated, **Then** it is not notified.

---

### User Story 2 - Stay alive: health alerts, block detection, and run visibility (Priority: P2)

As the sole owner running this from my home network, I want the watch loop to detect when it is being blocked or the site has changed, alert me, and back off instead of hammering the site — and I want to be able to tell when the system was not running — so a silent failure never quietly costs me opportunities or my own browsing access.

**Why this priority**: The core loop is only trustworthy if it fails loudly and accesses the site politely. Because a block hits the same home connection the owner browses on, aggressive retrying is unacceptable. This story turns the loop from "works when everything is fine" into "safe to leave running unattended."

**Independent Test**: Simulate each block/change signal in turn — an HTTP 403, an HTTP 429, a CAPTCHA challenge, and zero projects parsed from a listing that is clearly not empty. In every case a Telegram health alert is sent, the loop backs off with increasing delay rather than retrying immediately, and the run is logged with its outcome. Separately, stop the loop and confirm the owner can detect the gap from the last-run/heartbeat signal.

**Acceptance Scenarios**:

1. **Given** a check receives an HTTP 403 or 429, **When** the response is handled, **Then** a health alert is sent, access backs off exponentially, and the system does not retry aggressively.
2. **Given** a listing page returns zero parseable projects when recent activity makes that implausible, **When** the run completes, **Then** this is flagged as a possible block or structure change and a health alert is sent instead of silently reporting "no new projects."
3. **Given** a CAPTCHA or challenge page is detected, **When** it is encountered, **Then** the system stops normal scraping, alerts the owner, and backs off.
4. **Given** a single project fails to parse or its client page errors, **When** the run continues, **Then** that one project is logged and skipped without crashing the run, and the remaining projects are still processed.
5. **Given** the loop has not completed a successful run within the expected interval, **When** the owner checks, **Then** the absence of recent runs is observable (downtime is detectable).
6. **Given** any check run, **When** it finishes, **Then** a run record exists capturing start and finish time and the counts of projects found, new, updated, and errors.

---

### User Story 3 - Dynamic two-tier budget rule with anti-flapping (Priority: P3)

As the sole owner, I want the budget floor to automatically widen the funnel during slow periods and tighten it again when good volume returns — without rapidly flipping back and forth — so I keep seeing enough opportunities in dry spells while the messages stay clearly labeled by quality tier.

**Why this priority**: The primary floor in Story 1 already delivers value. This story is an optimization on top of it: it adapts the floor to recent volume so the owner is neither starved during quiet periods nor flooded once activity recovers. Hysteresis keeps the behavior stable.

**Independent Test**: Drive the recent Tier-1 volume below the configured target and confirm the active floor lowers so that projects in the Tier-2 band begin qualifying, each clearly labeled Tier 2. Then drive Tier-1 volume above the target plus the buffer and confirm the floor restores to the primary value. Hold volume between the target and the buffer and confirm the floor does not flip back and forth.

**Acceptance Scenarios**:

1. **Given** the count of Tier-1 qualifying projects over the rolling window is at or above the target, **When** projects are evaluated, **Then** the primary floor is active and only Tier-1 projects qualify.
2. **Given** the Tier-1 count over the window drops below the target, **When** projects are evaluated, **Then** the active floor lowers, projects in the Tier-2 band qualify, and their notifications are clearly marked Tier 2.
3. **Given** the active floor has been lowered, **When** the Tier-1 count rises above the target plus the buffer, **Then** the primary floor is restored.
4. **Given** the Tier-1 count sits between the target and the target-plus-buffer, **When** evaluations run, **Then** the active floor does not switch (no flapping).
5. **Given** any qualifying notification, **When** it is sent, **Then** it states which tier the project qualified under.

---

### Edge Cases

- **Hiring rate missing, malformed, in Arabic digits, or "لم يحسب بعد"** → treated as disqualifying (fail closed); the project is recorded but never notified.
- **Budget missing entirely** → the budget filter cannot be satisfied; the project is disqualified (fail closed).
- **Budget one-sided (only minimum or only maximum present)** → the single available bound is used as the comparison value against the active floor (see Assumptions).
- **Budget in a non-USD currency** → normalized to USD via a configured conversion table before comparison; if no conversion is configured for that currency, the budget is treated as unevaluable and the project is disqualified (fail closed) (see Assumptions).
- **Client profile page fails to load** → the hiring rate cannot be determined, so the project is never admitted on a guess; it is left pending and retried on later runs up to a configured limit/age, and is never notified until its client data is obtained.
- **Bid count or posted-at time missing or in Arabic digits** → parsed when present (including Arabic-Indic digits and relative Arabic time expressions); when genuinely absent or unparseable these display as unknown but do not by themselves disqualify the project, since they are not qualification signals.
- **Listing returns fewer or zero items than expected** → distinguished from a genuine "no new projects" result; an implausibly empty or short listing is flagged as a possible block or structure change and raises a health alert.
- **Duplicate appearance of an already-processed project** → recognized by Mostaql project identifier and never notified twice.
- **A project that qualifies, is notified, then later changes (e.g., bid count rises)** → recorded as updated in the run counts but not re-notified (re-notification on change is out of scope for this feature).

## Requirements *(mandatory)*

### Functional Requirements

**Watch loop & scheduling**

- **FR-001**: The system MUST repeatedly check the development-category project listing, newest first, on a configurable interval (default every 2 minutes).
- **FR-002**: The watch loop MUST run continuously and MUST NOT terminate silently; on error it logs, alerts, retries, and continues.

**Idempotent ingestion**

- **FR-003**: The system MUST identify projects that are new since the last check using the Mostaql project identifier.
- **FR-004**: The system MUST never notify the owner about the same project more than once, enforced by a deduplication key derived from the project identifier.
- **FR-005**: A project that cannot be fully evaluated on a given run (e.g., client data unavailable) MUST be left in a pending state and re-attempted on subsequent runs up to a configurable retry limit/age, and MUST NOT be marked notified until it actually qualifies and is sent.

**Project data capture**

- **FR-006**: For each new project the system MUST gather: title, full description, project URL, category, skills/tags, budget minimum and maximum, currency, current bid/offer count, posted-at time, and open/closed state.

**Client data capture & caching**

- **FR-007**: For each project's client the system MUST gather: name, profile URL, hiring rate, number of projects posted, number open, number of hires (when shown), average rating, number of reviews, total spent (when shown), country, member-since date, and verification status.
- **FR-008**: The system MUST obtain client signals that are not present on the listing row (including hiring rate) by visiting the client's profile.
- **FR-009**: The system MUST cache client profiles and refresh a given client's profile at most once per configurable period (default 12 hours), reusing the cached profile within that window.

**Qualification filters**

- **FR-010**: The system MUST qualify a project only if ALL hard filters pass: hiring rate is real and above the configured minimum; budget meets the active floor; the project is open and in the development category; and the project passes the exclusion check.
- **FR-011**: The system MUST exclude any client whose hiring rate is exactly 0% or shown as "لم يحسب بعد" (not yet calculated); the default minimum hiring rate is strictly greater than 0% and is configurable.
- **FR-012**: The system MUST treat any missing, ambiguous, or unparseable qualification signal as disqualifying and MUST NEVER admit a project by guessing or defaulting a missing signal.
- **FR-013**: The system MUST apply an exclusion check as a distinct qualification stage; in this feature it is a pass-through with no rules configured, structured so rules can be added later without changing the qualification flow.

**Dynamic budget rule**

- **FR-014**: The system MUST treat budgets at or above the primary floor (default $250) as Tier 1.
- **FR-015**: The system MUST count Tier-1 qualifying projects over a configurable rolling window (default last 24 hours) and, when that count drops below a configurable target (default 10), lower the active floor to a configurable fallback (default $100) so that projects in the fallback-to-primary band (default $100–$249) qualify as Tier 2.
- **FR-016**: The system MUST restore the primary floor only once the Tier-1 count over the window rises above the target plus a configurable buffer (default above 12), so the floor does not flip back and forth (hysteresis).
- **FR-017**: The system MUST label every qualifying project and its notification with the tier (Tier 1 or Tier 2) under which it qualified.
- **FR-018**: The primary floor, fallback floor, target, buffer, and window length MUST all be configurable.

**Storage**

- **FR-019**: The system MUST store every project and client with BOTH the raw scraped content and the parsed fields, so data can be re-parsed later if the site layout changes.
- **FR-020**: Stored data MUST be sufficient for later features to build history on top of it (projects linked to their clients, with capture timestamps).
- **FR-021**: Automation MUST NOT delete or overwrite previously captured data; updates are additive or annotative.

**Notifications**

- **FR-022**: The system MUST push each qualifying project to the owner's private Telegram chat in near real time.
- **FR-023**: Each notification MUST include: title, budget range with its tier, hiring rate, current bid count, time since posting, category, and a direct link.
- **FR-024**: Notifications MUST be at-least-once with deduplication: a qualifying project is never silently dropped and the owner is never pinged twice for the same project.
- **FR-025**: This feature MUST NOT include an opportunity score, ranking, or score threshold in notifications; every notification has already passed the hard filters.

**Run logging & health**

- **FR-026**: The system MUST log every check run with its start and finish time and the counts of projects found, new, updated, and errors.
- **FR-027**: The system MUST detect signals of being blocked or of site-structure change — including zero projects parsed on a listing that is implausibly empty, a CAPTCHA/challenge page, and HTTP 403/429 — and send a Telegram health alert instead of continuing to access the site.
- **FR-028**: On a detected block or challenge, the system MUST back off (exponentially) and MUST NOT retry aggressively.
- **FR-029**: The owner MUST be able to determine when the system was not running (e.g., via a last-run/heartbeat signal), because it runs on a personal machine that can go offline.
- **FR-030**: A single failing project MUST be logged and skipped without crashing the run.

**Polite access**

- **FR-031**: All access MUST mimic light human browsing: randomized inter-request delays, low (effectively serial) concurrency, reused/cached client profiles, and exponential backoff after rate-limit or block responses.
- **FR-032**: Request volume MUST stay personal and low; the system MUST NOT behave like an aggressive crawler.

**Correctness: encoding, digits, time**

- **FR-033**: All text MUST be handled as UTF-8 with Arabic content preserved.
- **FR-034**: Parsing MUST correctly read Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩) in budgets, counts, and percentages, and MUST recognize the "لم يحسب بعد" hiring-rate state as a distinct, meaningful value rather than a parse failure or zero.
- **FR-035**: All timestamps MUST be stored in UTC.

**Configuration**

- **FR-036**: Every threshold, interval, weight, and rule described above MUST be read from configuration and MUST NOT be hard-coded.

**Scope guard**

- **FR-037**: The system MUST NOT take any action on mostaql.com beyond reading (no bidding, messaging, or any write/submit action).

### Key Entities

- **Client**: The account that posted a project, carrying reputation signals — name, profile URL, hiring rate (which may be unknown/"not yet calculated", itself meaningful), projects posted, projects open, hires, average rating, review count, total spent, country, member-since date, verification status. Stored with raw and parsed forms and a last-refreshed timestamp.
- **Project**: A single posting — title, description, project URL, category, skills/tags, budget minimum/maximum, currency, bid count, posted-at time, open/closed state — linked to its client and labeled Tier 1 or Tier 2. Stored with raw and parsed forms and a capture timestamp.
- **Scrape Run**: A record of each check — start/finish time, counts of found/new/updated/errors, and outcome status (success, block/challenge detected, structure-change suspected, error).
- **Notification**: A record of each Telegram push, with a deduplication key tying it to exactly one project, the tier sent, the message content, and the delivery time.
- **Configuration / Settings**: The store of all thresholds, intervals, floors, target, buffer, window length, minimum hiring rate, refresh period, retry limits, and toggles read at runtime.
- **Budget Policy State**: The current active floor and the rolling Tier-1 volume it is derived from, used to apply the dynamic budget rule with hysteresis.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A newly posted qualifying development project reaches the owner's Telegram within about 5 minutes of posting (measured from posted-at to delivery) for the large majority of projects.
- **SC-002**: Over any measurement window, no qualifying project (by these rules) is missed and none is sent more than once — zero missed, zero duplicates.
- **SC-003**: 100% of clients whose hiring rate is 0% or "لم يحسب بعد" never trigger a notification.
- **SC-004**: 100% of block or structure-change events (403, 429, CAPTCHA, implausibly empty listing) produce a Telegram health alert and a back-off, with no silent failures.
- **SC-005**: Arabic budgets, counts, and percentages, and the "لم يحسب بعد" state, are parsed correctly on a representative sample (no misread of Arabic-Indic digits and 100% recognition of the not-yet-calculated state).
- **SC-006**: Access stays within polite bounds — randomized delays and serial-level concurrency are observed, and a back-off is engaged on 100% of rate-limit/block responses rather than immediate retry.
- **SC-007**: The owner can determine, at any time, whether the system ran recently and when it last completed a successful check (downtime is always detectable).
- **SC-008**: Every project and client stored is reconstructable from its raw captured payload, so a later layout change does not lose previously captured data.

## Assumptions

- **Budget comparison basis**: A project's budget is compared against the active floor using its budget maximum by default; this basis is configurable. When only one bound is present, that bound is used as the comparison value. When no budget figure is present at all, the project is disqualified (fail closed).
- **Currency normalization**: Budget thresholds are expressed in USD. Budgets in other currencies are normalized to USD via a configurable conversion table; if a project's currency is missing or has no configured conversion, its budget cannot be evaluated and the project is disqualified (fail closed). This keeps qualification conservative and avoids admitting a project on a guessed exchange rate.
- **Single channel and single recipient**: Notifications and health alerts go to one private Telegram chat owned by the sole user; there is no other recipient, channel, or delivery method in this feature.
- **Single category**: Only the development category is watched in this feature; multiple categories and saved searches are out of scope.
- **"New" detection horizon**: New-project detection is based on the Mostaql project identifier against previously seen identifiers; on first ever run the system establishes a baseline rather than notifying the entire historical backlog.
- **Posted-at and bid count are display facts, not filters**: Missing or unparseable posted-at time or bid count does not disqualify a project; only the defined hard filters (hiring rate, budget, open + development category, exclusion check) gate qualification.
- **Relative Arabic time**: Posted-at values may appear as relative Arabic expressions and are converted to an absolute UTC timestamp where possible; when not parseable, time-since-posting is shown as unknown.
- **Re-notification on change is out of scope**: Once a project is notified, later changes to it (e.g., rising bid count) are recorded as updates but do not trigger a new notification; trajectory tracking is a later feature.

## Out of Scope *(for this feature)*

- Re-checking projects over time / trajectory tracking.
- The 0–100 opportunity score, ranking, and a score threshold.
- The web dashboard.
- Telegram inline buttons and the personal CRM.
- Digests, tiered delivery scheduling, and quiet hours.
- Multiple categories and saved searches.
