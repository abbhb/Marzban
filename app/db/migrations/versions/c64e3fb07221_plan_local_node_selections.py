"""Allow plans to select concrete host and XHTTP routes within an inbound."""
import sqlalchemy as sa
from alembic import op

revision = "c64e3fb07221"
down_revision = "b53d2eaf6910"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("subscription_plans") as batch:
        batch.add_column(sa.Column("local_node_selections", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("subscription_plans") as batch:
        batch.drop_column("local_node_selections")
