"""durable publish tasks and dropship idempotency"""
from alembic import op
import sqlalchemy as sa

revision = "20260922_06"
down_revision = "20260922_05"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {x["name"] for x in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    publish = _columns("platform_publish_attempts")
    with op.batch_alter_table("platform_publish_attempts") as batch:
        if "requested_by" not in publish:
            batch.add_column(sa.Column("requested_by", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_publish_requested_by", "users", ["requested_by"], ["id"])
        if "request_payload" not in publish:
            batch.add_column(sa.Column("request_payload", sa.JSON(), nullable=False, server_default="{}"))
        if "started_at" not in publish:
            batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        if "finished_at" not in publish:
            batch.add_column(sa.Column("finished_at", sa.DateTime(), nullable=True))

    purchase = _columns("purchase_orders")
    with op.batch_alter_table("purchase_orders") as batch:
        if "sales_order_id" not in purchase:
            batch.add_column(sa.Column("sales_order_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_purchase_sales_order", "orders", ["sales_order_id"], ["id"])
            batch.create_index("ix_purchase_orders_sales_order_id", ["sales_order_id"])
        if "source_shop_id" not in purchase:
            batch.add_column(sa.Column("source_shop_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_purchase_source_shop", "shops", ["source_shop_id"], ["id"])
            batch.create_index("ix_purchase_orders_source_shop_id", ["source_shop_id"])
        if "idempotency_key" not in purchase:
            batch.add_column(sa.Column("idempotency_key", sa.String(128), nullable=True))
            batch.create_unique_constraint("uq_purchase_idempotency_key", ["idempotency_key"])
        if "platform_trade_no" not in purchase:
            batch.add_column(sa.Column("platform_trade_no", sa.String(128), nullable=False, server_default=""))
        if "purchase_type" not in purchase:
            batch.add_column(sa.Column("purchase_type", sa.String(24), nullable=False, server_default="stock"))


def downgrade() -> None:
    with op.batch_alter_table("purchase_orders") as batch:
        batch.drop_column("purchase_type")
        batch.drop_column("platform_trade_no")
        batch.drop_constraint("uq_purchase_idempotency_key", type_="unique")
        batch.drop_column("idempotency_key")
        batch.drop_index("ix_purchase_orders_source_shop_id")
        batch.drop_column("source_shop_id")
        batch.drop_index("ix_purchase_orders_sales_order_id")
        batch.drop_column("sales_order_id")
    with op.batch_alter_table("platform_publish_attempts") as batch:
        batch.drop_column("finished_at")
        batch.drop_column("started_at")
        batch.drop_column("request_payload")
        batch.drop_column("requested_by")
