"""Travel time on events, and the derived trips on the calendar"""

import sqlalchemy as sa

from alembic import op

revision = "a4c7e2f19b83"
down_revision = "f3b8e1d7c492"
branch_labels = None
depends_on = None

TRAVEL = "travel_minutes BETWEEN 0 AND 180"


def upgrade():
    if op.get_bind().dialect.name == "sqlite":
        # ADD COLUMN keeps the tables' unnamed CHECK constraints; a batch rebuild would drop them.
        op.execute(
            "ALTER TABLE obligations ADD COLUMN travel_minutes INTEGER DEFAULT '0' NOT NULL "
            f"CHECK ({TRAVEL})"
        )
        op.execute("ALTER TABLE obligations ADD COLUMN travel_mode VARCHAR(40) DEFAULT '' NOT NULL")
        op.execute("ALTER TABLE schedule_sessions ADD COLUMN travel BOOLEAN DEFAULT '0' NOT NULL")
        return
    op.add_column(
        "obligations",
        sa.Column("travel_minutes", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint("ck_obligations_travel_minutes", "obligations", TRAVEL)
    op.add_column(
        "obligations",
        sa.Column("travel_mode", sa.String(length=40), server_default="", nullable=False),
    )
    op.add_column(
        "schedule_sessions",
        sa.Column("travel", sa.Boolean(), server_default="0", nullable=False),
    )


def downgrade():
    op.drop_column("schedule_sessions", "travel")
    op.drop_column("obligations", "travel_mode")
    op.drop_column("obligations", "travel_minutes")
