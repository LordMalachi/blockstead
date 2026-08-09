"""Add paired Discord status-bot connections and command audit records."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_pairings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "admin_id",
            sa.String(36),
            sa.ForeignKey("administrators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_application_id", sa.String(32)),
        sa.Column("claimed_guild_id", sa.String(32)),
        sa.Column("claimed_channel_id", sa.String(32)),
        sa.Column("claimed_user_id", sa.String(32)),
        sa.Column("claimed_role_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discord_pairings_profile_id", "discord_pairings", ["profile_id"])
    op.create_table(
        "discord_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "admin_id",
            sa.String(36),
            sa.ForeignKey("administrators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False, unique=True
        ),
        sa.Column("application_id", sa.String(32), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("owner_user_id", sa.String(32), nullable=False),
        sa.Column("authorized_user_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("authorized_role_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("publish_address", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status_message_id", sa.String(32)),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("last_status_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discord_connections_guild_id", "discord_connections", ["guild_id"])
    op.create_index("ix_discord_connections_channel_id", "discord_connections", ["channel_id"])
    op.create_index(
        "uq_discord_connection_channel",
        "discord_connections",
        ["application_id", "guild_id", "channel_id"],
        unique=True,
    )
    op.create_table(
        "discord_command_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("discord_connections.id", ondelete="SET NULL"),
        ),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="SET NULL")),
        sa.Column("guild_id", sa.String(32)),
        sa.Column("channel_id", sa.String(32)),
        sa.Column("user_id", sa.String(32)),
        sa.Column("command", sa.String(64), nullable=False),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("safe_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_discord_command_audits_connection_id", "discord_command_audits", ["connection_id"]
    )
    op.create_index(
        "ix_discord_command_audits_created_at", "discord_command_audits", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_discord_command_audits_created_at", table_name="discord_command_audits")
    op.drop_index("ix_discord_command_audits_connection_id", table_name="discord_command_audits")
    op.drop_table("discord_command_audits")
    op.drop_index("ix_discord_connections_channel_id", table_name="discord_connections")
    op.drop_index("ix_discord_connections_guild_id", table_name="discord_connections")
    op.drop_index("uq_discord_connection_channel", table_name="discord_connections")
    op.drop_table("discord_connections")
    op.drop_index("ix_discord_pairings_profile_id", table_name="discord_pairings")
    op.drop_table("discord_pairings")
