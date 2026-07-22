"""Add profile-aware activity and local notification preferences."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("profile_id", sa.String(36), nullable=True))
    op.create_index("ix_audit_events_profile_id", "audit_events", ["profile_id"])
    with op.batch_alter_table("audit_events") as batch:
        batch.create_foreign_key(
            "fk_audit_events_profile_id_profiles",
            "profiles",
            ["profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_table(
        "notification_preferences",
        sa.Column(
            "admin_id",
            sa.String(36),
            sa.ForeignKey("administrators.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("server_crashes", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_backups", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("low_disk_space", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("completed_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("fk_audit_events_profile_id_profiles", type_="foreignkey")
    op.drop_index("ix_audit_events_profile_id", table_name="audit_events")
    op.drop_column("audit_events", "profile_id")
