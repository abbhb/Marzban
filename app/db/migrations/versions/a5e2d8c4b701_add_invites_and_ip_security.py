"""add invitation-only registration and portal IP security

Revision ID: a5e2d8c4b701
Revises: f4c1a7b2d903
Create Date: 2026-07-14 00:30:00

"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op


revision = "a5e2d8c4b701"
down_revision = "f4c1a7b2d903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_invitation_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("code_prefix", sa.String(length=16), nullable=False),
        sa.Column("note", sa.String(length=500), server_default="", nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("use_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", sa.String(length=34), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_portal_invites_max_uses"),
        sa.CheckConstraint("use_count >= 0", name="ck_portal_invites_use_count"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_digest"),
    )
    op.create_index(
        "ix_portal_invitation_codes_code_digest",
        "portal_invitation_codes",
        ["code_digest"],
        unique=True,
    )

    op.create_table(
        "portal_invitation_uses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invitation_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["portal_accounts.id"]),
        sa.ForeignKeyConstraint(["invitation_id"], ["portal_invitation_codes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_index(
        "ix_portal_invitation_uses_account_id",
        "portal_invitation_uses",
        ["account_id"],
        unique=True,
    )
    op.create_index(
        "ix_portal_invitation_uses_invitation_id",
        "portal_invitation_uses",
        ["invitation_id"],
    )

    op.create_table(
        "portal_ip_blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("network", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=34), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", sa.String(length=34), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network"),
    )
    op.create_index("ix_portal_ip_blocks_network", "portal_ip_blocks", ["network"], unique=True)

    op.create_table(
        "portal_security_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("window_started_at", sa.DateTime(), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("failure_count > 0", name="ck_portal_security_attempt_count"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_ip", "kind", name="uq_portal_security_attempt_ip_kind"),
    )
    op.create_index(
        "ix_portal_security_attempts_source_ip",
        "portal_security_attempts",
        ["source_ip"],
    )

    settings_table = op.create_table(
        "portal_security_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auto_block_enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("login_failure_limit", sa.Integer(), server_default="8", nullable=False),
        sa.Column("login_window_seconds", sa.Integer(), server_default="900", nullable=False),
        sa.Column("registration_failure_limit", sa.Integer(), server_default="5", nullable=False),
        sa.Column("registration_window_seconds", sa.Integer(), server_default="600", nullable=False),
        sa.Column("auto_block_seconds", sa.Integer(), server_default="86400", nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "login_failure_limit BETWEEN 2 AND 100",
            name="ck_portal_security_login_limit",
        ),
        sa.CheckConstraint(
            "registration_failure_limit BETWEEN 2 AND 100",
            name="ck_portal_security_register_limit",
        ),
        sa.CheckConstraint(
            "login_window_seconds BETWEEN 60 AND 86400",
            name="ck_portal_security_login_window",
        ),
        sa.CheckConstraint(
            "registration_window_seconds BETWEEN 60 AND 86400",
            name="ck_portal_security_register_window",
        ),
        sa.CheckConstraint(
            "auto_block_seconds BETWEEN 0 AND 2592000",
            name="ck_portal_security_block_seconds",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        settings_table,
        [
            {
                "id": 1,
                "auto_block_enabled": True,
                "login_failure_limit": 8,
                "login_window_seconds": 900,
                "registration_failure_limit": 5,
                "registration_window_seconds": 600,
                "auto_block_seconds": 86400,
                "updated_at": datetime.utcnow(),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("portal_security_settings")
    op.drop_index("ix_portal_security_attempts_source_ip", table_name="portal_security_attempts")
    op.drop_table("portal_security_attempts")
    op.drop_index("ix_portal_ip_blocks_network", table_name="portal_ip_blocks")
    op.drop_table("portal_ip_blocks")
    op.drop_index("ix_portal_invitation_uses_invitation_id", table_name="portal_invitation_uses")
    op.drop_index("ix_portal_invitation_uses_account_id", table_name="portal_invitation_uses")
    op.drop_table("portal_invitation_uses")
    op.drop_index("ix_portal_invitation_codes_code_digest", table_name="portal_invitation_codes")
    op.drop_table("portal_invitation_codes")
