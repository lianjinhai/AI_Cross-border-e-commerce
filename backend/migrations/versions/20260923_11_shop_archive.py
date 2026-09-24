"""shop archive (soft delete)

为 shops 增加 archived_at（可空）：DELETE /api/shops/{id} 由物理删除改为归档，
避免外键约束失败（orders / purchase_orders / platform_publish_attempts /
platform_settlement_records / oauth_states 均引用 shops.id），同时保留订单与
采购单的店铺归属，维持财务对账与审计留痕。

设计依据：docs/DECISIONS.md（店铺删除语义）；实现见
app/routers/shops.py::delete_shop 与 app/services/shop_scope.py。

幂等：加列前先检查列是否已存在。不修改、不删除任何既有数据（NULL = 正常可用）。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260923_11"
down_revision = "20260923_10"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    if "shops" not in set(sa.inspect(op.get_bind()).get_table_names()):
        print("[Revision E] shops 表不存在，跳过")
        return
    if "archived_at" in _columns("shops"):
        print("[Revision E] shops.archived_at 已存在，跳过")
        return
    op.add_column("shops", sa.Column("archived_at", sa.DateTime(), nullable=True))
    print("[Revision E] shops.archived_at 已添加")


def downgrade() -> None:
    if "shops" in set(sa.inspect(op.get_bind()).get_table_names()) \
            and "archived_at" in _columns("shops"):
        op.drop_column("shops", "archived_at")
