"""add stable per-user subscription path tokens

Revision ID: d14f6a9b2c30
Revises: b7f3e1a9c204
Create Date: 2026-07-20 12:00:00

"""

import secrets

import sqlalchemy as sa
from alembic import op


revision = "d14f6a9b2c30"
down_revision = "b7f3e1a9c204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("subscription_token", sa.String(length=43), nullable=True),
    )

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id FROM users")).fetchall()
    generated = set()
    for row in rows:
        token = secrets.token_urlsafe(32)
        while token in generated:
            token = secrets.token_urlsafe(32)
        generated.add(token)
        connection.execute(
            sa.text(
                "UPDATE users SET subscription_token = :token WHERE id = :user_id"
            ),
            {"token": token, "user_id": row[0]},
        )

    # Alembic automatically uses move-and-copy only on SQLite.  MySQL and
    # PostgreSQL retain their native ALTER TABLE path, avoiding a needless
    # rebuild of a potentially large users table.
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "subscription_token",
            existing_type=sa.String(length=43),
            nullable=False,
        )
    op.create_index(
        "ix_users_subscription_token",
        "users",
        ["subscription_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_subscription_token", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("subscription_token")
