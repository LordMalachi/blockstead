"""Add persistent server schedules."""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("start_time", sa.String(5)),
        sa.Column("stop_time", sa.String(5)),
        sa.Column(
            "backup_before_stop", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "power_off_after_stop", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("wake_time", sa.String(5)),
        sa.Column("last_start_date", sa.String(10)),
        sa.Column("last_stop_date", sa.String(10)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("schedules")
