"""add encrypted external Clash subscriptions and plan selections

Revision ID: 6f11a2c9e4d0
Revises: d14f6a9b2c30
Create Date: 2026-08-04 21:00:00

"""

import sqlalchemy as sa
from alembic import op


revision = "6f11a2c9e4d0"
down_revision = "d14f6a9b2c30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    budget_lock = op.create_table(
        "external_subscription_budget_lock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("id = 1", name="ck_external_budget_lock_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(budget_lock, [{"id": 1, "version": 0}])

    op.create_table(
        "external_subscription_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("group_name", sa.String(length=128), nullable=False),
        sa.Column("url_ciphertext", sa.Text(), nullable=True),
        sa.Column("url_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "refresh_interval_minutes",
            sa.Integer(),
            server_default="360",
            nullable=False,
        ),
        sa.Column("next_refresh_at", sa.DateTime(), nullable=True),
        sa.Column("etag", sa.String(length=512), nullable=True),
        sa.Column("last_modified", sa.String(length=128), nullable=True),
        sa.Column("refresh_lease_until", sa.DateTime(), nullable=True),
        sa.Column("refresh_lease_token", sa.String(length=43), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="empty", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("node_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_node_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.String(length=34), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "refresh_interval_minutes >= 15",
            name="ck_external_sources_refresh_interval",
        ),
        sa.CheckConstraint(
            "status IN ('empty', 'ready', 'auth_required', 'error', 'disabled')",
            name="ck_external_sources_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_name"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_external_subscription_sources_next_refresh_at",
        "external_subscription_sources",
        ["next_refresh_at"],
    )

    op.create_table(
        "external_subscription_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("external_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("proxy_type", sa.String(length=32), nullable=False),
        sa.Column("payload_ciphertext", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["external_subscription_sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "external_key",
            name="uq_external_nodes_source_key",
        ),
    )
    op.create_index(
        "ix_external_subscription_nodes_source_id",
        "external_subscription_nodes",
        ["source_id"],
    )

    op.create_table(
        "plan_external_source_selections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "mode IN ('all', 'selected')",
            name="ck_plan_external_selection_mode",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["subscription_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["external_subscription_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "source_id",
            name="uq_plan_external_selection_source",
        ),
    )
    op.create_index(
        "ix_plan_external_source_selections_plan_id",
        "plan_external_source_selections",
        ["plan_id"],
    )
    op.create_index(
        "ix_plan_external_source_selections_source_id",
        "plan_external_source_selections",
        ["source_id"],
    )

    op.create_table(
        "plan_external_selected_nodes",
        sa.Column("selection_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["plan_external_source_selections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["external_subscription_nodes.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("selection_id", "node_id"),
    )


def downgrade() -> None:
    op.drop_table("plan_external_selected_nodes")
    op.drop_index(
        "ix_plan_external_source_selections_source_id",
        table_name="plan_external_source_selections",
    )
    op.drop_index(
        "ix_plan_external_source_selections_plan_id",
        table_name="plan_external_source_selections",
    )
    op.drop_table("plan_external_source_selections")
    op.drop_index(
        "ix_external_subscription_nodes_source_id",
        table_name="external_subscription_nodes",
    )
    op.drop_table("external_subscription_nodes")
    op.drop_index(
        "ix_external_subscription_sources_next_refresh_at",
        table_name="external_subscription_sources",
    )
    op.drop_table("external_subscription_sources")
    op.drop_table("external_subscription_budget_lock")
