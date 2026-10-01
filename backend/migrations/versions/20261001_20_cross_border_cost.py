"""跨境到岸成本：关税税率、物流计费、平台费率、目的国合规与证据（D58）。

背景：2026 年低值包裹免税全球退坡，关税/进口税/目的国准入成为跨境直邮第一
成本项与第一封店原因，而此前全库无任何关务/物流/目的国合规建模。本迁移只
**新增**结构（5 张新表 + products.hs_code 列），不修改任何既有列，也不灌业务
数据——参考税率/费率/合规要求以代码内 DEFAULT_* 兜底（见 services/duty.py 等），
租户或平台服务商可后续写入覆盖，避免把"参考数据"绑死在迁移里。

幂等：建表前探测 `inspector.get_table_names()`，加列前探测列集合；在
`create_all` 已建好表的测试库上重复执行不会报错，也不会丢数据。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_20"
down_revision = "20261001_19"
branch_labels = None
depends_on = None

# 本迁移引入的表（表名 -> 建表语句所需的列/约束）
_TABLES = ("duty_rates", "logistics_routes", "platform_fee_schedules",
           "destination_compliance_rules", "product_compliance_evidence")


def _facts():
    """迁移前快照：既有表的列定义与行数。用于硬性断言"未改动既有结构"。"""
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    columns = {}
    counts = {}
    for table in sorted(existing - set(_TABLES)):
        columns[table] = tuple(sorted(
            (col["name"], str(col["type"]), bool(col["nullable"]))
            for col in inspector.get_columns(table)))
        counts[table] = op.get_bind().execute(
            sa.text("SELECT count(*) FROM %s" % table)).scalar_one()
    return existing, columns, counts


def _has_table(inspector, table: str) -> bool:
    return table in set(inspector.get_table_names())


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, table):
        # 目标表不存在（最小化隔离测试库，或前期结构尚未建立）：无可补列，跳过。
        # 主库与完整 create_all 库一定存在 products，此分支只服务于幂等的窄库场景。
        return
    if column.name in {col["name"] for col in inspector.get_columns(table)}:
        return
    with op.batch_alter_table(table) as batch:
        batch.add_column(column)


def _tenant_fk(name: str) -> sa.ForeignKey:
    return sa.ForeignKey("tenants.id", name=name)


def _create_duty_rates() -> None:
    op.create_table(
        "duty_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), _tenant_fk("fk_duty_rates_tenant_id_tenants"),
                  nullable=True),
        sa.Column("destination_country", sa.String(8), nullable=False),
        sa.Column("hs_prefix", sa.String(12), nullable=False, server_default=""),
        sa.Column("rate_type", sa.String(16), nullable=False, server_default="ad_valorem"),
        sa.Column("rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("de_minimis", sa.Float(), nullable=True),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("source_url", sa.String(512), nullable=False, server_default=""),
        sa.Column("note", sa.String(256), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_duty_rates_tenant_id", "duty_rates", ["tenant_id"])
    op.create_index("ix_duty_rates_destination_country", "duty_rates", ["destination_country"])
    op.create_index("ix_duty_rates_lookup", "duty_rates", ["destination_country", "hs_prefix"])


def _create_logistics_routes() -> None:
    op.create_table(
        "logistics_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  _tenant_fk("fk_logistics_routes_tenant_id_tenants"), nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("channel_type", sa.String(24), nullable=False, server_default="direct_mail"),
        sa.Column("destination_country", sa.String(8), nullable=False, server_default=""),
        sa.Column("billing_method", sa.String(16), nullable=False, server_default="per_kg"),
        sa.Column("first_weight_kg", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("first_weight_fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("additional_per_kg", sa.Float(), nullable=False, server_default="0"),
        sa.Column("per_cbm", sa.Float(), nullable=False, server_default="0"),
        sa.Column("per_item", sa.Float(), nullable=False, server_default="0"),
        sa.Column("volumetric_divisor", sa.Integer(), nullable=False, server_default="6000"),
        sa.Column("min_charge", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fuel_surcharge_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("peak_surcharge_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(256), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_logistics_routes_tenant_id", "logistics_routes", ["tenant_id"])
    op.create_index("ix_logistics_routes_lookup", "logistics_routes",
                    ["destination_country", "channel_type"])


def _create_platform_fee_schedules() -> None:
    op.create_table(
        "platform_fee_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  _tenant_fk("fk_platform_fee_schedules_tenant_id_tenants"), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("category", sa.String(64), nullable=False, server_default=""),
        sa.Column("site", sa.String(16), nullable=False, server_default=""),
        sa.Column("commission_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("transaction_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("service_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(256), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_platform_fee_schedules_tenant_id", "platform_fee_schedules", ["tenant_id"])
    op.create_index("ix_platform_fee_schedules_platform", "platform_fee_schedules", ["platform"])
    op.create_index("ix_platform_fee_lookup", "platform_fee_schedules",
                    ["platform", "category", "site"])


def _create_destination_compliance_rules() -> None:
    op.create_table(
        "destination_compliance_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  _tenant_fk("fk_destination_compliance_rules_tenant_id_tenants"), nullable=True),
        sa.Column("destination_country", sa.String(8), nullable=False),
        sa.Column("category", sa.String(64), nullable=False, server_default=""),
        sa.Column("requirement", sa.String(32), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("source_url", sa.String(512), nullable=False, server_default=""),
        sa.Column("note", sa.String(256), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_destination_compliance_rules_tenant_id",
                    "destination_compliance_rules", ["tenant_id"])
    op.create_index("ix_destination_compliance_rules_destination_country",
                    "destination_compliance_rules", ["destination_country"])
    op.create_index("ix_destination_compliance_lookup", "destination_compliance_rules",
                    ["destination_country", "category"])


def _create_product_compliance_evidence() -> None:
    op.create_table(
        "product_compliance_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  _tenant_fk("fk_product_compliance_evidence_tenant_id_tenants"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("destination_country", sa.String(8), nullable=False, server_default=""),
        sa.Column("requirement", sa.String(32), nullable=False),
        sa.Column("evidence_ref", sa.String(512), nullable=False, server_default=""),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(256), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "product_id", "destination_country", "requirement",
                            name="uq_product_compliance_evidence"),
    )
    op.create_index("ix_product_compliance_evidence_tenant_id",
                    "product_compliance_evidence", ["tenant_id"])
    op.create_index("ix_product_compliance_evidence_product_id",
                    "product_compliance_evidence", ["product_id"])


_BUILDERS = {
    "duty_rates": _create_duty_rates,
    "logistics_routes": _create_logistics_routes,
    "platform_fee_schedules": _create_platform_fee_schedules,
    "destination_compliance_rules": _create_destination_compliance_rules,
    "product_compliance_evidence": _create_product_compliance_evidence,
}


def _assert_only_additive(before: tuple, after: tuple) -> None:
    """硬性断言：本迁移只做加法。

    仅允许 products 新增 hs_code 一列；products 之外的既有表列定义必须逐字不变，
    且所有既有表行数不得变化（本迁移不灌数据、不改既有列）。
    """
    before_cols, after_cols = dict(before[1]), dict(after[1])
    before_prod = {col[0] for col in before_cols.pop("products", ())}
    after_prod = {col[0] for col in after_cols.pop("products", ())}
    changed = sorted(set(before_cols) ^ set(after_cols)) or [
        table for table in before_cols
        if before_cols[table] != after_cols.get(table)]
    assert before_cols == after_cols, (
        "跨境成本迁移改动了 products 之外的既有表结构：%s" % changed[:5])
    assert after_prod - before_prod <= {"hs_code"}, (
        "products 仅允许新增 hs_code，实际新增：%s" % sorted(after_prod - before_prod))
    assert before_prod - after_prod == set(), (
        "跨境成本迁移不得删除 products 既有列：%s" % sorted(before_prod - after_prod))
    mismatched = {table: (before[2].get(table), after[2].get(table))
                  for table in before[2] if before[2].get(table) != after[2].get(table)}
    assert not mismatched, "跨境成本迁移改动了既有表数据行数：%s" % mismatched


def upgrade():
    before = _facts()
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in _TABLES:
        if table not in existing:
            _BUILDERS[table]()
    _add_column_if_missing("products", sa.Column("hs_code", sa.String(16),
                                                 nullable=False, server_default=""))
    # 硬性断言：本迁移只允许新增结构（5 张新表 + products.hs_code），不改既有列与数据。
    _assert_only_additive(before, _facts())


def downgrade():
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
    # products 可能不存在（最小化隔离测试库）；不存在则无 hs_code 可回滚。
    if _has_table(sa.inspect(op.get_bind()), "products"):
        columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("products")}
        if "hs_code" in columns:
            with op.batch_alter_table("products") as batch:
                batch.drop_column("hs_code")
    remaining = set(sa.inspect(op.get_bind()).get_table_names())
    assert not (remaining & set(_TABLES)), "跨境成本回滚未清理干净"
