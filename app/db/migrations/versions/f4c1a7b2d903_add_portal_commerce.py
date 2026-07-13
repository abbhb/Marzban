"""add portal accounts, wallet ledger and subscription plans

Revision ID: f4c1a7b2d903
Revises: c8d9e0f1a2b3
Create Date: 2026-07-13 23:00:00

"""

import sqlalchemy as sa
from alembic import op


revision = "f4c1a7b2d903"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("data_limit", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("inbound_tags", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("price_minor >= 0", name="ck_subscription_plans_price"),
        sa.CheckConstraint("duration_days > 0", name="ck_subscription_plans_duration"),
        sa.CheckConstraint("data_limit >= 0", name="ck_subscription_plans_data_limit"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "portal_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=34), nullable=False),
        sa.Column("hashed_password", sa.String(length=128), nullable=False),
        sa.Column("wallet_balance_minor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("assigned_plan_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("password_reset_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("wallet_balance_minor >= 0", name="ck_portal_accounts_balance"),
        sa.ForeignKeyConstraint(["assigned_plan_id"], ["subscription_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_portal_accounts_assigned_plan_id", "portal_accounts", ["assigned_plan_id"])
    op.create_index("ix_portal_accounts_user_id", "portal_accounts", ["user_id"], unique=True)
    op.create_index("ix_portal_accounts_username", "portal_accounts", ["username"], unique=True)

    op.create_table(
        "portal_purchases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("actor_admin", sa.String(length=34), nullable=True),
        sa.Column("plan_name", sa.String(length=128), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("data_limit", sa.BigInteger(), nullable=False),
        sa.Column("inbound_tags", sa.JSON(), nullable=False),
        sa.Column("balance_before_minor", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_minor", sa.BigInteger(), nullable=False),
        sa.Column("effective_expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount_minor >= 0", name="ck_portal_purchases_amount"),
        sa.CheckConstraint(
            "kind IN ('self_purchase', 'admin_grant', 'admin_renewal')",
            name="ck_portal_purchases_kind",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["portal_accounts.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_portal_purchase_idempotency"),
    )
    op.create_index("ix_portal_purchases_account_id", "portal_purchases", ["account_id"])
    op.create_index("ix_portal_purchases_plan_id", "portal_purchases", ["plan_id"])

    op.create_table(
        "portal_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("plan_name", sa.String(length=128), nullable=False),
        sa.Column("price_paid_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("data_limit", sa.BigInteger(), nullable=False),
        sa.Column("inbound_tags", sa.JSON(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("purchased_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("data_limit >= 0", name="ck_portal_subscriptions_data_limit"),
        sa.ForeignKeyConstraint(["account_id"], ["portal_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_index("ix_portal_subscriptions_account_id", "portal_subscriptions", ["account_id"], unique=True)
    op.create_index("ix_portal_subscriptions_plan_id", "portal_subscriptions", ["plan_id"])

    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_minor", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("actor_admin", sa.String(length=34), nullable=True),
        sa.Column("purchase_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount_minor != 0", name="ck_wallet_transactions_amount"),
        sa.CheckConstraint("balance_after_minor >= 0", name="ck_wallet_transactions_balance"),
        sa.CheckConstraint(
            "kind IN ('admin_credit', 'purchase_debit')",
            name="ck_wallet_transactions_kind",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["portal_accounts.id"]),
        sa.ForeignKeyConstraint(["purchase_id"], ["portal_purchases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "kind",
            "idempotency_key",
            name="uq_wallet_transaction_idempotency",
        ),
    )
    op.create_index("ix_wallet_transactions_account_id", "wallet_transactions", ["account_id"])
    op.create_index("ix_wallet_transactions_purchase_id", "wallet_transactions", ["purchase_id"])


def downgrade() -> None:
    op.drop_index("ix_wallet_transactions_purchase_id", table_name="wallet_transactions")
    op.drop_index("ix_wallet_transactions_account_id", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_index("ix_portal_subscriptions_plan_id", table_name="portal_subscriptions")
    op.drop_index("ix_portal_subscriptions_account_id", table_name="portal_subscriptions")
    op.drop_table("portal_subscriptions")
    op.drop_index("ix_portal_purchases_plan_id", table_name="portal_purchases")
    op.drop_index("ix_portal_purchases_account_id", table_name="portal_purchases")
    op.drop_table("portal_purchases")
    op.drop_index("ix_portal_accounts_username", table_name="portal_accounts")
    op.drop_index("ix_portal_accounts_user_id", table_name="portal_accounts")
    op.drop_index("ix_portal_accounts_assigned_plan_id", table_name="portal_accounts")
    op.drop_table("portal_accounts")
    op.drop_table("subscription_plans")
