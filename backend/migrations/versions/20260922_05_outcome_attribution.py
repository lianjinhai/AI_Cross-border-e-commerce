"""forecast outcome and factory opportunity attribution"""
from alembic import op
import sqlalchemy as sa

revision = "20260922_05"
down_revision = "20260922_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    forecast_cols = {x["name"] for x in inspector.get_columns("forecast_snapshots")}
    with op.batch_alter_table("forecast_snapshots") as batch:
        if "target_start" not in forecast_cols:
            batch.add_column(sa.Column("target_start", sa.DateTime(), nullable=True))
        if "target_end" not in forecast_cols:
            batch.add_column(sa.Column("target_end", sa.DateTime(), nullable=True))
    match_cols = {x["name"] for x in sa.inspect(op.get_bind()).get_columns(
        "opportunity_supplier_matches")}
    if "promoted_at" not in match_cols:
        with op.batch_alter_table("opportunity_supplier_matches") as batch:
            batch.add_column(sa.Column("promoted_at", sa.DateTime(), nullable=True))
    inspector = sa.inspect(op.get_bind())
    if "forecast_outcomes" not in inspector.get_table_names():
        op.create_table("forecast_outcomes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("forecast_snapshots.id"),
                      nullable=False, unique=True),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False,
                      index=True),
            sa.Column("target_start", sa.DateTime(), nullable=False),
            sa.Column("target_end", sa.DateTime(), nullable=False),
            sa.Column("forecast_qty", sa.Float(), nullable=False, server_default="0"),
            sa.Column("actual_qty", sa.Float(), nullable=False, server_default="0"),
            sa.Column("absolute_error", sa.Float(), nullable=False, server_default="0"),
            sa.Column("bias", sa.Float(), nullable=True),
            sa.Column("covered", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source_order_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("evaluated_at", sa.DateTime(), nullable=False))
    if "opportunity_attributions" not in inspector.get_table_names():
        op.create_table("opportunity_attributions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
            sa.Column("match_id", sa.Integer(), sa.ForeignKey("opportunity_supplier_matches.id"),
                      nullable=False, unique=True),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False,
                      index=True),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False,
                      index=True),
            sa.Column("attribution_start", sa.DateTime(), nullable=False),
            sa.Column("listing_ids", sa.JSON(), nullable=False),
            sa.Column("order_ids", sa.JSON(), nullable=False),
            sa.Column("published_listing_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("order_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("gmv_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("net_revenue_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("contribution_profit_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("settled_net_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("lineage_method", sa.String(32), nullable=False,
                      server_default="product_after_promotion"),
            sa.Column("refreshed_at", sa.DateTime(), nullable=False))


def downgrade() -> None:
    op.drop_table("opportunity_attributions")
    op.drop_table("forecast_outcomes")
    with op.batch_alter_table("opportunity_supplier_matches") as batch:
        batch.drop_column("promoted_at")
    with op.batch_alter_table("forecast_snapshots") as batch:
        batch.drop_column("target_end")
        batch.drop_column("target_start")
