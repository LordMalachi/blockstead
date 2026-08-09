"""Add central Discord relay handles and host heartbeat metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("discord_pairings", sa.Column("relay_pairing_id", sa.String(36), nullable=True))
    # SQLite cannot ALTER a table to add a unique constraint. A unique index
    # has the same null-friendly uniqueness semantics and works on all targets.
    op.create_index(
        "uq_discord_pairings_relay_id",
        "discord_pairings",
        ["relay_pairing_id"],
        unique=True,
    )
    op.add_column(
        "discord_connections",
        sa.Column("relay_connection_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "uq_discord_connections_relay_id",
        "discord_connections",
        ["relay_connection_id"],
        unique=True,
    )
    op.add_column(
        "discord_connections",
        sa.Column("last_relay_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_index("uq_discord_connections_relay_id", table_name="discord_connections")
    op.drop_column("discord_connections", "relay_connection_id")
    op.drop_index("uq_discord_pairings_relay_id", table_name="discord_pairings")
    op.drop_column("discord_pairings", "relay_pairing_id")
    op.drop_column("discord_connections", "last_relay_heartbeat_at")
