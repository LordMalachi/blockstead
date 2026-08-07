"""Persist local diagnostic captures and backup-destination checks."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_captures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("output_file", sa.Text()),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_diagnostic_captures_profile_id", "diagnostic_captures", ["profile_id"])

    op.create_table(
        "backup_destination_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("destination_path", sa.Text(), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("write_verified", sa.Boolean(), nullable=False),
        sa.Column("read_verified", sa.Boolean(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_backup_destination_checks_profile_id",
        "backup_destination_checks",
        ["profile_id"],
    )
    op.create_index(
        "ix_backup_destination_checks_checked_at",
        "backup_destination_checks",
        ["checked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_backup_destination_checks_checked_at", table_name="backup_destination_checks")
    op.drop_index("ix_backup_destination_checks_profile_id", table_name="backup_destination_checks")
    op.drop_table("backup_destination_checks")
    op.drop_index("ix_diagnostic_captures_profile_id", table_name="diagnostic_captures")
    op.drop_table("diagnostic_captures")
