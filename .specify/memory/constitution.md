<!--
SYNC IMPACT REPORT
==================
Version change: none (bare template) → 1.0.0 (initial ratification)
Bump rationale: First concrete adoption of the constitution. No prior versioned
  content existed (the file held only template placeholders), so this is the
  initial ratification at 1.0.0 under the semantic-versioning policy below.

Principles defined (all newly authored from owner input):
  - I.   Personal & Single-Box
  - II.  Polite, Non-Aggressive Access
  - III. Config Over Code
  - IV.  Idempotent Ingestion & Non-Destructive History
  - V.   Arabic-First Correctness
  - VI.  Fail Loud
  - VII. Conservative, Fail-Closed Qualification
  - VIII.No Platform Automation
  - IX.  Local Security Hygiene
  - X.   Deployment-Portable

Sections added:
  - Operational Scope Boundaries (replaces template SECTION_2)
  - Development Workflow & Quality Gates (replaces template SECTION_3)

Sections removed: none (template placeholder slots were filled, not dropped).

Templates / artifacts reviewed for consistency:
  - .specify/templates/plan-template.md ........ ✅ updated (Constitution Check
      gate replaced with concrete gates derived from Principles I–X)
  - .specify/templates/spec-template.md ........ ✅ reviewed, already aligned
      (generic structure; constitutional constraints surface via plan gate)
  - .specify/templates/tasks-template.md ....... ✅ reviewed, already aligned
      (Polish/Cross-Cutting phase already covers security/observability tasks)
  - .specify/templates/commands/*.md ........... ⚠ N/A (no commands directory present)
  - README.md / docs/quickstart.md ............. ⚠ N/A (not yet created)

Deferred TODOs: none. RATIFICATION_DATE set to today's adoption date.
-->

# Mostaql Notifier Constitution

Mostaql Notifier is a personal, single-user tool that scrapes mostaql.com to surface and
track freelance projects worth bidding on. The principles below are non-negotiable and apply
to every feature, spec, plan, and task. Where a rule says MUST or MUST NEVER it is a hard
gate; a feature that violates it is not shipped until the violation is removed or the
constitution is formally amended.

## Core Principles

### I. Personal & Single-Box (MUST)

The system serves exactly one user — the owner — running on one machine in its supported
topology. There MUST be no multi-tenancy, no account or user-role system, no public SaaS
surface, and no feature built for anyone other than the owner. Any change that introduces a
second user class, a tenant boundary, or sign-up/onboarding for others is out of scope by
construction.

**Rationale**: Single-user scope keeps the system small, private, and matched to personal,
low-volume use; every avoided abstraction (auth tenancy, role models, billing) is complexity
that never has to be maintained.

### II. Polite, Non-Aggressive Access (MUST)

All data is scraped — Mostaql exposes no public API. Every request, on both the initial poll
and any re-scan, MUST behave like light human browsing: randomized inter-request delays, low
concurrency (effectively serial), cached and reused client profiles (cookies, headers,
user-agent), and exponential backoff on 429/403. On any sign of a block, CAPTCHA, or
page-structure change, the system MUST stop, alert the owner, and back off — it MUST NEVER
retry aggressively or attempt to defeat anti-bot controls. Volume stays personal and low.

**Rationale**: Aggressive scraping is the fastest way to get banned and lose the only data
source; politeness protects the owner's continued access and respects the platform.

### III. Config Over Code (MUST)

Every threshold, weight, interval, rule, toggle, and qualification criterion MUST be read from
a Settings store at runtime. No behavior-affecting value may be hard-coded or require a code
change or redeploy to alter. Defaults live in the Settings store, not as literals scattered
through logic; reading a "magic number" from source to change behavior is a constitution
violation.

**Rationale**: The owner must be able to tune scoring, intervals, and filters safely and
auditably without editing or redeploying code.

### IV. Idempotent Ingestion & Non-Destructive History (MUST)

Ingestion is idempotent: dedup is keyed on the Mostaql project ID, and a project is never
processed or ingested twice. Raw scraped payloads MUST always be stored alongside parsed
fields. Automation MUST NEVER delete or overwrite user data — notes, files, statuses, tags;
it may only add flags or annotations. History, time-series snapshots, and uploaded
attachments are retained and backed up. Destructive edits are owner-initiated only.

**Rationale**: Accumulated history and time-series tracking are the product's core value;
automation that can erase them would destroy the reason the tool exists.

### V. Arabic-First Correctness (MUST)

UTF-8 is used end to end. Arabic content renders right-to-left in the UI. Parsing MUST
explicitly handle Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩) and the "لم يحسب بعد" (not-yet-calculated)
state as a first-class case, never as a parse failure or a zero. Timestamps are stored in UTC
and displayed in the owner's configured timezone.

**Rationale**: The source is Arabic; silently mishandling digit forms, text direction, or the
not-calculated state corrupts both qualification decisions and what the owner sees.

### VI. Fail Loud (MUST)

Every scrape and re-scan run MUST emit a structured summary: found / new / updated / errors.
Background loops MUST NEVER die silently — failures are logged, alert the owner via Telegram,
and auto-retry under backoff. Notifications are at-least-once with deduplication: never
double-sent, never silently dropped. The owner MUST always be able to tell when the system was
not running (heartbeat / last-run visibility), because it runs on a personal machine that can
go offline.

**Rationale**: On a personal box, a silent crash means missed opportunities with no signal;
loud failure and downtime visibility are what make the system trustworthy.

### VII. Conservative, Fail-Closed Qualification (MUST)

Any missing or unparseable client signal — absent hiring rate, ambiguous percentage,
"لم يحسب بعد", or any value that cannot be confidently parsed — is treated as disqualifying.
The system MUST NEVER admit or qualify a project by guessing, defaulting, or inferring a
missing signal. When in doubt, the project is disqualified.

**Rationale**: A skipped borderline project costs nothing; a manual bid on an unqualified one
wastes the owner's scarce bidding effort. Absence of evidence is treated as disqualifying.

### VIII. No Platform Automation (MUST)

The tool only surfaces, scores, and organizes opportunities. It MUST NEVER auto-bid,
auto-submit proposals, auto-message clients, or take any write/action on mostaql.com. All
bidding and platform interaction is manual and owner-performed; the tool is decision support,
not an agent acting on the platform.

**Rationale**: Auto-acting on the platform risks the owner's account standing and the
platform's terms; keeping all writes manual keeps the owner in control and the tool low-risk.

### IX. Local Security Hygiene (MUST)

The dashboard sits behind authentication even when bound to localhost. Secrets live in
environment or secret storage and are NEVER committed to the repository. Uploaded files are
validated by type and size and served safely (no execution, correct content-type,
non-traversable paths). The scraper/worker process is never publicly exposed.

**Rationale**: Even a personal tool holds credentials, private notes, and attachments; local
convenience is not a license to drop the basic hygiene that prevents leaks and accidental
exposure.

### X. Deployment-Portable (MUST)

The system runs locally today but MUST carry no hard dependency on this specific machine — no
hostname, absolute-path, or OS-specific assumption baked into behavior. Moving the same stack
to an always-on VPS MUST be a redeploy (config + secrets + data restore), not a rewrite. All
state — database, attachments, settings — is portable and restorable from backup.

**Rationale**: The natural next step is an always-on host; designing for portability now turns
that migration into a redeploy instead of a forced rewrite.

## Operational Scope Boundaries

The following are permanently out of scope and constitute MUST-NEVER gates. A feature request
that requires any of these is rejected unless the constitution is amended first:

- Serving, authenticating, or onboarding any user other than the owner (Principle I).
- Aggressive scraping, parallel high-volume fetching, or any attempt to defeat anti-bot,
  rate-limit, or CAPTCHA controls (Principle II).
- Hard-coding any behavior-affecting threshold, interval, weight, or rule (Principle III).
- Automated deletion or overwriting of owner data — notes, files, statuses, tags (Principle IV).
- Admitting or qualifying a project from a guessed, defaulted, or inferred missing signal
  (Principle VII).
- Auto-bidding, auto-submitting proposals, or any automated write action on mostaql.com
  (Principle VIII).
- Exposing the scraper/worker process publicly, or committing secrets to the repository
  (Principle IX).

## Development Workflow & Quality Gates

Every feature flows through the spec → plan → tasks → implementation pipeline under these
principles:

- **Constitution Check (gating)**: Every `/speckit.plan` MUST include a Constitution Check that
  verifies compliance with all applicable principles (I–X) before Phase 0 research and re-checks
  after Phase 1 design. A failing gate blocks the plan until resolved or justified.
- **Specs**: Any spec that touches scraping, qualification, storage, notifications, or file
  uploads MUST state explicitly how it honors the relevant gates — politeness (II),
  non-destructive history and idempotency (IV), Arabic correctness (V), fail-loud observability
  (VI), fail-closed qualification (VII), and security hygiene (IX).
- **Tasks**: Task breakdowns MUST include the cross-cutting work the principles require where
  applicable — run logging and Telegram alerting (VI), raw-payload retention and backups (IV),
  authentication and upload validation (IX), and config-store wiring for new tunables (III).
- **Deviations**: Any departure from a principle MUST be recorded in the plan's Complexity
  Tracking table with the need, the rejected simpler alternative, and explicit owner sign-off.
  Undocumented deviations are defects.

## Governance

This constitution supersedes all other development practices for Mostaql Notifier. When a
spec, plan, task, or piece of code conflicts with a principle here, the constitution wins and
the conflicting artifact is changed.

- **Amendment procedure**: Amendments are proposed in writing (the change plus its rationale),
  reviewed by the owner, and applied by updating this file, bumping the version, refreshing the
  Sync Impact Report, and propagating any consequent changes to the dependent templates
  (`plan-template.md`, `spec-template.md`, `tasks-template.md`, and command/guidance docs).
- **Versioning policy** (semantic versioning of governance):
  - **MAJOR**: Backward-incompatible governance changes — a principle removed or redefined in a
    way that invalidates existing compliance.
  - **MINOR**: A new principle or section added, or material expansion of existing guidance.
  - **PATCH**: Clarifications, wording, and non-semantic refinements that do not change what
    compliance requires.
- **Compliance review**: The Constitution Check gate in every plan is the primary enforcement
  point. The owner reviews compliance at each plan and before each release; any MUST-NEVER
  breach is a release blocker.
- **Runtime guidance**: Agent and contributor runtime guidance lives in the repository's agent
  guidance file (e.g., `CLAUDE.md`) and MUST stay consistent with this constitution; on
  conflict, this constitution governs.

**Version**: 1.0.0 | **Ratified**: 2026-06-23 | **Last Amended**: 2026-06-23
