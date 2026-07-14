"""replace per-account plan assignment with global plan visibility

Revision ID: b7f3e1a9c204
Revises: a5e2d8c4b701
Create Date: 2026-07-14 02:30:00

"""

import sqlalchemy as sa
from alembic import op


revision = "b7f3e1a9c204"
down_revision = "a5e2d8c4b701"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("portal_accounts", recreate="always") as batch:
        batch.drop_index("ix_portal_accounts_assigned_plan_id")
        batch.drop_column("assigned_plan_id")

    with op.batch_alter_table("subscription_plans", recreate="always") as batch:
        batch.alter_column(
            "is_active",
            new_column_name="is_visible",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            existing_server_default=sa.text("1"),
        )
        batch.drop_column("is_default")


def downgrade() -> None:
    with op.batch_alter_table("subscription_plans", recreate="always") as batch:
        batch.alter_column(
            "is_visible",
            new_column_name="is_active",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            existing_server_default=sa.text("1"),
        )
        batch.add_column(
            sa.Column(
                "is_default",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )

    with op.batch_alter_table("portal_accounts", recreate="always") as batch:
        batch.add_column(sa.Column("assigned_plan_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_portal_accounts_assigned_plan_id_subscription_plans",
            "subscription_plans",
            ["assigned_plan_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_portal_accounts_assigned_plan_id",
            ["assigned_plan_id"],
            unique=False,
        )
