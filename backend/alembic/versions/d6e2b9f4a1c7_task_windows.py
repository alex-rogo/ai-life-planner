"""Time-of-day windows for tasks"""

import sqlalchemy as sa

from alembic import op

revision = "d6e2b9f4a1c7"
down_revision = "c81d5e3a07f6"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable ADD COLUMN works on SQLite without a batch rebuild (which would drop CHECKs).
    op.add_column("tasks", sa.Column("window_start", sa.String(length=5), nullable=True))
    op.add_column("tasks", sa.Column("window_end", sa.String(length=5), nullable=True))


def downgrade():
    op.drop_column("tasks", "window_end")
    op.drop_column("tasks", "window_start")
