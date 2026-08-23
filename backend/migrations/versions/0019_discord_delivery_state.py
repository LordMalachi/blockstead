"""Track Discord address consent and safe relay delivery results."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discord_connections",
        sa.Column("share_address", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text(
            "UPDATE discord_connections SET share_address = true "
            "WHERE publish_address = true"
        )
    )
    op.add_column(
        "discord_connections", sa.Column("last_delivery_result", sa.String(24), nullable=True)
    )
    op.add_column(
        "discord_connections",
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "discord_connections", sa.Column("last_delivery_detail", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("discord_connections", "last_delivery_detail")
    op.drop_column("discord_connections", "last_delivery_at")
    op.drop_column("discord_connections", "last_delivery_result")
    op.drop_column("discord_connections", "share_address")
