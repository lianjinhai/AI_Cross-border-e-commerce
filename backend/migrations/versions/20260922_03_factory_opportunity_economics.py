"""factory opportunity economics"""
from alembic import op
import sqlalchemy as sa

revision = "20260922_03"
down_revision = "20260922_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {x["name"] for x in sa.inspect(op.get_bind()).get_columns("opportunity_supplier_matches")}
    definitions = {
        "expected_price": sa.Column("expected_price", sa.Float(), server_default="0"),
        "expected_unit_profit": sa.Column("expected_unit_profit", sa.Float(), server_default="0"),
        "expected_margin": sa.Column("expected_margin", sa.Float(), server_default="0"),
        "expected_monthly_revenue": sa.Column("expected_monthly_revenue", sa.Float(), server_default="0"),
    }
    with op.batch_alter_table("opportunity_supplier_matches") as batch:
        for name, column in definitions.items():
            if name not in existing:
                batch.add_column(column)


def downgrade() -> None:
    with op.batch_alter_table("opportunity_supplier_matches") as batch:
        for name in ("expected_monthly_revenue", "expected_margin",
                     "expected_unit_profit", "expected_price"):
            batch.drop_column(name)
