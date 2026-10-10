"""Scope external subscription sources to shared or private portal accounts.

Revision ID: 82e5c913ab47
Revises: 7a24d91b6e03
"""
import sqlalchemy as sa
from alembic import op

revision = "82e5c913ab47"
down_revision = "7a24d91b6e03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Name reflected legacy unnamed constraints so SQLite batch rebuild can
    # replace them without changing existing source/node IDs or selections.
    convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    legacy = sa.inspect(op.get_bind()).get_unique_constraints("external_subscription_sources")
    with op.batch_alter_table("external_subscription_sources", naming_convention=convention) as batch:
        for constraint in legacy:
            columns = constraint["column_names"]
            if columns in (["name"], ["group_name"]):
                batch.drop_constraint(constraint["name"] or f"uq_external_subscription_sources_{columns[0]}", type_="unique")
        batch.add_column(sa.Column("owner_account_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("scope_key", sa.Integer(), nullable=False, server_default="0"))
        batch.create_foreign_key("fk_external_sources_owner", "portal_accounts", ["owner_account_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_external_subscription_sources_owner_account_id", ["owner_account_id"])
        batch.create_check_constraint("ck_external_sources_scope", "scope_key = COALESCE(owner_account_id, 0)")
        batch.create_unique_constraint("uq_external_sources_scope_name", ["scope_key", "name"])
        batch.create_unique_constraint("uq_external_sources_scope_group", ["scope_key", "group_name"])


def downgrade() -> None:
    # A downgrade must not turn private feeds into shared feeds. Refuse while
    # private data exists; restore the paired pre-upgrade backup for rollback.
    count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM external_subscription_sources WHERE owner_account_id IS NOT NULL")).scalar()
    if count:
        raise RuntimeError("Private subscriptions exist; restore the pre-upgrade database and image together")
    with op.batch_alter_table("external_subscription_sources") as batch:
        batch.drop_constraint("uq_external_sources_scope_name", type_="unique")
        batch.drop_constraint("uq_external_sources_scope_group", type_="unique")
        batch.drop_constraint("ck_external_sources_scope", type_="check")
        batch.drop_index("ix_external_subscription_sources_owner_account_id")
        batch.drop_constraint("fk_external_sources_owner", type_="foreignkey")
        batch.drop_column("scope_key")
        batch.drop_column("owner_account_id")
        batch.create_unique_constraint("uq_external_subscription_sources_name", ["name"])
        batch.create_unique_constraint("uq_external_subscription_sources_group_name", ["group_name"])
