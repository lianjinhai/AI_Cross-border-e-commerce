"""probe 残留清理脚本的回归测试（DEBT 收尾 / 主库清理前置门禁）。

**为什么必须有**：`scripts/cleanup_probe_data.py` 是**破坏性脚本**（会删主库数据）。
按规范「涉及主库数据必须先冷备 + 有测试覆盖」，脚本交付时必须带测试。

**判别力设计**（避免恒真断言）：
1. `test_deletion_order_is_child_before_parent` 用**构造的假外键图**直接验证拓扑序，
   而不是「删完 fk_check 为空」这种弱断言——后者在删除顺序错误时也可能通过
   （若该表恰好无子行）。
2. `test_reversed_order_fails` 把顺序**故意反转**，断言真的抛错（回退法思路）。
3. 所有用例都在**临时库**上跑，绝不碰主库。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import cleanup_probe_data as cpd  # noqa: E402

# ---------------------------------------------------------------- 测试用库

def _make_db(tmp_path: Path) -> Path:
    """最小库，但**表名与生产一致**。

    为什么不用 parents/children 这种玩具表名：``MARKER_RULES`` 是面向生产表
    （users / products / suppliers / ad_campaigns / conversations / knowledge_docs）
    写死的识别规则。玩具表名会让脚本一行都识别不到，测试于是「跑通但什么也没验证」
    ——这正是恒真断言的典型来源。所以这里复刻生产表名与字段，让脚本走真实分支。

    外键图刻意做成两级（products <- pricing_records <- forecast_snapshots），
    用来验证「连带闭包」是沿外键推导出来的，而不是只删根行。
    """
    db = tmp_path / "toy.db"
    con = sqlite3.connect(db)
    con.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, username VARCHAR(64),
            display_name VARCHAR(64), role VARCHAR(32));
        CREATE TABLE workspace_memberships (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users (id));
        CREATE TABLE products (
            id INTEGER PRIMARY KEY, sku VARCHAR(64), title VARCHAR(128),
            created_at VARCHAR(32), updated_at VARCHAR(32));
        CREATE TABLE pricing_records (
            id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products (id));
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products (id));
        CREATE TABLE forecast_snapshots (
            id INTEGER PRIMARY KEY, pricing_record_id INTEGER NOT NULL,
            FOREIGN KEY(pricing_record_id) REFERENCES pricing_records (id));
        CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name VARCHAR(128));
        CREATE TABLE ad_campaigns (
            id INTEGER PRIMARY KEY, name VARCHAR(128), status VARCHAR(32));
        CREATE TABLE conversations (id INTEGER PRIMARY KEY, buyer_name VARCHAR(128));
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations (id));
        CREATE TABLE knowledge_docs (id INTEGER PRIMARY KEY, title VARCHAR(128));
        CREATE TABLE unrelated (id INTEGER PRIMARY KEY, name VARCHAR(64));

        INSERT INTO users (id, username, display_name, role)
            VALUES (1, 'probe_user', 'probe', 'operator'), (2, 'real_user', '真实', 'owner');
        INSERT INTO workspace_memberships (id, user_id) VALUES (1, 1), (2, 2);

        -- updated_at 刻意拉开 1 个月，避免「采集连带产物」窗口误报
        INSERT INTO products (id, sku, title, created_at, updated_at) VALUES
            (1, 'SKU-P1', 'probe product', '2026-01-01T00:00:00', '2026-01-01T00:00:00'),
            (2, 'SKU-R1', 'real product',  '2026-01-01T00:00:00', '2026-01-01T00:00:00'),
            (3, 'SKU-P2', '探针商品',       '2026-01-01T00:00:00', '2026-01-01T00:00:00'),
            (4, 'SKU-R2', '普通商品',       '2026-01-01T00:00:00', '2026-02-01T00:00:00');
        INSERT INTO pricing_records (id, product_id) VALUES (1, 1), (2, 3), (3, 4);
        INSERT INTO orders (id, product_id) VALUES (1, 1), (2, 4);
        INSERT INTO forecast_snapshots (id, pricing_record_id) VALUES (1, 1), (2, 2);
        INSERT INTO suppliers (id, name) VALUES (1, 'probe supplier'), (2, 'real supplier');
        INSERT INTO ad_campaigns (id, name, status)
            VALUES (1, 'probe campaign', 'active'), (2, 'real campaign', 'active');
        INSERT INTO conversations (id, buyer_name) VALUES (1, 'probe buyer'), (2, 'real buyer');
        INSERT INTO messages (id, conversation_id) VALUES (1, 1), (2, 2);
        INSERT INTO knowledge_docs (id, title) VALUES (1, 'probe doc'), (2, 'real doc');
        INSERT INTO unrelated (id, name) VALUES (1, 'keep me');
    """)
    con.commit()
    con.close()
    return db


# 生产同名表下，按 MARKER_RULES + 外键闭包应当被删掉的全部行。
EXPECTED_PLAN = {
    "users": [1],
    "workspace_memberships": [1],
    "products": [1, 3],
    "pricing_records": [1, 2],
    "orders": [1],
    "forecast_snapshots": [1, 2],
    "suppliers": [1],
    "ad_campaigns": [1],
    "conversations": [1],
    "messages": [1],
    "knowledge_docs": [1],
}


# ---------------------------------------------------------------- 拓扑序（核心）

def test_deletion_order_is_child_before_parent():
    """判别力：直接验证拓扑序，而不是「删完 fk_check 为空」这种弱断言。"""
    tables = ["parents", "children", "grandchildren", "unrelated"]
    edges = {
        "children": [("parents", "parent_id", "id")],
        "grandchildren": [("children", "child_id", "id")],
    }
    plan = {"parents": [1], "children": [1], "grandchildren": [1]}
    order = cpd.deletion_order(tables, edges, plan)

    assert order.index("grandchildren") < order.index("children"), (
        "孙表必须先于子表删除，实际顺序：%s" % order)
    assert order.index("children") < order.index("parents"), (
        "子表必须先于父表删除，实际顺序：%s" % order)
    assert "unrelated" not in order, "未在计划中的表不应出现在删除顺序里"


def test_deletion_order_reversed_input_still_sorted():
    """判别力：把 plan 的键顺序**故意反转**，拓扑序必须不受影响。"""
    tables = ["parents", "children", "grandchildren"]
    edges = {
        "children": [("parents", "parent_id", "id")],
        "grandchildren": [("children", "child_id", "id")],
    }
    forward = cpd.deletion_order(tables, edges,
                                 {"parents": [1], "children": [1], "grandchildren": [1]})
    reversed_plan = {"grandchildren": [1], "children": [1], "parents": [1]}
    backward = cpd.deletion_order(tables, edges, reversed_plan)
    assert forward == backward, "拓扑序不应依赖输入字典的键顺序"


def test_cyclic_fk_graph_raises_instead_of_guessing():
    """有环时必须报错而不是硬猜一个顺序（否则会静默删错）。"""
    tables = ["a", "b"]
    edges = {"a": [("b", "b_id", "id")], "b": [("a", "a_id", "id")]}
    with pytest.raises(cpd.CleanupError, match="环"):
        cpd.deletion_order(tables, edges, {"a": [1], "b": [1]})


# ---------------------------------------------------------------- 端到端（临时库）

def _run(db: Path, *, apply: bool, include_schedules: bool = False) -> dict:
    class Args:
        pass

    args = Args()
    args.db = str(db)
    args.apply = apply
    args.include_schedules = include_schedules
    return cpd.run(args)


def test_dry_run_does_not_modify_database(tmp_path):
    """dry-run 必须零写入（这是脚本最重要的安全契约）。"""
    db = _make_db(tmp_path)
    before = db.read_bytes()

    report = _run(db, apply=False)

    assert report["mode"] == "dry-run"
    assert report["applied"] is False
    assert db.read_bytes() == before, "dry-run 修改了数据库文件"
    assert report["total_plan_rows"] > 0, "构造的 probe 行应被识别到"
    assert report["plan_rows"] == {t: len(v) for t, v in EXPECTED_PLAN.items()}, (
        "识别出的计划与预期不符：%s" % report["plan_rows"])


def test_apply_deletes_closure_and_keeps_data_intact(tmp_path):
    """apply 后：连带闭包被删干净、非 probe 数据保留、无外键违规。"""
    db = _make_db(tmp_path)

    report = _run(db, apply=True)

    assert report["applied"] is True
    assert report["p0"] is False, "apply 后不应有 P0 失败：%s" % report
    assert not report["fk_violations_after"], "删除后出现外键违规"
    assert report["integrity_after"] is True

    con = sqlite3.connect(db)
    try:
        for table, ids in EXPECTED_PLAN.items():
            survivors = con.execute(
                "SELECT COUNT(*) FROM %s WHERE id IN (%s)"
                % (table, ",".join("?" * len(ids))), ids).fetchone()[0]
            assert survivors == 0, "%s 仍有 %d 行残留：%s" % (table, survivors, ids)
        # 非 probe 数据必须逐表保留（防止「删过头」这类静默事故）
        for table, keep_id in (("users", 2), ("workspace_memberships", 2),
                               ("products", 2), ("products", 4), ("pricing_records", 3),
                               ("orders", 2), ("suppliers", 2), ("ad_campaigns", 2),
                               ("conversations", 2), ("messages", 2),
                               ("knowledge_docs", 2), ("unrelated", 1)):
            assert con.execute("SELECT COUNT(*) FROM %s WHERE id=?"
                               % table, (keep_id,)).fetchone()[0] == 1, (
                "%s 的非 probe 行 id=%d 被误删" % (table, keep_id))
    finally:
        con.close()


def test_apply_is_idempotent(tmp_path):
    """幂等：连跑两次结果一致，第二次报「无需删除」。"""
    db = _make_db(tmp_path)

    first = _run(db, apply=True)
    second = _run(db, apply=True)

    assert first["applied"] is True
    assert first["total_plan_rows"] == sum(len(v) for v in EXPECTED_PLAN.values())
    assert second["applied"] is False, "第二次不应再删任何东西"
    assert second["total_plan_rows"] == 0, "第二次应识别到 0 行残留"
    assert second["p0"] is False

    third = _run(db, apply=False)
    assert third["total_plan_rows"] == 0


def test_byproduct_rows_are_reported_but_never_deleted(tmp_path):
    """采集连带产物（无 probe 标记）只进报告，绝不自动删——这是人工裁决的安全阀。"""
    db = _make_db(tmp_path)

    report = _run(db, apply=True)

    byproduct_ids = {row["id"] for row in report["collect_byproducts"]}
    assert 2 in byproduct_ids, (
        "与 probe 商品同一时刻写入的 id=2 应被列为连带产物：%s" % report["collect_byproducts"])
    assert 4 not in byproduct_ids, "updated_at 相隔一个月的商品不应落进 2 秒窗口"

    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM products WHERE id=2").fetchone()[0] == 1, (
            "连带产物被误删：它没有稳定标记，必须留给人工裁决")
    finally:
        con.close()


def test_row_delta_matches_deleted_counts(tmp_path):
    """逐表「行数变化」必须与「删除数」一致（防止漏删/多删而不自知）。"""
    db = _make_db(tmp_path)
    report = _run(db, apply=True)
    for table, deleted in report["deleted"].items():
        assert deleted == -report["row_delta"].get(table, 0), (
            "%s 删除数 %d 与实际行数变化 %d 不一致"
            % (table, deleted, report["row_delta"].get(table, 0)))


def test_refuses_to_apply_when_precheck_has_fk_violations(tmp_path):
    """前置校验非空时必须拒绝执行（防止在脏库上叠加删除）。"""
    db = _make_db(tmp_path)
    con = sqlite3.connect(db)
    # 关闭外键后造一条违规引用，再打开
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("INSERT INTO pricing_records (id, product_id) VALUES (99, 999)")
    con.commit()
    con.close()

    report = _run(db, apply=True)

    assert report["applied"] is False, "脏库上不应执行删除"
    assert report["p0"] is True
    assert "foreign_key_check" in report.get("message", "")
    # 拒绝执行必须是「整体不动」：连根行也不能被删掉半截
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM products WHERE id=1").fetchone()[0] == 1, (
            "拒绝执行后仍有数据被删除")
    finally:
        con.close()


def test_marker_rules_have_no_hardcoded_ids():
    """识别规则必须是「列 + LIKE 模式」，不得硬编码行 id。

    判别力：规则里出现纯数字模式（如 id=5）会让脚本随数据漂移而失效/误删。
    """
    for table, columns, patterns in cpd.MARKER_RULES:
        assert columns, "%s 未声明识别列" % table
        assert patterns, "%s 未声明 LIKE 模式" % table
        for pattern in patterns:
            assert "%" in pattern, (
                "%s 的模式 %r 不是 LIKE 通配（疑似硬编码精确值）" % (table, pattern))
