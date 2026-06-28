"""ORM models for the watch-and-notify loop (data-model.md).

Reality note (verified 2026-06-23): a mostaql project page exposes the client's hiring rate and
several stats inline, but NO ``/u/`` profile link or stable client id. So:
  * client data is captured from the project page (one fetch yields project + client — more polite);
  * ``Client.mostaql_id`` is a derived surrogate (``derived:<hash>``) — see ``derive_client_key``;
  * the separate profile fetch / 12 h cache (FR-008/009) is reserved for when a profile URL becomes
    reachable and is a no-op in this feature.
"""
from __future__ import annotations

import enum
import hashlib

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .types import JSONType, UtcDateTime, make_enum, utcnow


class ProjectStatus(str, enum.Enum):
    open = "open"
    closed = "closed"
    unknown = "unknown"  # fail-closed default — never a parse failure


class EvalStatus(str, enum.Enum):
    baseline = "baseline"        # seen at first-run; never notified
    pending = "pending"          # awaiting (re)evaluation
    qualified = "qualified"
    disqualified = "disqualified"
    eval_error = "eval_error"    # exceeded retry cap; terminal; alerted


class RunStatus(str, enum.Enum):
    running = "running"
    success = "success"
    partial = "partial"          # some projects errored & were skipped
    failed = "failed"
    blocked = "blocked"          # circuit-breaker / challenge / structure-change


def derive_client_key(name: str | None, member_since: str | None) -> str:
    """Best-effort stable surrogate for a client lacking a site id (see module note)."""
    basis = f"{(name or '').strip()}|{(member_since or '').strip()}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"derived:{digest}"


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    mostaql_id: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(sa.String)
    profile_url: Mapped[str | None] = mapped_column(sa.String)
    # NULL == not-yet-calculated / unknown ("لم يحسب بعد"). 0.0 is a real, distinct value.
    hiring_rate: Mapped[float | None] = mapped_column(sa.Float)
    projects_posted: Mapped[int | None] = mapped_column(sa.Integer)
    projects_open: Mapped[int | None] = mapped_column(sa.Integer)
    hires_count: Mapped[int | None] = mapped_column(sa.Integer)
    avg_rating: Mapped[float | None] = mapped_column(sa.Float)
    reviews_count: Mapped[int | None] = mapped_column(sa.Integer)
    total_spent: Mapped[float | None] = mapped_column(sa.Numeric)
    country: Mapped[str | None] = mapped_column(sa.String)
    member_since: Mapped[str | None] = mapped_column(sa.String)  # raw site text; display-only
    verified: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    last_refreshed_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False)
    first_seen_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    projects: Mapped[list[Project]] = relationship(back_populates="client")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    mostaql_id: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    client_id: Mapped[int | None] = mapped_column(sa.ForeignKey("clients.id"))
    title: Mapped[str | None] = mapped_column(sa.String)
    description: Mapped[str | None] = mapped_column(sa.Text)
    url: Mapped[str | None] = mapped_column(sa.String)
    category: Mapped[str | None] = mapped_column(sa.String)
    skills: Mapped[list | None] = mapped_column(JSONType)
    budget_min: Mapped[object | None] = mapped_column(sa.Numeric)
    budget_max: Mapped[object | None] = mapped_column(sa.Numeric)
    currency: Mapped[str | None] = mapped_column(sa.String)
    bids_count: Mapped[int | None] = mapped_column(sa.Integer)
    posted_at: Mapped[object | None] = mapped_column(UtcDateTime)  # approximate; display-only
    scraped_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False)
    site_status: Mapped[ProjectStatus] = mapped_column(
        make_enum(ProjectStatus, "project_status"), nullable=False, default=ProjectStatus.unknown
    )
    eval_status: Mapped[EvalStatus] = mapped_column(
        make_enum(EvalStatus, "eval_status"), nullable=False, default=EvalStatus.pending
    )
    eval_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    last_eval_at: Mapped[object | None] = mapped_column(UtcDateTime)
    qualified_at: Mapped[object | None] = mapped_column(UtcDateTime)  # hysteresis-window basis
    tier: Mapped[int | None] = mapped_column(sa.Integer)
    notified: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    raw: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    client: Mapped[Client | None] = relationship(back_populates="projects")
    notifications: Mapped[list[NotificationLog]] = relationship(back_populates="project")
    # Feature 3 — the owner's personal layer (1:1) + uploaded files (many). Non-cascading: a
    # scraped project is never deleted by automation (constitution IV), so these are never orphaned
    # by the watcher; only owner-initiated deletes remove personal data.
    personal: Mapped[PersonalRecord | None] = relationship(
        back_populates="project", uselist=False
    )
    attachments: Mapped[list[Attachment]] = relationship(back_populates="project")

    __table_args__ = (
        sa.Index("ix_projects_posted_at", "posted_at"),
        sa.Index("ix_projects_scraped_at", "scraped_at"),
        sa.Index("ix_projects_qualified_at", "qualified_at"),
        sa.Index("ix_projects_eval_status", "eval_status"),
    )


class PersonalRecord(Base):
    """The owner's personal layer for one project (Feature 3).

    PK == FK (``project_id``) makes the 1:1 a structural guarantee — a second record for the same
    project is impossible, so "one record, consistent across the dashboard and the bot" (FR-029,
    SC-006) holds by construction. ``status`` is a config-driven slug (not a DB enum) so the owner
    can relabel/reorder stages without a migration (constitution III).
    """

    __tablename__ = "personal_records"

    project_id: Mapped[int] = mapped_column(
        sa.ForeignKey("projects.id"), primary_key=True
    )
    favorite: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="new")
    tags: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    applied_at: Mapped[object | None] = mapped_column(UtcDateTime)  # set once on first →applied
    won_amount: Mapped[object | None] = mapped_column(sa.Numeric)  # owner-entered, ≥ 0
    lost_reason: Mapped[str | None] = mapped_column(sa.Text)
    notes: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")  # markdown
    board_position: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    hidden: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    status_changed_at: Mapped[object | None] = mapped_column(UtcDateTime)
    reminder_at: Mapped[object | None] = mapped_column(UtcDateTime)  # reserved; inert this feature
    created_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[object] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="personal")

    __table_args__ = (
        sa.Index("ix_personal_records_status", "status"),
        sa.Index("ix_personal_records_hidden", "hidden"),
        sa.Index("ix_personal_records_favorite", "favorite"),
    )


class Attachment(Base):
    """A file the owner uploaded for a project (Feature 3, many-per-project).

    The bytes live on disk under ``attachments_dir/{project_id}/{stored_name}``; this row is the
    metadata + the safe storage handle. ``stored_name`` is a server-generated ``{uuid}.{ext}`` so no
    user input ever reaches a filesystem path (no traversal); ``original_name`` is retained verbatim
    for display only (constitution IX).
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    original_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    stored_name: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    file_type: Mapped[str] = mapped_column(sa.String, nullable=False)  # "pdf" | "docx" | "md"
    content_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    uploaded_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="attachments")

    __table_args__ = (sa.Index("ix_attachments_project_id", "project_id"),)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    started_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[object | None] = mapped_column(UtcDateTime)
    found_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    new_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    status: Mapped[RunStatus] = mapped_column(
        make_enum(RunStatus, "run_status"), nullable=False, default=RunStatus.running
    )
    notes: Mapped[str | None] = mapped_column(sa.Text)


class NotificationLog(Base):
    __tablename__ = "notifications_log"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    sent_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False)
    channel: Mapped[str] = mapped_column(sa.String, nullable=False, default="telegram")
    dedup_key: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    tier: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    project: Mapped[Project] = relationship(back_populates="notifications")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(sa.String, primary_key=True)
    value: Mapped[str] = mapped_column(sa.String, nullable=False)
    value_type: Mapped[str] = mapped_column(sa.String, nullable=False, default="str")


class AppState(Base):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(sa.String, primary_key=True)
    value: Mapped[str] = mapped_column(sa.String, nullable=False)
