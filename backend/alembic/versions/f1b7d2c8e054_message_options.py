"""Tappable reply options on assistant messages"""

import sqlalchemy as sa

from alembic import op

revision = "f1b7d2c8e054"
down_revision = "e9a3c5d71b28"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_messages", sa.Column("options", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("chat_messages", "options")
