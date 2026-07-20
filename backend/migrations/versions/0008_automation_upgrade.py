"""Add weekday automation, one-time maintenance, and execution history."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.add_column(
            sa.Column(
                "weekdays",
                sa.String(32),
                nullable=False,
                server_default="0,1,2,3,4,5,6",
            )
        )
        batch.add_column(
            sa.Column("only_when_empty", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    op.create_table(
        "automation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_at", sa.String(16), nullable=False),
        sa.Column(
            "backup_before_stop", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "power_off_after_stop", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("wake_time", sa.String(5)),
        sa.Column("only_when_empty", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_automation_events_profile_id", "automation_events", ["profile_id"])
    op.create_index("ix_automation_events_run_at", "automation_events", ["run_at"])

    op.create_table(
        "automation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(24), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_automation_runs_profile_id", "automation_runs", ["profile_id"])


def downgrade() -> None:
    op.drop_index("ix_automation_runs_profile_id", table_name="automation_runs")
    op.drop_table("automation_runs")
    op.drop_index("ix_automation_events_run_at", table_name="automation_events")
    op.drop_index("ix_automation_events_profile_id", table_name="automation_events")
    op.drop_table("automation_events")
    with op.batch_alter_table("schedules") as batch:
        batch.drop_column("only_when_empty")
        batch.drop_column("weekdays")
