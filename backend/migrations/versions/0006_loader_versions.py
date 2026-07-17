"""Persist the exact mod-loader version selected for a profile."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("loader_version", sa.String(64)))


def downgrade() -> None:
    op.drop_column("profiles", "loader_version")
