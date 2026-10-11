"""Store each proposal's previewed outcome so applying it needs no second solve"""

import sqlalchemy as sa

from alembic import op

revision = "d2a8f6c41e07"
down_revision = "b7d41c2e9a10"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable columns without constraints: a plain ADD COLUMN on every dialect, no table rebuild.
    op.add_column("proposals", sa.Column("result", sa.JSON(), nullable=True))
    op.add_column("proposals", sa.Column("base_fingerprint", sa.String(length=64), nullable=True))


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        raise NotImplementedError(
            "Downgrading SQLite would drop existing CHECK constraints; recreate the demo database."
        )
    op.drop_column("proposals", "base_fingerprint")
    op.drop_column("proposals", "result")
