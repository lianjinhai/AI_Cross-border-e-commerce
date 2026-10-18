"""DEBT-03：tenant_id 外键约束的回归测试（含判别力验证）。

为什么需要本文件
----------------
`app/db.py` 在连接级强制 `PRAGMA foreign_keys=ON`，但 45 张含 `tenant_id`
的业务表**从未声明** `tenants.id` 外键（迁移 20260924_16 才补齐）。后果是
应用层写错租户时数据库不拒绝——DEBT-02 的 37 行孤儿数据即由此产生。

本文件锁死三条契约：
1. **结构**：所有含 `tenant_id` 的表都必须声明 `tenants.id` 外键；
2. **行为**：写不存在的 tenant_id 必须被拒绝（判别力验证）；
3. **语义**：平台级表 `platform_rule_packs.tenant_id` 允许 NULL，
   且**禁止**写 0 哨兵值（tenants 表没有 id=0）。

判别力说明：断言 2 必须配合「对照组」才有意义——只断言「写入失败」时，
任何无关的 NOT NULL 约束都会让用例通过（假绿）。因此这里显式先证明
合法 tenant_id 能写入，再证明非法值被拒。

所有用例都依赖 ``client`` 夹具：它负责把测试库推进到 alembic head
（迁移链含 20260924_16），否则被测的外键根本不存在。

**为什么还要单独测「迁移清单 vs 模型层」**（实测踩过的盲区）：
测试库的建库路径是 ``create_all``（按**模型**建表）+ 全量迁移链。若迁移
清单漏掉某张表，``create_all`` 已经按模型把外键建好了，于是「库里有外键」
这类断言**照样通过**——迁移的遗漏被完全掩盖。实测：从迁移清单里删掉
``products`` 后，其余 5 个用例全绿。因此必须直接比对两份清单本身。
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import PlatformRulePack, Product, Tenant


def _tenant_tables(engine) -> set:
    """所有含 tenant_id 列的表名（从真实数据库结构读，不硬编码清单）。"""
    from sqlalchemy import inspect

    inspector = inspect(engine)
    return {t for t in inspector.get_table_names()
            if "tenant_id" in {c["name"] for c in inspector.get_columns(t)}}


def test_every_tenant_table_declares_foreign_key(client):
    """结构契约：含 tenant_id 的表必须全部声明 tenants 外键。"""
    from sqlalchemy import inspect

    from app.db import engine

    inspector = inspect(engine)
    tables = _tenant_tables(engine)
    assert tables, "未找到任何含 tenant_id 的表，测试基线不成立"

    missing = []
    for table in sorted(tables):
        if not any(fk["referred_table"] == "tenants"
                   for fk in inspector.get_foreign_keys(table)):
            missing.append(table)
    assert not missing, (
        "以下表含 tenant_id 但没有 tenants.id 外键，租户引用不受数据库保护：%s"
        % ", ".join(missing))


def test_model_metadata_declares_foreign_key(client):
    """模型层契约：create_all 建的新库必须与迁移后的库结构一致。"""
    from app.db import Base

    missing = []
    for name, table in Base.metadata.tables.items():
        if "tenant_id" not in table.columns:
            continue
        targets = {fk.target_fullname for fk in table.columns["tenant_id"].foreign_keys}
        if "tenants.id" not in targets:
            missing.append(name)
    assert not missing, (
        "以下模型的 tenant_id 未声明 ForeignKey(\"tenants.id\")，"
        "create_all 建出的新库会与迁移后的库结构漂移：%s" % ", ".join(sorted(missing)))


def test_migration_table_list_matches_model_metadata(client):
    """迁移清单契约：迁移覆盖的表集合必须与模型层完全一致。

    判别力：``create_all`` 会掩盖迁移清单的遗漏，所以这里**不查库**，
    而是直接比对迁移模块的 TENANT_FK_TABLES 与模型元数据。
    """
    from importlib import import_module

    from app.db import Base

    migration = import_module(
        "migrations.versions.20260924_16_tenant_id_foreign_keys")
    listed = set(migration.TENANT_FK_TABLES)

    expected = set()
    for name, table in Base.metadata.tables.items():
        if "tenant_id" not in table.columns:
            continue
        targets = {fk.target_fullname for fk in table.columns["tenant_id"].foreign_keys}
        if "tenants.id" in targets:
            expected.add(name)
    # users / tenant_settings / workspace_profiles 的外键先于本迁移存在，
    # 不在本迁移清单内（其中 workspace_profiles 不注册在模型元数据上）。
    # ai_actions 由后续 Revision 18 新建并在该迁移中声明外键；禁止回改已执行的
    # Revision 16 清单。它的外键由 test_ai_action_migration 独立核对。
    # D58 的 5 张跨境成本表由后续 Revision 20 新建并在该迁移中声明外键，同理不回改
    # Revision 16 清单；其 tenant_id → tenants.id 由本文件首条元数据级契约
    # （test_all_tenant_id_columns_have_foreign_key）与 test_cross_border 共同核对。
    # D59 的 2 张海外仓库存表由后续 Revision 21 新建，同理不回改 Revision 16 清单；
    # warehouses 的 tenant_id → tenants.id 与 inventory_snapshots 的
    # tenant_id → tenants.id 由本文件首条元数据级契约与 test_warehouses_inventory 核对。
    # WorkflowEvent 由 Revision 26 新建；独立历史库迁移测试核对真实 FK。
    expected -= {"users", "tenant_settings", "workspace_profiles", "ai_actions", "workflow_events", "product_assets",
                 "duty_rates", "logistics_routes", "platform_fee_schedules",
                 "destination_compliance_rules", "product_compliance_evidence",
                 "warehouses", "inventory_snapshots",
                 # business_profiles 由 Revision 29（D63 经营画像）新建，同理不回改
                 # Revision 16 清单；其 tenant_id → tenants.id 由元数据级契约
                 # test_all_tenant_id_columns_have_foreign_key 与 test_business_profile 共同核对。
                 "business_profiles"}

    assert listed == expected, (
        "迁移清单与模型层不一致——漏补：%s；多补：%s"
        % (sorted(expected - listed), sorted(listed - expected)))
    assert len(listed) == 45, "迁移清单应覆盖 45 张表，实际 %d" % len(listed)


def test_migration_listed_tables_all_exist(client):
    """迁移清单里的每张表都必须真实存在（防止清单写错表名）。"""
    from importlib import import_module

    from sqlalchemy import inspect

    from app.db import engine

    migration = import_module(
        "migrations.versions.20260924_16_tenant_id_foreign_keys")
    existing = set(inspect(engine).get_table_names())
    missing = sorted(set(migration.TENANT_FK_TABLES) - existing)
    assert not missing, "迁移清单引用了不存在的表：%s" % ", ".join(missing)


def test_unknown_tenant_id_is_rejected(client):
    """行为契约：写不存在的 tenant_id 必须被数据库拒绝。

    判别力：先确认合法 tenant_id 能写入，排除「因为别的约束才失败」的假绿。
    """
    db = SessionLocal()
    try:
        tenant_id = db.query(Tenant.id).order_by(Tenant.id).first()
        if tenant_id is None:
            pytest.skip("库中无 tenant 行，无法验证判别力")
        tenant_id = tenant_id[0]

        # 对照组：合法租户必须能写入（否则下面的断言毫无判别力）
        ok = Product(tenant_id=tenant_id, sku="FK-OK", title="t", category="c")
        db.add(ok)
        db.commit()
        db.delete(ok)
        db.commit()

        # 实验组：不存在的租户必须被拒绝
        db.add(Product(tenant_id=999999, sku="FK-BAD", title="t", category="c"))
        with pytest.raises(IntegrityError) as exc:
            db.commit()
        assert "FOREIGN KEY" in str(exc.value.orig).upper(), (
            "预期外键约束失败，实际：%s" % exc.value.orig)
    finally:
        db.rollback()
        db.close()


def test_tenant_zero_sentinel_is_rejected(client):
    """行为契约：tenant_id=0 必须被拒绝（tenants 表没有 id=0）。

    这是 DEBT-02 的根因——历史代码用 0 作「平台级」哨兵值写入业务表。
    """
    db = SessionLocal()
    try:
        db.add(Product(tenant_id=0, sku="FK-ZERO", title="t", category="c"))
        with pytest.raises(IntegrityError) as exc:
            db.commit()
        assert "FOREIGN KEY" in str(exc.value.orig).upper(), (
            "预期外键约束失败，实际：%s" % exc.value.orig)
    finally:
        db.rollback()
        db.close()


def test_platform_level_table_accepts_null_but_rejects_zero(client):
    """语义契约：平台级表的 tenant_id 允许 NULL，但 0 哨兵值仍被拒绝。"""
    db = SessionLocal()
    try:
        # 平台级共享规则包：tenant_id 为 NULL 是**正确**写法
        row = PlatformRulePack(tenant_id=None, platform="fk-test-platform",
                               version="2026-09-24", rules={})
        db.add(row)
        db.commit()
        db.delete(row)
        db.commit()

        # 0 哨兵值仍必须被拒绝（否则 D27 的缺陷会回归）
        db.add(PlatformRulePack(tenant_id=0, platform="fk-test-zero",
                                version="2026-09-24", rules={}))
        with pytest.raises(IntegrityError) as exc:
            db.commit()
        assert "FOREIGN KEY" in str(exc.value.orig).upper(), (
            "预期外键约束失败，实际：%s" % exc.value.orig)
    finally:
        db.rollback()
        db.close()
