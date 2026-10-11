"""Subscribed calendar feeds and their imported, read-only events"""

import sqlalchemy as sa

from alembic import op

revision = "e5c19b7a3d20"
down_revision = "d2a8f6c41e07"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "calendar_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=12), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider IN ('canvas', 'google', 'outlook', 'apple', 'other', 'demo')"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "external_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("uid", sa.String(length=400), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("course", sa.String(length=120), nullable=True),
        sa.Column("location", sa.String(length=300), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('event', 'deadline', 'all_day')"),
        sa.CheckConstraint("ends_at >= starts_at"),
        sa.ForeignKeyConstraint(["source_id"], ["calendar_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "uid"),
    )
    op.create_index("ix_external_events_source_id", "external_events", ["source_id"])
    op.create_index("ix_external_events_starts_at", "external_events", ["starts_at"])
    op.create_index("ix_external_events_ends_at", "external_events", ["ends_at"])


def downgrade():
    op.drop_table("external_events")
    op.drop_table("calendar_sources")
