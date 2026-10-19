"""D63 / LinkWhale V9.1：选中报价持久化 + 报价诚实性扩展（仅加列，无新表）。

修订 20261019_30（down_revision = 20261018_29）。
- supplier_offers.valid_until / source_kind / verification_status
- products.selected_offer_id（FK -> supplier_offers.id，命名约束
  fk_products_selected_offer_id_supplier_offers）

幂等：加列/加约束前先探测已存在结构，避免与 ``create_all``（按模型建表）
已建出的列/约束重复执行而报错。downgrade 反向删除约束与列。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261019_30"
down_revision = "20261018_29"
branch_labels = None
depends_on = None

FK_NAME = "fk_products_selected_offer_id_supplier_offers"


def upgrade():
    bind = op.get_bind()

    offer_cols = {c["name"] for c in sa.inspect(bind).get_columns("supplier_offers")}
    with op.batch_alter_table("supplier_offers") as batch:
        if "valid_until" not in offer_cols:
            batch.add_column(sa.Column("valid_until", sa.DateTime(), nullable=True))
        if "source_kind" not in offer_cols:
            batch.add_column(sa.Column("source_kind", sa.String(32), nullable=False,
                                       server_default="manual"))
        if "verification_status" not in offer_cols:
            batch.add_column(sa.Column("verification_status", sa.String(24), nullable=False,
                                       server_default="unverified"))

    product_cols = {c["name"] for c in sa.inspect(bind).get_columns("products")}
    if "selected_offer_id" not in product_cols:
        product_fks = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("products")}
        with op.batch_alter_table("products") as batch:
            batch.add_column(sa.Column("selected_offer_id", sa.Integer(), nullable=True))
            if FK_NAME not in product_fks:
                batch.create_foreign_key(
                    FK_NAME, "supplier_offers", ["selected_offer_id"], ["id"])


def downgrade():
    with op.batch_alter_table("products") as batch:
        # SQLite batch 重建表：先删约束再删列（约束存在才删，避免误库报错）。
        try:
            batch.drop_constraint(FK_NAME, type_="foreignkey")
        except Exception:
            pass
        batch.drop_column("selected_offer_id")
    with op.batch_alter_table("supplier_offers") as batch:
        batch.drop_column("verification_status")
        batch.drop_column("source_kind")
        batch.drop_column("valid_until")
