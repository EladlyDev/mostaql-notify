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


class HomeOverview(BaseModel):
    found_today: int
    qualified_today: int
    total_projects: int
    total_clients: int
    last_successful_scrape: datetime | None = None
    latest_run_status: str | None = None
    health: str  # "green" | "red" | "unknown"


class SettingItem(BaseModel):
    # int first so an int-typed setting serializes as a JSON integer (120, not 120.0); float for
    # min_hiring_rate; str kept for forward-compat with non-numeric settings.
    key: str
    value: int | float | str
    type: str  # "int" | "float"
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
