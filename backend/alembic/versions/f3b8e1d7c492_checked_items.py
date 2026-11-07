"""Items checked off in the sidebar's task list"""

import sqlalchemy as sa

from alembic import op

revision = "f3b8e1d7c492"
down_revision = "e5c19b7a3d20"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "checked_items",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("checked_items")
