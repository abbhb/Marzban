"""Persist the order of panel-owned subscription policy groups."""
import sqlalchemy as sa
from alembic import op

revision = "93f6d024bc58"
down_revision = "82e5c913ab47"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_group_order",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_names", sa.JSON(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_subscription_group_order_singleton"),
    )


def downgrade():
    op.drop_table("subscription_group_order")
