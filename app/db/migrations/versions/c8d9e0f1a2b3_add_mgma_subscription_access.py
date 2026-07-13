"""add MGMA temporary subscription access

Revision ID: c8d9e0f1a2b3
Revises: 2b231de97dc3
Create Date: 2026-07-12 17:00:00

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "c8d9e0f1a2b3"
down_revision = "2b231de97dc3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("sub_access_token_digest", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("sub_access_issued_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("sub_access_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("sub_access_consumed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_users_sub_access_token_digest",
        "users",
        ["sub_access_token_digest"],
        unique=True,
    )

    op.create_table(
        "mgma_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "mode",
            sa.String(length=16),
            server_default="legacy",
            nullable=False,
        ),
        sa.Column(
            "ttl_seconds",
            sa.Integer(),
            server_default="180",
            nullable=False,
        ),
        sa.Column(
            "single_use",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "source_mode",
            sa.String(length=32),
            server_default="any",
            nullable=False,
        ),
        sa.Column("custom_cidrs", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_mgma_settings_singleton"),
        sa.CheckConstraint(
            "mode IN ('legacy', 'dual', 'ephemeral')",
            name="ck_mgma_settings_mode",
        ),
        sa.CheckConstraint(
            "ttl_seconds BETWEEN 30 AND 900",
            name="ck_mgma_settings_ttl_seconds",
        ),
        sa.CheckConstraint(
            "source_mode IN ('any', 'china', 'custom', 'china_or_custom')",
            name="ck_mgma_settings_source_mode",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("mgma_settings")
    op.drop_index("ix_users_sub_access_token_digest", table_name="users")
    op.drop_column("users", "sub_access_consumed_at")
    op.drop_column("users", "sub_access_expires_at")
    op.drop_column("users", "sub_access_issued_at")
    op.drop_column("users", "sub_access_token_digest")
