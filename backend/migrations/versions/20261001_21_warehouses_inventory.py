"""海外仓 / FBA 库存模型：warehouses + inventory_snapshots（D59）。

背景：D58 把物流升级为费率表，但海外仓持有成本仍混在 logistics 路由的
``per_item`` 里——结果把「日仓储费 × 库龄」这种与时间强相关的成本，
按出库件数平摊，长期库存的真实持有成本被严重低估。本迁移新增两张表：

    - warehouses：库位（overseas/fba/3pl）+ 日费率 + 入库/出库操作费 + 超期附加
    - inventory_snapshots：商品 × 库位 × 入库时点的在库事实

只新增结构、不改既有列、不灌业务数据。``costing`` 在调用方给出
``warehouse_id`` 时叠加持有成本，未给出时口径不变（向后兼容）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_21"
down_revision = "20261001_20"
branch_labels = None
depends_on = None

_TABLES = ("warehouses", "inventory_snapshots")


def _facts():
    """迁移前快照：既有表的列定义与行数。硬性断言「未改动既有结构」。"""
    inspector = sa.inspect(op.get_bind())
    # existing 只记 _TABLES 之外的表，否则新建表后 existing 自然变化，断言必挂。
    existing = set(inspector.get_table_names()) - set(_TABLES)
    columns = {}
    counts = {}
    for table in sorted(existing):
        columns[table] = tuple(sorted(
            (col["name"], str(col["type"]), bool(col["nullable"]))
            for col in inspector.get_columns(table)))
        counts[table] = op.get_bind().execute(
            sa.text("SELECT count(*) FROM %s" % table)).scalar_one()
    return existing, columns, counts


def upgrade():
    before = _facts()
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "warehouses" not in existing:
        op.create_table(
            "warehouses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=True),
            sa.Column("code", sa.String(32), nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("warehouse_type", sa.String(16), nullable=True),
            sa.Column("country", sa.String(8), nullable=True),
            sa.Column("daily_fee_per_unit", sa.Float(), nullable=True),
            sa.Column("inbound_fee_per_unit", sa.Float(), nullable=True),
            sa.Column("outbound_fee_per_unit", sa.Float(), nullable=True),
            sa.Column("long_term_threshold_days", sa.Integer(), nullable=True),
            sa.Column("long_term_surcharge_rate", sa.Float(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=True),
            sa.Column("note", sa.String(256), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                     name="fk_warehouses_tenant_id_tenants"),
            sa.UniqueConstraint("tenant_id", "code", name="uq_warehouses_tenant_code"),
        )
        op.create_index("ix_warehouses_tenant_id", "warehouses", ["tenant_id"])

    if "inventory_snapshots" not in existing:
        op.create_table(
            "inventory_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=True),
            sa.Column("warehouse_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("sku", sa.String(64), nullable=True),
            sa.Column("qty_on_hand", sa.Integer(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=True),
            sa.Column("snapshot_at", sa.DateTime(), nullable=True),
            sa.Column("note", sa.String(256), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                     name="fk_inventory_snapshots_tenant_id_tenants"),
            sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        )
        op.create_index("ix_inventory_snapshots_lookup",
                         "inventory_snapshots", ["tenant_id", "warehouse_id", "product_id"])

    after = _facts()
    assert before == after, "迁移改变了既有列、索引或行数（_TABLES 之外的表必须不变）"


def downgrade():
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
