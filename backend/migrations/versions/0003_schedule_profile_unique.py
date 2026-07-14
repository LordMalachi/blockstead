"""Keep one schedule per profile in legacy create-all databases."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("schedules")
    if not any(constraint["column_names"] == ["profile_id"] for constraint in constraints):
        with op.batch_alter_table("schedules") as batch:
            batch.create_unique_constraint("uq_schedules_profile_id", ["profile_id"])


def downgrade() -> None:
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("schedules")
    if any(constraint["name"] == "uq_schedules_profile_id" for constraint in constraints):
        with op.batch_alter_table("schedules") as batch:
            batch.drop_constraint("uq_schedules_profile_id", type_="unique")
