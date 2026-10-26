"""Retire account-level VLESS flow; inbound settings are authoritative."""
import sqlalchemy as sa
from alembic import op

revision = "b53d2eaf6910"
down_revision = "a42c1d9e580f"
branch_labels = None
depends_on = None


def upgrade():
    proxies = sa.table("proxies", sa.column("id", sa.Integer),
                       sa.column("type", sa.String), sa.column("settings", sa.JSON))
    connection = op.get_bind()
    for row in connection.execute(sa.select(proxies.c.id, proxies.c.settings).where(
            sa.func.lower(proxies.c.type) == "vless")).mappings().all():
        if isinstance(row["settings"], dict) and "flow" in row["settings"]:
            settings = dict(row["settings"])
            settings.pop("flow")
            connection.execute(proxies.update().where(proxies.c.id == row["id"]).values(settings=settings))


def downgrade():
    # The previous account model defaults missing flow to None/empty. Retired
    # per-account choices are intentionally not recreated; backups retain them.
    pass
