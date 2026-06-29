"""continuous watch scoring

Revision ID: 08bb5227930f
Revises: 8e6070483eaf
Create Date: 2026-06-28 19:06:50.618829

Feature 4 — adds the opportunity score + the watch-over-time trajectory. Two new tables
(``project_scores`` 1:1, ``project_snapshots`` append-only) plus two additive, non-destructive
deltas: a defaulted ``scrape_runs.kind`` so re-check runs log distinctly, and two nullable
``personal_records.auto_status_*`` columns for the reversible auto-transition. A data step
idempotently appends the ``expired_missed`` personal status.

The ``awarded`` value the model adds to ``ProjectStatus`` needs **no DDL**: ``make_enum`` is a
portable ``native_enum=False`` Enum with SQLAlchemy's default ``create_constraint=False``, so
``site_status`` is a plain ``VARCHAR`` with the membership enforced at the ORM ``validate_strings``
layer (verified: the existing ``projects`` table carries no CHECK). The new value is therefore
admitted by the model change alone — we do not rebuild the heavily-FK'd ``projects`` table.

All changes are reversible (round-trip tested in tests/integration/test_scoring_migration.py).
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text  # available for JSONB(astext_type=Text()) renderings
from sqlalchemy.dialects import postgresql
import mostaql_notifier.db.types

revision: str = '08bb5227930f'
down_revision: Union[str, None] = '8e6070483eaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Lightweight table handle for the settings data step (no ORM import in migrations).
_settings = sa.table(
    'settings',
    sa.column('key', sa.String),
    sa.column('value', sa.String),
    sa.column('value_type', sa.String),
)
_EXPIRED_MISSED = {"key": "expired_missed", "label": "منتهي/فائت"}


def _append_expired_missed(bind) -> None:
    """Idempotently append the ``expired_missed`` stage to an existing ``personal_statuses`` setting."""
    row = bind.execute(
        sa.select(_settings.c.value).where(_settings.c.key == 'personal_statuses')
    ).first()
    if row is None:
        return  # no row yet — seed_defaults inserts the full default (which already includes it)
    try:
        statuses = json.loads(row[0])
    except (TypeError, ValueError):
        return
    if not isinstance(statuses, list):
        return
    if any(isinstance(s, dict) and s.get('key') == 'expired_missed' for s in statuses):
        return  # already present — idempotent
    statuses.append(_EXPIRED_MISSED)
    bind.execute(
        _settings.update()
        .where(_settings.c.key == 'personal_statuses')
        .values(value=json.dumps(statuses, ensure_ascii=False))
    )


def upgrade() -> None:
    op.create_table(
        'project_scores',
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('breakdown', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('computed_at', mostaql_notifier.db.types.UtcDateTime(), nullable=True),
        sa.Column('outcome', sa.Enum('open', 'closed_no_hire', 'hired', 'unknown', name='outcome', native_enum=False), nullable=False),
        sa.Column('tracking_active', sa.Boolean(), nullable=False),
        sa.Column('last_checked_at', mostaql_notifier.db.types.UtcDateTime(), nullable=True),
        sa.Column('closed_observed_at', mostaql_notifier.db.types.UtcDateTime(), nullable=True),
        sa.Column('created_at', mostaql_notifier.db.types.UtcDateTime(), nullable=False),
        sa.Column('updated_at', mostaql_notifier.db.types.UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_scores_project_id_projects')),
        sa.PrimaryKeyConstraint('project_id', name=op.f('pk_project_scores')),
    )
    with op.batch_alter_table('project_scores', schema=None) as batch_op:
        batch_op.create_index('ix_project_scores_score', ['score'], unique=False)
        batch_op.create_index('ix_project_scores_tracking', ['tracking_active', 'last_checked_at'], unique=False)

    op.create_table(
        'project_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('captured_at', mostaql_notifier.db.types.UtcDateTime(), nullable=False),
        sa.Column('bids_count', sa.Integer(), nullable=True),
        sa.Column('site_status', sa.Enum('open', 'closed', 'awarded', 'unknown', name='project_status', native_enum=False), nullable=False),
        sa.Column('score', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_snapshots_project_id_projects')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_snapshots')),
    )
    with op.batch_alter_table('project_snapshots', schema=None) as batch_op:
        batch_op.create_index('ix_project_snapshots_project_captured', ['project_id', 'captured_at'], unique=False)

    with op.batch_alter_table('personal_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auto_status_from', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('auto_status_at', mostaql_notifier.db.types.UtcDateTime(), nullable=True))

    # NOT NULL on an existing, possibly-populated table needs a server default for prior rows.
    with op.batch_alter_table('scrape_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(), nullable=False, server_default='poll'))

    # Data step — give existing DBs the new personal stage (fresh DBs already have it via seed_defaults).
    _append_expired_missed(op.get_bind())


def downgrade() -> None:
    # Leaves the additive settings data (the appended personal stage) in place — it is harmless.
    with op.batch_alter_table('scrape_runs', schema=None) as batch_op:
        batch_op.drop_column('kind')

    with op.batch_alter_table('personal_records', schema=None) as batch_op:
        batch_op.drop_column('auto_status_at')
        batch_op.drop_column('auto_status_from')

    with op.batch_alter_table('project_snapshots', schema=None) as batch_op:
        batch_op.drop_index('ix_project_snapshots_project_captured')
    op.drop_table('project_snapshots')

    with op.batch_alter_table('project_scores', schema=None) as batch_op:
        batch_op.drop_index('ix_project_scores_tracking')
        batch_op.drop_index('ix_project_scores_score')
    op.drop_table('project_scores')
