"""Add encrypted entry nodes and cascade publishing modes to hosts."""
import sqlalchemy as sa
from alembic import op

revision = "c63e9a0427bd"
down_revision = "c64e3fb07221"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("cascade_mode", sa.String(16), nullable=False, server_default="off"))
        batch.add_column(sa.Column("cascade_entry_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cascade_entry_ciphertext", sa.Text(), nullable=True))
        batch.create_foreign_key("fk_hosts_cascade_entry", "external_subscription_nodes", ["cascade_entry_id"], ["id"], ondelete="RESTRICT")


def downgrade():
    with op.batch_alter_table("hosts") as batch:
        batch.drop_constraint("fk_hosts_cascade_entry", type_="foreignkey")
        batch.drop_column("cascade_entry_ciphertext")
        batch.drop_column("cascade_entry_id")
        batch.drop_column("cascade_mode")
