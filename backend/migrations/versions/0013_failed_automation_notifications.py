"""Add a local-alert preference for failed scheduled and manual automation."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_preferences",
        sa.Column("failed_automations", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    with op.batch_alter_table("notification_preferences") as batch:
        batch.drop_column("failed_automations")
