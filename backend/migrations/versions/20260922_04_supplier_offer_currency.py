"""supplier offer currency"""
from alembic import op
import sqlalchemy as sa

revision = "20260922_04"
down_revision = "20260922_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {x["name"] for x in sa.inspect(op.get_bind()).get_columns("supplier_offers")}
    if "currency" not in existing:
        with op.batch_alter_table("supplier_offers") as batch:
            batch.add_column(sa.Column("currency", sa.String(8), nullable=False,
                                       server_default="CNY"))


def downgrade() -> None:
    with op.batch_alter_table("supplier_offers") as batch:
        batch.drop_column("currency")
