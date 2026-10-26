"""Persist per-plan policy group members."""
import sqlalchemy as sa
from alembic import op

revision = "a42c1d9e580f"
down_revision = "93f6d024bc58"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("subscription_plans") as batch:
        batch.add_column(sa.Column("group_members", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("subscription_plans") as batch:
        batch.drop_column("group_members")
