"""When each calendar feed was last imported successfully"""

import sqlalchemy as sa

from alembic import op

revision = "c81d5e3a07f6"
down_revision = "a4c7e2f19b83"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "calendar_sources", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE calendar_sources SET last_success_at = last_synced_at WHERE last_error = ''")


def downgrade():
    op.drop_column("calendar_sources", "last_success_at")
