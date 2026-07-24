"""Add best-effort player session history and the avatar opt-in preference."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_preferences",
        sa.Column("show_player_avatars", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "player_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("player_name", sa.String(16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_player_sessions_profile_id", "player_sessions", ["profile_id"])
    op.create_index("ix_player_sessions_player_name", "player_sessions", ["player_name"])


def downgrade() -> None:
    op.drop_index("ix_player_sessions_player_name", table_name="player_sessions")
    op.drop_index("ix_player_sessions_profile_id", table_name="player_sessions")
    op.drop_table("player_sessions")
    with op.batch_alter_table("notification_preferences") as batch:
        batch.drop_column("show_player_avatars")
