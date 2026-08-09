"""Add roles, saved setup provenance, and notification delivery state."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "administrators", sa.Column("role", sa.String(16), nullable=False, server_default="owner")
    )
    op.add_column(
        "administrators",
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "password_recovery_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "admin_id",
            sa.String(36),
            sa.ForeignKey("administrators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "saved_setups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column(
            "created_by_admin_id", sa.String(36), sa.ForeignKey("administrators.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "saved_setup_variants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "setup_id",
            sa.String(36),
            sa.ForeignKey("saved_setups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "source_profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="SET NULL")
        ),
        sa.Column(
            "protection_backup_id", sa.String(36), sa.ForeignKey("backups.id", ondelete="SET NULL")
        ),
        sa.Column("copied_paths", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_saved_setup_variants_setup_id", "saved_setup_variants", ["setup_id"])
    op.create_table(
        "notification_integrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "admin_id",
            sa.String(36),
            sa.ForeignKey("administrators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False, server_default="discord_webhook"),
        sa.Column("secret_key", sa.String(64), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "integration_id",
            sa.String(36),
            sa.ForeignKey("notification_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alert_id", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_status", sa.Integer()),
        sa.Column("detail", sa.Text(), nullable=False, server_default="Delivery is queued."),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_notification_deliveries_integration_id", "notification_deliveries", ["integration_id"]
    )
    op.create_index(
        "uq_notification_delivery_alert",
        "notification_deliveries",
        ["integration_id", "alert_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_notification_delivery_alert", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_integration_id", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_table("notification_integrations")
    op.drop_index("ix_saved_setup_variants_setup_id", table_name="saved_setup_variants")
    op.drop_table("saved_setup_variants")
    op.drop_table("saved_setups")
    op.drop_table("password_recovery_tokens")
    with op.batch_alter_table("administrators") as batch:
        batch.drop_column("disabled")
        batch.drop_column("role")
