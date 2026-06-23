# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]  
**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]  
**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]  
**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]  
**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]
**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]  
**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]  
**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]  
**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Confirm this feature complies with every applicable principle in `.specify/memory/constitution.md`.
Mark each gate Pass / N/A, and justify any non-compliance in Complexity Tracking below.

- [ ] **I. Personal & Single-Box**: No multi-tenancy, accounts, roles, or features for anyone but the owner.
- [ ] **II. Polite, Non-Aggressive Access**: Any scraping uses randomized delays, low/serial concurrency, cached client profiles, and exponential backoff; blocks/CAPTCHAs alert and back off, never retry aggressively.
- [ ] **III. Config Over Code**: New thresholds, weights, intervals, rules, and toggles are read from the Settings store, not hard-coded.
- [ ] **IV. Idempotent Ingestion & Non-Destructive History**: Dedup by Mostaql project ID; raw payloads stored with parsed fields; automation never deletes/overwrites owner data; history and attachments backed up.
- [ ] **V. Arabic-First Correctness**: UTF-8 throughout; RTL rendering; Arabic-Indic digits and "لم يحسب بعد" handled; timestamps stored UTC, displayed in owner timezone.
- [ ] **VI. Fail Loud**: Runs log found/new/updated/errors; background loops log + Telegram-alert + auto-retry on failure; notifications at-least-once with dedup; downtime is observable.
- [ ] **VII. Conservative, Fail-Closed Qualification**: Missing/unparseable client signals disqualify; no admitting projects by guessing a signal.
- [ ] **VIII. No Platform Automation**: No auto-bid, auto-submit, or any write action on mostaql.com; bidding stays manual.
- [ ] **IX. Local Security Hygiene**: Dashboard behind auth even on localhost; secrets in env/secret storage (never committed); uploads validated by type/size and served safely; scraper/worker never publicly exposed.
- [ ] **X. Deployment-Portable**: No machine-specific assumptions; state is portable and restorable; VPS migration is a redeploy, not a rewrite.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
