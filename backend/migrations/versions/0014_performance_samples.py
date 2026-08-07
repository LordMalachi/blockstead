"""Add persisted, capability-gated Paper performance samples."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "performance_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("sampling_period_seconds", sa.Integer(), nullable=False),
        sa.Column("tps_one_minute", sa.Float()),
        sa.Column("tps_five_minutes", sa.Float()),
        sa.Column("tps_fifteen_minutes", sa.Float()),
        sa.Column("mspt_five_seconds", sa.Float()),
        sa.Column("mspt_ten_seconds", sa.Float()),
        sa.Column("mspt_sixty_seconds", sa.Float()),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_performance_samples_profile_id", "performance_samples", ["profile_id"])
    op.create_index("ix_performance_samples_created_at", "performance_samples", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_performance_samples_created_at", table_name="performance_samples")
    op.drop_index("ix_performance_samples_profile_id", table_name="performance_samples")
    op.drop_table("performance_samples")
