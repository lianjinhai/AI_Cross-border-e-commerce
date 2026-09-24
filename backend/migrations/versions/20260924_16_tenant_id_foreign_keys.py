"""tenant_id 外键约束收敛（DEBT-03）

背景
----
`app/db.py` 在**应用连接级**强制 `PRAGMA foreign_keys=ON`，但 45 张含
`tenant_id` 的业务表**从未声明** `tenants.id` 外键。后果：

1. 应用层一旦写错租户（如历史 superadmin 越权写入 `tenant_id=0`），
   数据库不会拒绝，只能在事后靠审计脚本发现——DEBT-02 的 37 行孤儿数据
   就是这么产生的；
2. `PRAGMA foreign_key_check` 为 0 只说明「已声明的外键没违规」，
   **不能**证明租户引用完整，属于合规假象。

本迁移把缺口一次性补齐（含 `workspace_profiles`，共 45 张）。

设计要点
--------
**A. 平台级哨兵值改 NULL（关键决策，见 docs/DECISIONS.md D27）**

`platform_rule_packs` 是**平台级共享**表：规则包由平台公开文档整理，
对所有租户一致；读取路径 `platform_rules.get_active_rules()` 只按
`platform` 过滤，**刻意不带租户维度**。历史上写入侧用 `tenant_id=0`
作平台级哨兵，而 `tenants` 表没有 id=0——这正是 Revision C 修复
`users.tenant_id=0` 时的同源缺陷。

处置：`platform_rule_packs.tenant_id` 改为 **nullable**，写入侧改 `None`。
与 `users.tenant_id` 的 superadmin 处理保持同一模式（平台身份不归属租户）。
**不做豁免**：豁免会让「45 张表全有外键」变成「44 张 + 1 个例外」，
例外会在后续每一次 schema 审计中被反复误报。

**B. SQLite 必须 batch rebuild**

SQLite 不支持 `ALTER TABLE ... ADD CONSTRAINT`，加外键只能重建表
（`batch_alter_table(recreate="always")`）。重建会连带重建索引与既有外键，
本迁移用「前后快照比对」硬性断言它们没有漂移。

**C. 幂等**

加外键前先探测 `PRAGMA foreign_key_list`；已有 `tenants` 外键的表直接跳过。
本迁移在 `create_all` 已建好表的库（测试库路径）上重复执行必须安全。

**D. 前置条件**

执行前必须：① 已冷备；② `scripts/migration_preflight.py` P0 全通过。
预检的 `check_tenant_zero` 会拦截任何 `tenant_id=0` 的业务行——本迁移
依赖它作为「数据干净」的证明。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260924_16"
down_revision = "20260924_15"
branch_labels = None
depends_on = None


# 45 张待补外键的表。顺序固定（便于审计 diff），与 models.py 声明一一对应。
TENANT_FK_TABLES = [
    "ad_campaigns",
    "ai_decisions",
    "ai_logs",
    "alert_events",
    "alert_rules",
    "category_mappings",
    "compliance_reports",
    "conversations",
    "exchange_rates",
    "forecast_outcomes",
    "forecast_snapshots",
    "knowledge_candidates",
    "knowledge_docs",
    "listing_review_decisions",
    "listings",
    "market_trends",
    "messages",
    "oauth_states",
    "opportunity_attributions",
    "opportunity_supplier_matches",
    "order_fees",
    "order_lines",
    "orders",
    "platform_publish_attempts",
    "platform_rule_packs",
    "platform_settlement_records",
    "pricing_records",
    "product_performances",
    "product_scores",
    "products",
    "purchase_orders",
    "refund_orders",
    "schedules",
    "settlements",
    "shops",
    "supplier_catalog_products",
    "supplier_evidence",
    "supplier_offers",
    "supplier_portal_members",
    "supplier_scores",
    "suppliers",
    "tenant_access_logs",
    "workflow_runs",
    "workflow_steps",
    "workflow_templates",
]

# 需要同时改为 nullable 的平台级表（tenant_id 是「不归属租户」语义，不是哨兵值）
PLATFORM_LEVEL_TABLES = ("platform_rule_packs",)


def fk_name(table: str) -> str:
    return "fk_%s_tenant_id_tenants" % table


def _columns(inspector, table: str) -> dict:
    return {c["name"]: c for c in inspector.get_columns(table)}


def _tenant_fks(inspector, table: str) -> list:
    return [fk for fk in inspector.get_foreign_keys(table)
            if fk.get("referred_table") == "tenants"]


def _snapshot(inspector, table: str) -> dict:
    """表结构快照：列定义 / 索引 / 外键，用于重建前后比对。"""
    cols = []
    for c in inspector.get_columns(table):
        cols.append((c["name"], str(c["type"]).upper(), bool(c["nullable"]),
                     bool(c.get("primary_key"))))
    idx = []
    for i in inspector.get_indexes(table):
        idx.append((i["name"], tuple(i["column_names"]), bool(i.get("unique"))))
    fks = set()
    for fk in inspector.get_foreign_keys(table):
        # 用 set 比对：SQLite 的 PRAGMA foreign_key_list 返回顺序不稳定，
        # 直接比 tuple 列表会把「顺序变化」误报成漂移（实测踩过）。
        fks.add((tuple(fk["constrained_columns"]), fk.get("referred_table"),
                 tuple(fk["referred_columns"])))
    return {"columns": sorted(cols), "indexes": sorted(idx), "fks": fks}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    missing = [t for t in TENANT_FK_TABLES if t not in existing]
    if missing:
        raise RuntimeError(
            "以下表不存在，数据库结构与预期不符：%s" % ", ".join(missing))

    # ---- 阶段 1：平台级表改 nullable（必须在加外键之前）----
    for table in PLATFORM_LEVEL_TABLES:
        col = _columns(inspector, table).get("tenant_id")
        if col is None:
            raise RuntimeError("%s.tenant_id 不存在" % table)
        if not col.get("nullable", False):
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.alter_column("tenant_id", existing_type=sa.Integer(),
                                   nullable=True)
            inspector = sa.inspect(bind)

    # ---- 阶段 2：逐表补 tenants 外键 ----
    added = []
    skipped = []
    for table in TENANT_FK_TABLES:
        if _tenant_fks(inspector, table):
            skipped.append(table)
            continue

        before = _snapshot(inspector, table)
        row_count = bind.execute(
            sa.text('SELECT COUNT(*) FROM "%s"' % table)).scalar()

        with op.batch_alter_table(table, recreate="always") as batch:
            batch.create_foreign_key(fk_name(table), "tenants", ["tenant_id"], ["id"])

        inspector = sa.inspect(bind)
        after = _snapshot(inspector, table)

        if before["columns"] != after["columns"]:
            raise RuntimeError("%s 列定义在重建后漂移" % table)
        if before["indexes"] != after["indexes"]:
            raise RuntimeError("%s 索引在重建后漂移：%s -> %s"
                               % (table, before["indexes"], after["indexes"]))
        # 既有外键必须一条不少（新加的 tenants 外键除外）
        new_fks = after["fks"] - before["fks"]
        if len(new_fks) != 1:
            raise RuntimeError("%s 新增外键数量异常：%s" % (table, new_fks))
        if before["fks"] - after["fks"]:
            raise RuntimeError("%s 既有外键在重建后丢失：%s"
                               % (table, before["fks"] - after["fks"]))
        after_rows = bind.execute(
            sa.text('SELECT COUNT(*) FROM "%s"' % table)).scalar()
        if row_count != after_rows:
            raise RuntimeError("%s 行数变化：%s -> %s"
                               % (table, row_count, after_rows))
        added.append(table)

    _assert_all_tenant_fks(bind)
    _assert_no_zero_tenant(bind)

    print("[20260924_16] 已补外键 %d 张表，跳过（已存在）%d 张表"
          % (len(added), len(skipped)))


def _assert_all_tenant_fks(bind) -> None:
    """硬性断言：45 张表全部有 tenants 外键，且不再有 tenant_id=0 的行。"""
    inspector = sa.inspect(bind)
    missing = [t for t in TENANT_FK_TABLES
               if not _tenant_fks(inspector, t)]
    if missing:
        raise RuntimeError("以下表仍缺 tenants 外键：%s" % ", ".join(missing))

    # 平台级表必须是 nullable
    for table in PLATFORM_LEVEL_TABLES:
        col = _columns(inspector, table).get("tenant_id")
        if not col.get("nullable", False):
            raise RuntimeError("%s.tenant_id 应为 nullable（平台级表）" % table)


def _assert_no_zero_tenant(bind) -> None:
    for table in TENANT_FK_TABLES:
        zero = bind.execute(sa.text(
            'SELECT COUNT(*) FROM "%s" WHERE tenant_id = 0' % table)).scalar()
        if zero:
            raise RuntimeError("%s 存在 %d 行 tenant_id=0" % (table, zero))
    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError("加外键后 PRAGMA foreign_key_check 发现 %d 条违规：%s"
                           % (len(violations), violations[:5]))


def downgrade() -> None:
    """回退：删除 tenants 外键，并把平台级表改回 NOT NULL。

    注意：downgrade **不恢复** tenant_id=0 哨兵值（那是缺陷行为）。
    若 platform_rule_packs 已有 tenant_id=NULL 的行，改回 NOT NULL 会失败——
    这是有意的安全设计，避免静默丢失「平台级」语义。
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for table in TENANT_FK_TABLES:
        if table not in existing:
            continue
        for fk in _tenant_fks(inspector, table):
            name = fk.get("name")
            if not name:
                raise RuntimeError(
                    "%s 的 tenants 外键没有名字，无法安全删除" % table)
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.drop_constraint(name, type_="foreignkey")
            inspector = sa.inspect(bind)

    for table in PLATFORM_LEVEL_TABLES:
        if table not in existing:
            continue
        null_rows = bind.execute(sa.text(
            'SELECT COUNT(*) FROM "%s" WHERE tenant_id IS NULL' % table)).scalar()
        if null_rows:
            raise RuntimeError(
                "%s 有 %d 行 tenant_id 为 NULL（平台级规则包），拒绝改回 NOT NULL；"
                "请先确认这些行的归属" % (table, null_rows))
        col = _columns(inspector, table).get("tenant_id")
        if col and col.get("nullable", False):
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.alter_column("tenant_id", existing_type=sa.Integer(),
                                   nullable=False)
            inspector = sa.inspect(bind)
