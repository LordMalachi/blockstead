"""Backup manifests, checksums, and per-profile retention policy."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backups", sa.Column("manifest_name", sa.Text()))
    op.add_column("backups", sa.Column("sha256", sa.String(64)))
    op.add_column("backups", sa.Column("included_paths", sa.Text()))
    # Existing profiles adopt the same default count-based retention that new
    # profiles receive; NULL means "no limit" for a rule.
    op.add_column(
        "profiles",
        sa.Column("backup_keep_count", sa.Integer(), server_default=sa.text("10")),
    )
    op.add_column("profiles", sa.Column("backup_keep_days", sa.Integer()))
    op.add_column("profiles", sa.Column("backup_max_total_mb", sa.Integer()))


def downgrade() -> None:
    op.drop_column("profiles", "backup_max_total_mb")
    op.drop_column("profiles", "backup_keep_days")
    op.drop_column("profiles", "backup_keep_count")
    op.drop_column("backups", "included_paths")
    op.drop_column("backups", "sha256")
    op.drop_column("backups", "manifest_name")
