"""Allowed weekdays for tasks"""

import sqlalchemy as sa

from alembic import op

revision = "e9a3c5d71b28"
down_revision = "d6e2b9f4a1c7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("days", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("tasks", "days")
