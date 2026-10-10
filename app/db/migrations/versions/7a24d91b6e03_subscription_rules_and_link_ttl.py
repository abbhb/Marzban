"""Editable subscription rules and configurable link lifetime.

Revision ID: 7a24d91b6e03
Revises: 6f11a2c9e4d0
"""
import sqlalchemy as sa
from alembic import op

revision = "7a24d91b6e03"
down_revision = "6f11a2c9e4d0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("mgma_settings") as batch:
        batch.drop_constraint("ck_mgma_settings_ttl_seconds", type_="check")
        batch.create_check_constraint(
            "ck_mgma_settings_ttl_seconds",
            "ttl_seconds = 0 OR ttl_seconds BETWEEN 30 AND 315360000",
        )
    op.create_table(
        "subscription_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rules", sa.JSON(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_subscription_rules_singleton"),
    )


def downgrade():
    # Downgrading must never silently turn a permanent bearer into a legacy
    # valid bearer. Revoke it before restoring the old settings range.
    op.execute("UPDATE users SET sub_access_token_digest = NULL, sub_access_issued_at = NULL, sub_access_consumed_at = NULL WHERE sub_access_expires_at IS NULL")
    op.execute("UPDATE mgma_settings SET ttl_seconds = 180 WHERE ttl_seconds = 0 OR ttl_seconds > 900")
    op.drop_table("subscription_rules")
    with op.batch_alter_table("mgma_settings") as batch:
        batch.drop_constraint("ck_mgma_settings_ttl_seconds", type_="check")
        batch.create_check_constraint("ck_mgma_settings_ttl_seconds", "ttl_seconds BETWEEN 30 AND 900")
