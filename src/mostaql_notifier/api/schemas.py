"""Response/request DTOs for the dashboard API (mirrors contracts/openapi.yaml).

Projection over Feature 1's ORM entities — no schema change. Missing numerics serialize as
``null`` (never coerced to 0) so the frontend can render "not calculated" / unknown correctly.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuthStatus(BaseModel):
    authenticated: bool
    auth_enabled: bool


class LoginRequest(BaseModel):
    password: str


class ProjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    url: str | None = None
    client_name: str | None = None
    # 0–100; null = not yet calculated ("لم يحسب بعد"), distinct from 0.0.
    client_hiring_rate: float | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    currency: str | None = None
    tier: int | None = None
    tier_label: str | None = None
    bids_count: int | None = None
    posted_at: datetime | None = None
    site_status: str
    eval_status: str
    qualified: bool
    # Feature 3 — personal projection (defaulted when no personal record exists yet).
    favorite: bool = False
    personal_status: str = "new"
    personal_status_label: str = ""
    tags: list[str] = []
    hidden: bool = False
    # Feature 4 — scoring projection (defaulted null for unscored / non-qualified projects).
    # 0–100; null = not yet scored, distinct from 0.0.
    score: float | None = None
    # Derived "still good?" signal ("green" | "yellow" | "red"); null when no scoring/trajectory yet.
    freshness: str | None = None


class ProjectListResponse(BaseModel):
    items: list[ProjectListItem]
    total: int
    page: int
    page_size: int


class ClientPanel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None
    hiring_rate: float | None = None
    projects_posted: int | None = None
    projects_open: int | None = None
    hires_count: int | None = None
    avg_rating: float | None = None
    reviews_count: int | None = None
    total_spent: float | None = None
    country: str | None = None
    member_since: str | None = None
    verified: bool = False


class ProjectDetail(ProjectListItem):
    description: str | None = None
    category: str | None = None
    skills: list[str] | None = None
    scraped_at: datetime | None = None
    client: ClientPanel | None = None
    same_client_projects: list[ProjectListItem] = []
    # Feature 3 — the full personal record embedded for the detail/workspace view.
    personal: PersonalRecord | None = None
    # Feature 4 — scoring projection (score/freshness inherited from ProjectListItem above).
    # Fail-closed final disposition ("open" | "closed_no_hire" | "hired" | "unknown"); null until scored.
    outcome: str | None = None
    # The stored per-component breakdown behind ``score``; null when the project was never scored.
    score_breakdown: ScoreBreakdown | None = None


class HomeOverview(BaseModel):
    found_today: int
    qualified_today: int
    total_projects: int
    total_clients: int
    last_successful_scrape: datetime | None = None
    latest_run_status: str | None = None
    health: str  # "green" | "red" | "unknown"
    # Feature 3 — surface the intentional-idle state distinctly from a fault (constitution VI).
    paused: bool = False


# ---------------------------------------------------------------------------
# Feature 4 — opportunity score breakdown + lifecycle DTOs (mirror contracts/openapi.yaml)
# ---------------------------------------------------------------------------


class ScoreComponent(BaseModel):
    """One weighted component of the opportunity score (renders as one bar)."""

    key: str
    label: str
    # The component's primary raw input (e.g. hiring rate %, bid count); null when unknown.
    raw: float | None = None
    sub_score: float  # normalized component score in [0, 1]
    weight: float  # this component's normalized weight (the six weights sum to 1)
    contribution: float  # points contributed: 100 × weight × sub_score


class ScoreBreakdown(BaseModel):
    """The explainable record behind a project's score (FR-004/FR-007)."""

    score: float  # total 0–100; equals the sum of the components' contributions
    components: list[ScoreComponent]
    # True when the configured weights were rescaled to sum to 1 before combining (FR-009).
    normalized: bool
    computed_at: datetime | None = None


class Snapshot(BaseModel):
    """One append-only re-check observation; many per project, time-ordered."""

    captured_at: datetime
    # Bids observed (Arabic-Indic safe); null when unknown / not-yet-calculated.
    bids_count: int | None = None
    site_status: str  # "open" | "closed" | "awarded" | "unknown"
    # Score at this moment; frozen once the project is closed; null when never scored.
    score: float | None = None


class StatusEvent(BaseModel):
    """A single site-status transition derived from the snapshot series (one per change)."""

    at: datetime  # when the status first became this value (UTC)
    status: str  # "open" | "closed" | "awarded" | "unknown"


class Lifecycle(BaseModel):
    """Response of GET /api/projects/{id}/lifecycle."""

    # Fail-closed final disposition; null when the project has never been scored/tracked.
    outcome: str | None = None
    snapshots: list[Snapshot] = []  # append-only bid/status/score trajectory, oldest first
    status_timeline: list[StatusEvent] = []  # deduped status changes


# ---------------------------------------------------------------------------
# Feature 3 — personal pipeline & workspace DTOs (mirror contracts/openapi.yaml)
# ---------------------------------------------------------------------------


class PersonalRecord(BaseModel):
    """The owner's personal layer for one project (response projection; built explicitly so
    ``status_label`` can be resolved from config)."""

    project_id: int
    favorite: bool
    status: str
    status_label: str
    tags: list[str]
    applied_at: datetime | None = None
    won_amount: float | None = None
    lost_reason: str | None = None
    notes: str
    board_position: float
    hidden: bool
    status_changed_at: datetime | None = None
    reminder_at: datetime | None = None  # reserved; inert this feature
    # Feature 4 — reversible auto-transition trail (null unless an automated change fired); the
    # detail view shows a one-click "undo" affordance when these are set.
    auto_status_from: str | None = None
    auto_status_at: datetime | None = None


class PersonalUpdate(BaseModel):
    """Partial create-or-update body. Any subset; the service applies the applied-once +
    status_changed_at rules. ``model_fields_set`` distinguishes "omitted" from "explicit null"."""

    favorite: bool | None = None
    status: str | None = None
    tags: list[str] | None = None
    applied_at: datetime | None = None
    won_amount: float | None = None
    lost_reason: str | None = None
    notes: str | None = None
    hidden: bool | None = None
    reminder_at: datetime | None = None


class BoardCard(BaseModel):
    project_id: int
    title: str | None = None
    url: str | None = None
    client_hiring_rate: float | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    currency: str | None = None
    tier: int | None = None
    tier_label: str | None = None
    bids_count: int | None = None
    posted_at: datetime | None = None
    tags: list[str] = []
    status: str
    board_position: float


class BoardColumn(BaseModel):
    key: str
    label: str
    cards: list[BoardCard] = []


class BoardResponse(BaseModel):
    columns: list[BoardColumn]


class BoardMoveRequest(BaseModel):
    project_id: int
    to_status: str
    position: float


class AttachmentItem(BaseModel):
    id: int
    project_id: int
    original_name: str
    file_type: str  # "pdf" | "docx" | "md"
    size_bytes: int
    uploaded_at: datetime
    can_preview: bool


class AttachmentListResponse(BaseModel):
    items: list[AttachmentItem]


class AttachmentRename(BaseModel):
    original_name: str


class ControlState(BaseModel):
    paused: bool


class PersonalStatusOption(BaseModel):
    """A configured pipeline stage (slug + Arabic label) for the feed/detail status pickers."""

    key: str
    label: str


class UploadConfig(BaseModel):
    """Config-driven upload limits, surfaced so the dropzone hint matches server enforcement."""

    allowed_types: list[str]
    max_bytes: int


class SettingItem(BaseModel):
    # bool first so a bool-typed setting serializes as a JSON boolean, not 1/0 (bool is an int
    # subclass); int next so an int-typed setting serializes as a JSON integer (120, not 120.0);
    # float for min_hiring_rate; str kept for forward-compat with non-numeric settings.
    key: str
    value: bool | int | float | str
    type: str  # "int" | "float" | "bool"
    min: float | None = None
    max: float | None = None
    label: str


class SettingsResponse(BaseModel):
    items: list[SettingItem]


class FieldError(BaseModel):
    key: str
    message: str


class ValidationErrorBody(BaseModel):
    detail: str
    errors: list[FieldError]


class ErrorBody(BaseModel):
    detail: str


# Resolve the forward reference ProjectDetail -> PersonalRecord now that both are defined.
ProjectDetail.model_rebuild()
