# Feature Specification: Analytics and Insights

**Feature Branch**: `006-analytics-insights`  
**Created**: 2026-06-30  
**Status**: Draft  
**Input**: User description: "Mostaql Notifier — Feature 6: analytics and insights. Turn the accumulated history (project records, scores, per-project bid/status/outcome trajectories, and my personal pipeline) into understanding: a dashboard analytics section of charts and auto-generated, plain-language tips answering when the best projects appear, how fast competition builds, what happened to projects after I saw them, how my own funnel converts, and what I should change. Reads existing data only; scrapes nothing and changes nothing about the watcher or my project records."

## User Scenarios & Testing *(mandatory)*

Features 1–4 built the machine that *gathers*: a polite watcher collects qualifying development projects, a
dashboard lets the owner browse and tune them, a personal pipeline layer records what the owner favourited,
applied to, won and lost, an opportunity score ranks every qualified project, and a watch-over-time loop
records each project's bid trajectory, status changes, and final outcome. All of that history now exists —
but it is only ever viewable **one project at a time**. The owner can open a single project and see its bid
chart and outcome, yet cannot answer the questions that actually move a win rate: *When do the best projects
appear? How fast does competition build? What became of the projects I saw — and which good ones did I miss?
Where does my own pipeline leak?* This feature is the **reading** half of the system: it aggregates the
already-collected records into a small set of clear charts and a handful of plain-language, rule-based tips,
so the owner can sharpen timing, selectivity, and approach over time.

Two invariants from the constitution govern everything here. First, this feature is **strictly read-only and
non-destructive** (Principle IV): it computes every chart and tip from records that already exist — projects,
scores, snapshots, outcomes, and personal pipeline rows — and it **writes nothing back** to project, watcher,
or personal data, performs **no scraping**, and takes **no action** on Mostaql. The only state it introduces
is its own configuration (the analytics timezone, the date range, and the tip thresholds). Second, it is
**honest under thin data** (Principles VI and VII): with little history, every chart shows a clear "not enough
data yet" state and every tip is **withheld** until the data behind it clears a configurable minimum support,
rather than presenting a misleading conclusion drawn from two data points.

The seven user stories below are prioritized and each maps to one analytical capability the owner asked for.
**User Story 1 (the posting heatmap)** is the foundation: it stands up the analytics section itself — the new
dashboard area, the configured analytics timezone, the date-range filter, and the graceful sparse-data
states every later chart reuses — while answering the single most actionable timing question, *"when should I
be watching?"*. Stories 2–6 each add one more aggregate view over the data Features 1–4 produced, and each can
be built, tested, and demonstrated on its own. **User Story 7 (the tips engine)** is the synthesis layer: it
reads the aggregates the earlier stories expose and renders them as plain sentences the owner can act on, so
it is sequenced last because each tip depends on its underlying aggregate already existing.

### User Story 1 - See when qualified projects appear, so I know when to watch (Priority: P1)

As the sole owner, I want a day-of-week × hour-of-day heatmap of when **qualified development projects** tend
to be posted — rendered in a single analytics timezone I configure — so I can see the peak windows worth
watching and be ready to bid the moment a good project lands. This story also stands up the analytics section
itself: a dedicated area in the dashboard, behind my existing login, with a date-range filter that scopes the
view and a clear "not enough data yet" state when history is too thin to draw a grid.

**Why this priority**: "When are the good projects posted?" is the most directly actionable timing question
and the cheapest to answer from existing data (every qualified project already carries its posting time). It
is also the natural place to build the section's shared scaffolding — the analytics area, the timezone
setting, the date-range filter, and the sparse-data state — that every later chart depends on. With only this
story shipped, the owner already gains a real edge (knowing the windows to be watching) and the analytics
section exists for the rest to slot into. It is the MVP.

**Independent Test**: Seed qualified projects with posting times spread across several weekdays and hours. Open
the analytics section and confirm a 7×24 heatmap renders, with the densest cells on the weekdays/hours that
hold the most qualified projects, labelled and coloured so the peak windows are obvious at a glance. Change
the analytics timezone setting and confirm the cells shift to the new timezone (a project near a day boundary
moves to the adjacent day/hour) with no code change. Narrow the date range and confirm only projects posted in
that window are counted. Run it against an almost-empty database and confirm a clear "not enough data yet"
state instead of a misleading near-blank grid.

**Acceptance Scenarios**:

1. **Given** qualified projects posted across various weekdays and hours, **When** I open the posting heatmap, **Then** I see a 7×24 (day-of-week by hour-of-day) grid whose cell intensity reflects how many qualified projects were posted in each weekday/hour bucket.
2. **Given** the heatmap, **When** I read it, **Then** every time bucket is expressed in the configured analytics timezone (not UTC and not the browser's timezone), and the busiest cells visibly mark the peak windows to be watching.
3. **Given** the analytics timezone setting, **When** I change it, **Then** the heatmap re-buckets into the new timezone with no code change — including correctly moving a project posted near midnight into the adjacent local day/hour.
4. **Given** the date-range filter, **When** I set a range, **Then** the heatmap counts only qualified projects posted within that range.
5. **Given** too few qualified projects to populate a meaningful grid, **When** I open the heatmap, **Then** I see a clear "not enough data yet" state rather than a misleading sparse grid.
6. **Given** a qualified project whose exact posting time is unknown, **When** the heatmap is built, **Then** it falls back to the project's first-seen time so the project is still placed in a bucket, and the fallback does not crash the view.

---

### User Story 2 - See the project landscape: supply over time and the money I'm bidding into (Priority: P2)

As the sole owner, I want to see how the **supply of good projects** is trending and what the **budget
landscape** looks like, so I can tell whether qualified development work is rising or falling and understand
the money I'm bidding into. Specifically: qualified-vs-total project counts over time (by day and by week),
shown for the development category with room for more categories later; and a distribution of the budgets of
qualified projects together with the share that are **Tier 1** (full budget floor) versus the relaxed
**Tier 2** (fallback floor).

**Why this priority**: After "when to watch," the next thing that shapes strategy is *how much good work there
is and what it pays*. Both are simple, high-value distributions over the project records that already exist,
and both reuse the section scaffolding from Story 1, so they come next. With this story the owner can see at a
glance whether supply is drying up and whether they're mostly bidding into Tier-1 or relaxed Tier-2 money.

**Independent Test**: Seed projects across several weeks with a mix of qualified and disqualified, and a mix of
Tier-1 and Tier-2 budgets (including some with missing or one-sided budgets). Confirm a volume chart shows
qualified and total counts over time with a by-day and a by-week view, scoped to the date range and labelled
by category. Confirm a budget distribution chart shows how qualified budgets are spread and a clear Tier-1 vs
Tier-2 split. Confirm projects with a missing or one-sided budget are handled without error (grouped sensibly,
not silently dropped in a way that misstates the total).

**Acceptance Scenarios**:

1. **Given** projects collected over time, **When** I open the volume view, **Then** I see qualified and total project counts over time, with both a by-day and a by-week granularity, scoped to the selected date range.
2. **Given** the volume view, **When** I read it, **Then** it is presented for the development category and is structured so additional categories could be shown later without redesign.
3. **Given** qualified projects with a range of budgets, **When** I open the budget distribution, **Then** I see how those budgets are distributed and the share that are Tier 1 versus Tier 2.
4. **Given** qualified projects where some have a missing or one-sided budget (only a minimum or only a maximum), **When** the budget distribution is built, **Then** those projects are handled gracefully (placed in a clearly labelled "unknown/partial budget" grouping or derived from the available bound) and never crash or silently distort the chart.
5. **Given** the date-range filter, **When** I change it, **Then** both the volume and budget views recompute over the new window.
6. **Given** too little history, **When** I open either view, **Then** it shows a clear "not enough data yet" state.

---

### User Story 3 - See how fast competition builds, and how long I have to bid (Priority: P3)

As the sole owner, I want to see how **bid counts grow as a project ages** — built from the real per-project
trajectories the watch-over-time loop already recorded — so I can see the window in which I can still be an
early bidder, plus how bidding activity varies by hour of day. The headline I want is a concrete answer to
*"how long do I have before a project gets crowded?"* expressed against a configurable "crowded" bid level.

**Why this priority**: This converts the trajectory data (the most valuable thing Feature 4 gathered) into the
single most strategic number in the whole feature — the bidding window. It depends on the per-project snapshot
history existing, so it is sequenced after the simpler descriptive views, but it stands alone and is
separately testable.

**Independent Test**: Seed several projects each with a sequence of snapshots showing bids rising as the
project ages. Confirm a "bids vs. age" view renders an aggregate curve (e.g. median bids at each age bucket
since posting) built from those real trajectories, and a headline that states, in plain words, roughly how
many hours pass before a typical project reaches the configured "crowded" bid level. Confirm a "bidding by
hour of day" view shows when bidding activity concentrates, in the analytics timezone. Change the "crowded"
threshold in settings and confirm the headline window moves. Confirm a project with only one snapshot (no
trajectory yet) does not break the aggregate.

**Acceptance Scenarios**:

1. **Given** projects with recorded bid trajectories, **When** I open the competition view, **Then** I see an aggregate curve of how bid counts grow with project age (e.g. median and a spread, by age-since-posting bucket), built from the real per-project snapshots.
2. **Given** the competition view, **When** I read its headline, **Then** it answers in plain language roughly how long a typical project takes to reach the configured "crowded" bid level (e.g. "most projects pass N bids within about X hours of posting").
3. **Given** the "crowded" bid threshold in settings, **When** I change it, **Then** the headline window and the marker on the curve move accordingly with no code change.
4. **Given** bidding activity over time, **When** I open the "bidding by hour of day" view, **Then** I see how bidding concentrates across the 24 hours, expressed in the analytics timezone.
5. **Given** a project with only a single snapshot (no trajectory yet), **When** the aggregate curve is built, **Then** that project contributes what it can without breaking the aggregate, and the curve degrades gracefully.
6. **Given** too few projects with enough trajectory, **When** I open the competition view, **Then** it shows a clear "not enough data yet" state rather than a curve drawn from one or two projects.

---

### User Story 4 - See what became of the projects I saw, and what I missed (Priority: P4)

As the sole owner, I want to see, of the qualified projects the system tracked **to a conclusion**, what share
ended **hired** versus **closed with no hire**, the average and typical time from posting to closing — and,
importantly, the **projects that ended up hired that I never applied to** (my missed opportunities), so I can
see the cost of being slow or absent.

**Why this priority**: This is where the data starts to judge *me*: it shows whether the work I'm watching
actually converts to hires at all, how long the decision window really is, and — most pointedly — a concrete
count of good projects that got hired while I sat them out. It depends on the outcome data from Feature 4 and
on my personal pipeline records, so it follows the trajectory view.

**Independent Test**: Seed qualified projects with concluded outcomes (some hired, some closed-no-hire, some
still open, some genuinely unknown) and posting/closing times, plus personal records marking which I applied
to. Confirm an outcomes view shows the hired vs closed-no-hire share among **concluded** projects (excluding
still-open ones from the shares), the average **and** median time from posting to closing, and a clear count
(and list) of projects that ended hired but that I never applied to. Confirm still-open projects are excluded
from the outcome shares but still counted in volume (Story 2). Confirm an extreme time-to-close outlier does
not distort the headline (median is shown alongside the mean).

**Acceptance Scenarios**:

1. **Given** qualified projects tracked to a conclusion, **When** I open the outcomes view, **Then** I see the share that ended **hired** versus **closed with no hire**, computed only over concluded projects.
2. **Given** concluded projects with posting and closing times, **When** I read the time-to-close figure, **Then** I see both an average and a median time from posting to closing (so a single very long project does not distort the picture).
3. **Given** projects that ended **hired** and my personal pipeline records, **When** I open the missed-opportunities view, **Then** I see a clear count — and a list — of projects that were hired but that I never applied to.
4. **Given** projects that are still open (not concluded) or whose ending is genuinely **unknown**, **When** the outcome shares are computed, **Then** still-open projects are excluded from the hired/no-hire shares (and the unknown-ending ones are shown honestly, not folded into "hired").
5. **Given** the date-range filter, **When** I change it, **Then** the outcome shares, time-to-close, and missed-opportunity count recompute over the window.
6. **Given** too few concluded projects, **When** I open the outcomes view, **Then** it shows a clear "not enough data yet" state rather than a percentage drawn from a handful of projects.

---

### User Story 5 - See my own funnel, and where I drop off (Priority: P5)

As the sole owner, I want to see my **personal conversion funnel** — how many qualified projects I **saw**,
**favourited**, **applied to**, took into **discussion**, and **won** — with the conversion rate and the
typical time lag at each step, so I can see exactly where I leak: whether I'm seeing plenty but applying to
few, or applying but rarely converting.

**Why this priority**: This is the most personal, behaviour-changing view — it tells the owner what *they*
should do differently. It depends on the personal pipeline records (Feature 3) and reuses the
seen/applied/won framing the dashboard and bot already track, so it sits here. It is fully independent and
testable on its own.

**Independent Test**: Seed personal pipeline records across the stages (some favourited, fewer applied, fewer
in discussion, fewer won) with the timestamps that exist (seen, applied, last status change). Confirm a funnel
view shows the count at each stage from seen → favourited → applied → discussion → won, the step-to-step
conversion rate, and the typical (median) time lag at each step where timestamps allow. Confirm a funnel where
almost nothing was applied to still renders honestly (mostly-empty stages, not an error or a divide-by-zero).

**Acceptance Scenarios**:

1. **Given** my personal pipeline records, **When** I open the funnel view, **Then** I see the count at each stage: seen → favourited → applied → in discussion → won.
2. **Given** the funnel, **When** I read it, **Then** each step shows its conversion rate from the previous step (e.g. applied ÷ seen) and the typical time lag at that step where the underlying timestamps support it.
3. **Given** a funnel where I applied to very little (most stages near zero), **When** I open it, **Then** it renders honestly — empty or near-empty stages are shown as such, with no error and no misleading 0/0 rates.
4. **Given** the date-range filter, **When** I change it, **Then** the funnel counts and rates recompute over the window.
5. **Given** a step whose time lag cannot be computed because the needed timestamp was never recorded, **When** the funnel is shown, **Then** that step's lag is shown as unavailable rather than fabricated.
6. **Given** too little personal history, **When** I open the funnel, **Then** it shows a clear "not enough data yet" state.

---

### User Story 6 - Read a few plain-language tips I can act on (Priority: P6)

As the sole owner, I want a short list of **auto-generated, plain-language takeaways** derived from the
aggregates above — each a single sentence I can act on directly, each backed by my own data, and each shown
**only** when the data behind it clears a configurable minimum support — so I get conclusions, not just
charts, and never a tip that overreaches when data is thin. The tips are generated by **rules over my own
aggregated data**, never by any external AI service.

**Why this priority**: The tips are the synthesis that makes the whole section actionable, but each tip is a
sentence *about* an aggregate from Stories 1–5, so it depends on those aggregates already existing and is
sequenced last. It is independently testable: feed it aggregates and assert the right sentences appear (and
that none appear when support is below the threshold).

**Independent Test**: With enough seeded history, confirm the tips panel shows a handful of plain sentences of
the expected kinds — e.g. which days/hours most qualified projects appear (and therefore when to be ready);
how quickly bids pass a small threshold (and therefore how fast to bid); an observation about which timing
correlates with my own wins; a suggested score threshold that would have kept most of my past wins while
cutting noise (clearly framed as a suggestion that changes nothing); and a note when the budget floor has been
on the fallback (lower) level for a while because Tier-1 supply is low. Lower the data until a tip's support
falls below the configured minimum and confirm that tip simply disappears (no misleading statement). Confirm
each shown tip cites the data behind it. Confirm no tip is produced by an external AI service.

**Acceptance Scenarios**:

1. **Given** sufficient history, **When** I open the tips panel, **Then** I see a short, ranked list of plain-language sentences, each backed by an aggregate from the charts above and each citing the data behind it.
2. **Given** the posting heatmap data clears minimum support, **When** the tips regenerate, **Then** a tip names the peak day(s)/hour(s) qualified projects appear and frames it as when to be ready.
3. **Given** the competition data clears minimum support, **When** the tips regenerate, **Then** a tip states how quickly bids tend to pass the small/early threshold and therefore how fast to bid.
4. **Given** my wins and their timing clear minimum support, **When** the tips regenerate, **Then** a tip observes which timing correlates with my own wins (e.g. that my wins skew toward projects I applied to early).
5. **Given** my past wins and their scores clear minimum support, **When** the tips regenerate, **Then** a tip **suggests** a score threshold that would have retained most of my past wins while cutting noise — explicitly framed as a suggestion that sets, gates, or sends nothing.
6. **Given** the dynamic budget floor has been on the fallback (lower) level for a sustained period, **When** the tips regenerate, **Then** a tip notes that Tier-1 supply has been low and the floor has been relaxed for a while.
7. **Given** any tip whose supporting aggregate falls below the configured minimum support, **When** the tips regenerate, **Then** that tip is withheld entirely rather than shown with a weak or misleading basis.
8. **Given** the minimum-support and reference thresholds in settings, **When** I change them, **Then** which tips appear (and the numbers they cite) update accordingly with no code change.
9. **Given** the data updates (a new collection or refresh), **When** the tips regenerate, **Then** they reflect the latest data, and no tip is ever produced by an external AI service.

---

### User Story 7 - Filter, refresh, and trust the analytics (cross-cutting controls) (Priority: P7)

As the sole owner, I want every chart and tip to honour one **date-range filter** and to reflect data up to the
most recent collection (a manual refresh is fine; real-time is not required), and I want confidence that
opening and using the analytics section **never changes any of my data** — it reads, it never writes. I also
want it all to render Arabic correctly and right-to-left and to be clean, fast, and readable on both laptop and
phone.

**Why this priority**: These are the cross-cutting guarantees that make the section trustworthy and usable
rather than a new capability. They are listed last because they constrain and bind the other stories rather
than standing alone, but they are explicitly testable.

**Independent Test**: Set a date range and confirm every chart and every tip recomputes to that window
consistently. Confirm a manual refresh updates the views to the latest collected data and that there is no
expectation of live streaming. Snapshot the database (project, score, snapshot, and personal records), open
and exercise every analytics view and the tips, snapshot again, and confirm **zero** rows were created,
updated, or deleted in any of those tables. Confirm Arabic labels render right-to-left and the layout is
readable on a narrow phone viewport and a wide laptop viewport.

**Acceptance Scenarios**:

1. **Given** the analytics section, **When** I set a date range, **Then** every chart and every tip recomputes consistently to that window.
2. **Given** new data has been collected, **When** I manually refresh, **Then** the analytics reflect the latest data; real-time streaming is not required.
3. **Given** I open and use every analytics view and the tips, **When** I compare the project, score, snapshot, and personal records before and after, **Then** nothing was created, updated, or deleted — the section is strictly read-only.
4. **Given** the analytics section, **When** it renders, **Then** Arabic content and labels display correctly and right-to-left where applicable, and the charts are readable on both phone and laptop.
5. **Given** the analytics section, **When** I open it, **Then** it sits behind the dashboard's existing single-owner authentication like every other dashboard area.

---

### Edge Cases

- **Sparse or empty history (a fresh system)**: Every chart shows a clear "not enough data yet" state instead of a misleading near-blank or single-point visualization; every tip is withheld until its supporting aggregate clears the configured minimum support.
- **Projects still open / not yet concluded**: Excluded from the hired/no-hire outcome shares and from time-to-close, but still counted where appropriate (e.g. in volume trends and the posting heatmap).
- **Genuinely unknown endings**: Outcomes recorded as **unknown** (the fail-closed default) are never folded into "hired"; they are shown honestly or excluded from the hired/no-hire ratio, never silently counted as a hire.
- **Timezone conversion around day boundaries / DST**: A project posted near local midnight lands in the correct local day and hour after conversion; the heatmap and hourly views handle day-boundary and daylight-saving shifts in the analytics timezone without misplacing or double-counting buckets.
- **Unknown posting time**: A qualified project with no recorded posting time falls back to its first-seen time for the heatmap and time-of-day views so it is still placed, and the fallback is applied consistently (and noted where it materially affects a figure).
- **Missing or one-sided budgets**: Projects with no budget or only a minimum or only a maximum are placed in a clearly labelled partial/unknown grouping (or derived from the present bound) in the budget distribution — never dropped in a way that misstates totals or shares.
- **Mostly-empty funnel**: A funnel where the owner applied to very little renders honestly (near-empty stages shown as such); conversion rates with a zero denominator are shown as unavailable, never as a fabricated or divide-by-zero value.
- **Outliers in time-to-close or bid counts**: Headline figures are presented robustly — a median is shown alongside any mean, and a single extreme project cannot distort the headline window or share.
- **Few snapshots for the competition curve**: A project with only one snapshot contributes what it can (or is excluded from velocity) without breaking the aggregate curve; the curve is only drawn once enough projects have enough trajectory.
- **Two notions of "outcome"**: The **market** outcome (the project was hired/closed on Mostaql) and the **owner** outcome (the owner won/lost it) are distinct; the "hired projects I never applied to" view deliberately joins a market **hired** with the absence of a personal application.
- **Date range with no data**: A selected range that contains no qualifying records yields the "not enough data yet" state for the affected charts, not an error.
- **Changing the analytics timezone or a threshold**: Re-buckets/regenerates the affected views and tips on the next refresh with no code change.

## Requirements *(mandatory)*

### Functional Requirements

#### Part A — Analytics section foundation, timezone & controls

- **FR-001**: The system MUST provide a dedicated **analytics section** in the dashboard, reachable from the dashboard navigation and sitting behind the existing single-owner authentication, that contains the charts and tips defined below.
- **FR-002**: Every time-of-day analysis (the posting heatmap and the bidding-by-hour view) MUST be expressed in a single **configured analytics timezone**, read from settings; underlying timestamps remain stored in UTC and are converted to that timezone for bucketing and display. Changing the analytics timezone MUST re-bucket the affected views with no code change.
- **FR-003**: The analytics section MUST provide a single **date-range filter** that scopes every chart and every tip consistently to the selected window.
- **FR-004**: The analytics MUST reflect data **up to the most recent collection**; a manual refresh is acceptable and real-time/live streaming is NOT required.
- **FR-005**: Every chart MUST degrade gracefully under sparse data: when there is too little history to support it, it MUST show a clear **"not enough data yet"** state rather than a misleading visualization.
- **FR-006**: The analytics section MUST be strictly **read-only**: computing or viewing any chart or tip MUST NOT create, update, or delete any project, client, score, snapshot, outcome, or personal pipeline record, MUST perform **no scraping**, and MUST take **no action** on mostaql.com.

#### Part B — Posting heatmap

- **FR-007**: The system MUST present a **day-of-week × hour-of-day heatmap** of when **qualified** development projects tend to be posted, with cell intensity reflecting the count of qualified projects posted in each weekday/hour bucket, in the analytics timezone, scoped to the date range.
- **FR-008**: When a qualified project's exact posting time is unknown, the heatmap MUST fall back to the project's first-seen (collection) time so the project is still placed in a bucket, without erroring.

#### Part C — Volume trends & budget distribution

- **FR-009**: The system MUST present **volume trends** — qualified and total project counts over time, at both a **by-day** and a **by-week** granularity — scoped to the date range.
- **FR-010**: The volume view MUST be presented for the **development category** and MUST be structured so that **additional categories** can be added later without redesign (a category dimension is reserved even though only development exists today).
- **FR-011**: The system MUST present a **budget distribution** of qualified projects' budgets, together with the **share that are Tier 1 versus Tier 2** (consuming the existing two-tier classification — it reads the tier; it MUST NOT redefine the tier rule).
- **FR-012**: The budget distribution MUST handle projects with **missing or one-sided budgets** gracefully — placing them in a clearly labelled partial/unknown grouping or deriving from the present bound — never silently dropping them in a way that misstates totals or shares.

#### Part D — Competition dynamics

- **FR-013**: The system MUST present an aggregate **bids-vs-age curve** — how bid counts grow with project age — built from the **real per-project snapshot trajectories** already recorded, presented robustly (e.g. a median with a spread by age-since-posting bucket) so outliers do not distort it.
- **FR-014**: The competition view MUST surface a plain-language **headline answering "how long before a project gets crowded"** — roughly how long a typical project takes to reach a **configurable "crowded" bid level** — and MUST move that headline when the configured threshold changes, with no code change.
- **FR-015**: The system MUST present a **bidding-by-hour-of-day** view showing how bidding activity concentrates across the 24 hours, expressed in the analytics timezone.
- **FR-016**: The competition aggregates MUST degrade gracefully when projects have too little trajectory (e.g. a single snapshot contributes what it can or is excluded from velocity) and MUST show "not enough data yet" rather than a curve drawn from one or two projects.

#### Part E — Outcome analytics

- **FR-017**: The system MUST present, over qualified projects tracked **to a conclusion**, the **share that ended hired versus closed with no hire**, computed only over concluded projects (still-open projects excluded from the shares; genuinely **unknown** endings shown honestly and never counted as hires).
- **FR-018**: The system MUST present the **time from posting to closing** for concluded projects as both an **average and a median**, so a single extreme project does not distort the figure.
- **FR-019**: The system MUST present the **projects that ended hired that the owner never applied to** — both a count and a list — by joining a market **hired** outcome with the absence of a personal application (the owner's "missed opportunities").
- **FR-020**: Still-open projects MUST be excluded from the outcome shares and time-to-close but MUST still be counted where appropriate elsewhere (e.g. volume trends, posting heatmap).

#### Part F — My funnel

- **FR-021**: The system MUST present the owner's **personal conversion funnel** with the count at each stage: **seen → favourited → applied → in discussion → won**, scoped to the date range.
- **FR-022**: The funnel MUST show, for each step, the **conversion rate** from the previous step and the **typical (median) time lag** at that step where the underlying timestamps support it; where a step's lag cannot be computed from recorded timestamps, it MUST be shown as unavailable rather than fabricated.
- **FR-023**: The funnel MUST render **honestly when mostly empty** (e.g. the owner applied to very little): near-empty stages are shown as such, and any conversion rate with a zero denominator is shown as unavailable rather than as a divide-by-zero or fabricated value.

#### Part G — Insights / tips engine

- **FR-024**: The system MUST generate a short, ranked list of **plain-language tips**, each a single actionable sentence derived from the aggregates above and each **citing the data behind it**.
- **FR-025**: Each tip MUST appear **only** when its supporting aggregate clears a **configurable minimum support**; a tip whose basis is below that threshold MUST be **withheld entirely** rather than shown with a weak or misleading basis.
- **FR-026**: The tips engine MUST be able to produce at least the following kinds of statement when their data clears minimum support: (a) the peak day(s)/hour(s) qualified projects appear and therefore when to be ready; (b) how quickly bids tend to pass the small/early threshold and therefore how fast to bid; (c) an observation about which timing correlates with the owner's own wins; (d) a **suggested** score threshold that would have retained most of the owner's past wins while cutting noise; and (e) a note that the budget floor has been on the fallback (lower) level for a sustained period because Tier-1 supply is low.
- **FR-027**: The suggested score threshold (and any other suggestion) MUST be **advisory only** — it MUST NOT set, gate, change, or send anything (it changes no notification threshold, no setting, and triggers no message).
- **FR-028**: Tips MUST be **regenerated as the data updates** (on refresh / new collection) so they always reflect the latest aggregates.
- **FR-029**: Tips MUST be generated by **rules over the owner's own aggregated data** only — the system MUST NOT use any external AI service, or any source outside the owner's own collected data, to generate insights.

#### Cross-cutting: configuration, correctness, presentation, security & history

- **FR-030**: Every threshold this feature uses MUST be **read from settings and MUST NOT be hard-coded** — at minimum: the analytics timezone, the default date range, the minimum-support threshold(s) for tips, the "crowded" bid level, the small/early bid threshold used by the "how fast to bid" tip, and any reference values the tips cite. Changing any of them MUST take effect on the next refresh with no code change.
- **FR-031**: All re-derived counts and percentages MUST correctly handle the data's existing conventions — Arabic-Indic digits where relevant, an unknown bid count as distinct from zero, and an unknown client hiring rate/value as distinct from a real zero — consistent with Features 1 and 4.
- **FR-032**: All headline figures over potentially skewed data (time-to-close, bid counts, time lags) MUST be presented **robustly**, with a **median shown alongside any mean**, so a single outlier cannot distort the headline.
- **FR-033**: Timezone handling MUST be correct around **day boundaries and daylight-saving** transitions in the analytics timezone: a project near local midnight is bucketed into the correct local day/hour, with no double-counting or gaps.
- **FR-034**: Every analytics surface MUST render **Arabic content right-to-left** where applicable and MUST be **clean, fast, and readable on both laptop and phone**.
- **FR-035**: The analytics section MUST sit behind the dashboard's **existing single-owner authentication**; it MUST NOT introduce any new public surface.
- **FR-036**: The feature MUST NOT introduce any persisted history of its own beyond its **configuration** (the analytics timezone, the date range, and the tip thresholds); all charts and tips are **derived at read time** from existing records and are not a new source of truth that must be separately backed up.

### Constitutional Alignment *(how this feature honors the gates)*

This feature is read-only aggregation and presentation over already-collected data, so several scraping- and
write-oriented gates are satisfied **by construction**; it states explicitly how it honors each relevant gate:

- **II. Polite, Non-Aggressive Access**: This feature performs **no network access to mostaql.com at all** — it reads only the local database. It cannot be impolite because it never touches the site (FR-006).
- **III. Config Over Code**: The analytics timezone, the date range, the tip minimum-support thresholds, the "crowded" bid level, and every reference value the tips cite are read from settings; none are hard-coded, and changing them takes effect with no code change (FR-002, FR-014, FR-025, FR-030).
- **IV. Idempotent Ingestion & Non-Destructive History**: The section is strictly read-only — it creates, updates, and deletes nothing in the project, client, score, snapshot, outcome, or personal tables, and introduces no new history that must be preserved beyond its own configuration (FR-006, FR-036).
- **V. Arabic-First Correctness**: Re-derived counts/percentages handle Arabic-Indic digits and the unknown-vs-zero distinction; every time-of-day view is in the configured analytics timezone with correct day-boundary/DST handling; all surfaces render right-to-left (FR-031, FR-033, FR-034).
- **VI. Fail Loud / Honest Under Thin Data**: Every chart shows an explicit "not enough data yet" state and every tip is withheld below its minimum support, so the section never presents a confident-looking but unsupported conclusion (FR-005, FR-025, FR-032).
- **VII. Conservative, Fail-Closed Qualification**: Outcome analytics never assume a hire from absence of evidence — unknown endings stay unknown and are never folded into "hired" — and tips never overreach beyond what their support justifies (FR-017, FR-025, FR-026).
- **VIII. No Platform Automation**: The feature takes no action on mostaql.com; its strongest "action," the suggested score threshold, is advisory only and sets/sends nothing (FR-006, FR-027).
- **IX. Local Security Hygiene**: The analytics section sits behind the existing single-owner authentication and adds no new public surface (FR-035).
- **X. Deployment-Portable**: The only new state is configuration in the existing settings store; no machine-specific assumptions and nothing new to back up beyond settings (FR-030, FR-036).

### Out of Scope (built in later features or elsewhere)

The following are explicitly NOT part of this feature and MUST NOT be built here:

- Anything that depends on a **score-based notification threshold, digests, or quiet hours** — this feature may *suggest* a score threshold but MUST NOT set it, gate notifications by it, or send anything based on it.
- The **clients directory and per-client analytics**, client trend-history snapshots, and any client-by-client breakdown — this feature analyzes projects and the owner's own funnel, not individual clients.
- **Watchlists and blacklists.**
- **Multiple saved searches** and **additional categories beyond development** — the views reserve a category dimension for later but ship the development view only.
- **Any AI-generated insights or summaries** — every tip here is strictly a rule over the owner's own aggregated data, with no external AI service involved.
- **Exporting** the analytics (CSV / PDF / image export) — a later feature.

### Key Entities

- **Aggregate View** *(derived, read-only)*: A summary computed at read time from existing records — posting frequency by weekday/hour, qualified-vs-total counts over time, budget and Tier-1/Tier-2 distribution, bids-vs-age curve and bidding-by-hour, outcome shares and time-to-close, and the funnel counts/conversion/lag. Not stored as a new source of truth; recomputed from the underlying records (and re-buckets when the timezone or date range changes).
- **Insight / Tip**: A single plain-language statement generated by a rule when its supporting aggregate clears the configured minimum support. Carries the finding (the sentence) and the data behind it (the figures it cites). Advisory only — sets, gates, and sends nothing.
- **Analytics Settings** *(configuration — the only new persisted state)*: The analytics timezone, the default/selected date range, the tip minimum-support threshold(s), the "crowded" bid level, the small/early bid threshold, and any reference values the tips cite. Read at runtime; never hard-coded.
- **Project** *(existing, read-only here)*: The collected Mostaql project. This feature reads its posting time, first-seen time, category, budget, tier, qualified status, and bid count to build the heatmap, volume, budget, and competition views. Never written.
- **Opportunity Score & Outcome** *(existing, from Feature 4, read-only here)*: The per-project score feeds the suggested-threshold tip; the recorded market outcome (hired / closed-no-hire / open / unknown) and the close-observed time feed the outcome shares, time-to-close, and missed-opportunity views. Never written.
- **Project Snapshot** *(existing, from Feature 4, read-only here)*: The append-only per-project trajectory of bid count, status, and score over time — the real data behind the bids-vs-age curve and the bidding-by-hour view. Never written.
- **Personal Pipeline Record** *(existing, from Feature 3, read-only here)*: The owner's favourite flag, configurable status (new → interested → applied → in discussion → won → lost → expired/missed → ignored), application time, and win/loss — the data behind the funnel and the "hired projects I never applied to" view. Never written.
- **Budget Policy / Dynamic Floor** *(existing, from Feature 1, read-only here)*: The two-tier classification (Tier 1 = full floor, Tier 2 = relaxed fallback floor) consumed by the budget distribution, and the dynamic floor's fallback state consumed by the "Tier-1 supply has been low" tip. Read, never redefined.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The owner can see, at a glance, the weekday/hour windows when qualified development projects most often appear, in their chosen analytics timezone.
- **SC-002**: The owner can read a concrete, plain-language answer to how long they have before a typical project gets crowded, derived from real bid trajectories, and that answer moves when the "crowded" threshold is changed in settings.
- **SC-003**: The owner can see what share of concluded projects ended hired versus no-hire, and a clear count (and list) of projects that were hired but that they never applied to.
- **SC-004**: The owner can see their own funnel from seen → favourited → applied → discussion → won, with the conversion rate and the typical lag at each step (or "unavailable" where a timestamp was never recorded).
- **SC-005**: The owner gets a handful (a small, ranked set) of plain-language tips, each backed by their own data and citing it, and none appear when the data behind them is below the configured minimum support.
- **SC-006**: With very little history, every chart shows a clear "not enough data yet" state and unsupported tips are withheld — verified on a near-empty database (the section is honest, not misleading).
- **SC-007**: Every time-of-day view matches the configured analytics timezone, including projects near a day boundary, and changing the timezone setting re-buckets the views with no code change.
- **SC-008**: Opening and exercising every analytics view and the tips changes **zero** project, client, score, snapshot, outcome, or personal records — verified by comparing those tables before and after.
- **SC-009**: Headline figures over skewed data (time-to-close, bid counts, lags) show a median alongside any mean, so a single extreme outlier does not distort the headline.
- **SC-010**: The budget distribution and the Tier-1/Tier-2 share render correctly, including projects with missing or one-sided budgets, without error or misstated totals.
- **SC-011**: The single date-range filter narrows every chart and every tip consistently to the selected window.
- **SC-012**: The analytics section renders Arabic right-to-left and stays readable on both a phone and a laptop viewport, behind the existing single-owner authentication.

## Assumptions

- **Builds on Features 1–4**: This feature reuses the existing local database, the settings/configuration store and its typed getters, the projects and clients records, the opportunity score and recorded outcomes, the append-only per-project snapshots, the personal pipeline records and their configurable status set, the two-tier budget classification and its dynamic fallback floor, the dashboard shell with single-owner authentication and navigation, and the established UTC-storage / owner-timezone display pattern. No new scraping target, category, or write path is introduced.
- **"Qualified" predicate**: A project counts as qualified when its evaluation status is *qualified* (the same predicate the feed, scoring, and `/top` already use); the heatmap, the volume "qualified" series, the budget distribution, and the competition/outcome views are over qualified projects unless a chart explicitly shows a total.
- **Analytics timezone**: The analytics timezone is its **own** setting that **defaults to the existing owner timezone** (currently Africa/Cairo) and follows the established read-a-tz-setting → compute local buckets → store/query in UTC pattern; an invalid value falls back to the owner timezone, consistent with existing helpers.
- **Posting time source**: The heatmap and time-of-day views use each project's recorded posting time, falling back to its first-seen (collection) time when the posting time is unknown; this fallback is applied consistently and noted where it materially affects a figure.
- **"Seen" in the funnel**: "Seen" is taken to mean the qualified projects that were surfaced to the owner (the ones notified / appearing in the feed) — the realistic top of the personal funnel — rather than every project ever collected; favourited, applied, in-discussion, and won are read from the personal records.
- **Funnel reach is cumulative and lags are best-effort**: Because the personal status set is ordered, each funnel stage counts projects that reached **at least** that stage; step lags are computed from the timestamps that are actually retained (first-seen, application time, and the most recent status-change time), and any step whose lag cannot be derived is shown as unavailable rather than estimated.
- **Time-to-close basis**: Time-to-close is measured from a project's posting time (falling back to first-seen when posting time is unknown) to the time its close was first observed; both an average and a median are shown.
- **Concluded vs open vs unknown**: "Concluded" means the recorded market outcome is hired or closed-no-hire; still-open projects are excluded from outcome shares and time-to-close; genuinely unknown endings are shown honestly and never counted as hires.
- **Two outcome notions**: The market outcome (hired/closed on Mostaql) and the owner outcome (won/lost) are distinct; "hired projects I never applied to" deliberately joins a market **hired** with the absence of a personal application.
- **Bidding-by-hour derivation**: "Bidding activity by hour of day" is derived from the change in recorded bid counts between consecutive per-project snapshots, attributed to the hour (in the analytics timezone) in which the increase was observed; it is therefore an approximation bounded by the snapshot cadence, and is shown as a relative pattern rather than an exact bid log.
- **"Crowded" and "early" thresholds**: The bid level that defines "crowded" (for the competition headline) and the small/early bid level (for the "how fast to bid" tip) are configurable settings, not fixed in code.
- **Robust statistics**: Distributions and headline figures use outlier-robust presentation (median alongside mean, and a spread on the bids-vs-age curve) so a single extreme project cannot dominate.
- **Tip count and ranking**: The tips panel shows a small, ranked set (a handful, not an exhaustive dump); the maximum count and the minimum-support thresholds are configurable.
- **Suggested score threshold is advisory**: The suggested threshold is computed by replaying the owner's past wins against candidate score cut-offs to find one that retains most wins while excluding the most noise; it is presented as a suggestion only and changes, gates, and sends nothing.
- **Budget-fallback tip basis**: The "Tier-1 supply has been low" tip reads the dynamic budget floor's current/fallback state (the existing hysteresis mechanism) and fires when the floor has been on the fallback (lower) level for a sustained, configurable period.
- **Manual refresh**: The analytics reflect data as of the most recent collection and update on a manual refresh; live streaming is explicitly not required, consistent with Features 2–4.
- **Category dimension reserved**: Only the development category exists today; the volume and related views reserve a category dimension so additional categories can be added later without redesign.
- **Derived, not stored**: The aggregates and tips are computed at read time from existing records; the only new persisted state is this feature's configuration, so there is nothing new (beyond settings) to add to the backup set.

## Dependencies

- **Feature 1 (watcher)**: the project and client records and their fields (posting time, first-seen time, category, budget, currency, bid count), the two-tier budget classification and its dynamic fallback-floor state (consumed, not redefined), the settings store and its typed getters, the owner-timezone setting, and the UTC-storage convention.
- **Feature 2 (dashboard)**: the application shell, the single-owner authentication/session, the navigation, the settings UI/store (extended with the new analytics configuration), and the right-to-left Arabic presentation conventions — the analytics section is a new area within this shell.
- **Feature 3 (personal pipeline)**: the personal pipeline records and their configurable, ordered status set (favourite, applied, in-discussion, won, lost) and the timestamps they retain — the data behind the funnel and the missed-opportunity view; and the shared aggregation module the dashboard and bot already use for per-stage and today-bucketed counts, which this feature extends rather than duplicates.
- **Feature 4 (scoring & watch-over-time)**: the opportunity score (for the suggested-threshold tip), the recorded market outcome and close-observed time (for outcome shares, time-to-close, and missed opportunities), and the append-only per-project snapshot trajectory (for the bids-vs-age curve and bidding-by-hour).
- **Settings store**: MUST hold all new tunables (analytics timezone, default date range, tip minimum-support thresholds, "crowded" and small/early bid levels, and any reference values) so they take effect at runtime without code changes.
