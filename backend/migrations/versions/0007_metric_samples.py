"""Add persistent profile metric samples for overview trends."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metric_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_percent", sa.Float(), nullable=False),
        sa.Column("disk_percent", sa.Float(), nullable=False),
        sa.Column("process_memory_bytes", sa.BigInteger()),
        sa.Column("world_size_bytes", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_metric_samples_profile_id", "metric_samples", ["profile_id"])
    op.create_index("ix_metric_samples_created_at", "metric_samples", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_metric_samples_created_at", table_name="metric_samples")
    op.drop_index("ix_metric_samples_profile_id", table_name="metric_samples")
    op.drop_table("metric_samples")
