"""Tomo planner: categories, event kinds, automatic horizon and reviewable proposals"""

import sqlalchemy as sa

from alembic import op

revision = "b7d41c2e9a10"
down_revision = "9f899d7db5f5"
branch_labels = None
depends_on = None

CATEGORY = "category IN ('focus', 'routine', 'personal', 'errand')"
KIND = "kind IN ('commitment', 'appointment', 'interview', 'personal')"


def upgrade():
    op.create_table(
        "proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("batch", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("footer", sa.Text(), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'applied', 'discarded', 'undone')"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("proposals", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_proposals_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_proposals_status"), ["status"], unique=False)

    op.add_column("preferences", sa.Column("planned_through", sa.String(length=10), nullable=True))
    if op.get_bind().dialect.name == "sqlite":
        # A batch rebuild would drop the tables' existing unnamed CHECK constraints, so use
        # SQLite's ADD COLUMN, which accepts inline constraints and references. SQLAlchemy
        # does not reflect ON DELETE from an inline reference, so `alembic check` on SQLite
        # reports a spurious FK change; CI checks drift on PostgreSQL.
        op.execute(
            "ALTER TABLE tasks ADD COLUMN category VARCHAR(12) DEFAULT 'focus' NOT NULL "
            f"CHECK ({CATEGORY})"
        )
        op.execute(
            "ALTER TABLE obligations ADD COLUMN kind VARCHAR(12) DEFAULT 'commitment' NOT NULL "
            f"CHECK ({KIND})"
        )
        op.execute(
            "ALTER TABLE chat_messages ADD COLUMN proposal_id CHAR(32) "
            "REFERENCES proposals (id) ON DELETE SET NULL"
        )
        return
    op.add_column(
        "tasks",
        sa.Column("category", sa.String(length=12), server_default="focus", nullable=False),
    )
    op.create_check_constraint("ck_tasks_category", "tasks", CATEGORY)
    op.add_column(
        "obligations",
        sa.Column("kind", sa.String(length=12), server_default="commitment", nullable=False),
    )
    op.create_check_constraint("ck_obligations_kind", "obligations", KIND)
    op.add_column("chat_messages", sa.Column("proposal_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_chat_messages_proposal_id",
        "chat_messages",
        "proposals",
        ["proposal_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        raise NotImplementedError(
            "Downgrading SQLite would drop existing CHECK constraints; recreate the demo database."
        )
    op.drop_constraint("fk_chat_messages_proposal_id", "chat_messages", type_="foreignkey")
    op.drop_column("chat_messages", "proposal_id")
    op.drop_column("preferences", "planned_through")
    op.drop_constraint("ck_obligations_kind", "obligations", type_="check")
    op.drop_column("obligations", "kind")
    op.drop_constraint("ck_tasks_category", "tasks", type_="check")
    op.drop_column("tasks", "category")
    with op.batch_alter_table("proposals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_proposals_status"))
        batch_op.drop_index(batch_op.f("ix_proposals_created_at"))
    op.drop_table("proposals")
