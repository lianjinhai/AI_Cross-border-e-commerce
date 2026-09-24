"""probe 残留数据清理器：默认只读演练，``--apply`` 才真正删除。

为什么需要本脚本
    R-06 只清理了 5 个 ``probe tenant`` 及其 25 行关联数据；``users`` /
    ``products`` / ``suppliers`` / ``ad_campaigns`` / ``conversations`` /
    ``knowledge_docs`` 中仍留有 probe 命名的静态脏数据。``app/db.py`` 在连接级
    强制 ``PRAGMA foreign_keys=ON``，且 45 张表已补 ``tenants.id`` 外键，因此删除
    必须**按外键拓扑序**（子表在前、父表在后），否则 DELETE 直接 IntegrityError。

识别规则（可复现，不含硬编码 id）
    1) 标记命中：见 ``MARKER_RULES``，按 username / display_name / title / name /
       buyer_name 的 ``LIKE '%probe%'``（products 另加 ``'%探针%'``）命中，称为「根」；
    2) 传递闭包：沿外键图把「引用根行」的行一并纳入，称为「连带」（含业务表）。
    报告会逐表打印「被谁引用」的完整引用链，dry-run 即可人工复核。

已知歧义（不擅自处置，只在报告中列出）
    1) ``products`` 有 10 条「健身弹力带套装5件」在每次 probe 商品落库后 9~30ms 被
       同一次采集流程写入（``services/mock_market.insert_products`` 会把 created_at
       回溯 0~45 天，updated_at 才是真实写入时刻）。其标题与合法演示数据完全相同、
       无稳定标记，**无法与合法数据区分**，故不纳入自动删除。
    2) ``schedules`` 的 10 条 ``probe`` + 1 条 ``验收-趋势扫描`` 已被 D20 / S-9 明确
       裁定「保留取证」（run_count / last_run_at 是排查线索），默认**不纳入**，
       需显式 ``--include-schedules``。
    3) 另有 4 条「门禁验证商品 无图」/「测试缺货商品 采购流程」属测试残留但非 probe
       标记，只报告，需负责人裁决。

只读保证
    默认 dry-run 全程以 ``mode=ro`` + ``PRAGMA query_only=ON`` 打开；只有 ``--apply``
    才以读写方式打开，且删除在**单事务**内完成，失败整体回滚。

用法（在 backend 目录下执行）
    python scripts/cleanup_probe_data.py                        # 演练（默认）
    python scripts/cleanup_probe_data.py --db erp.db --json     # JSON 演练报告
    python scripts/cleanup_probe_data.py --apply                # 真正删除
    python scripts/cleanup_probe_data.py --apply --include-schedules

退出码
    0 = 正常（演练完成，或删除成功）
    2 = 存在 P0（预检有 FK 违规 / 删除后校验失败 / 行数变化与计划不符）
    3 = 用法错误 / 数据库不可读
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BACKEND_DIR / "erp.db"

# 只读巡检不应在磁盘上留下任何新文件（包括 __pycache__）
sys.dont_write_bytecode = True

_PROBE = ("%probe%",)

# 表 -> (识别列, LIKE 模式)。命中行即「根」；不含硬编码 id。
MARKER_RULES = (
    ("users", ("username", "display_name"), _PROBE),
    ("products", ("title",), ("%probe%", "%探针%")),
    ("suppliers", ("name",), _PROBE),
    ("ad_campaigns", ("name",), _PROBE),
    ("conversations", ("buyer_name",), _PROBE),
    ("knowledge_docs", ("title",), _PROBE),
)
# D20 的处置 SQL 用的就是这两个模式；本脚本沿用，但需 --include-schedules 显式开启。
SCHEDULES_RULE = ("schedules", ("name",), ("%probe%", "%验收%"))
# 非 probe 标记的其他测试命名残留：只报告，不删除。
OTHER_TEST_RULES = (("products", ("title",), ("%门禁验证%", "%测试缺货%")),)

# 报告中每表展示的识别列（人工复核「删的到底是什么」）
DISPLAY_COLS = {
    "users": ("username", "role"),
    "products": ("sku", "title"),
    "suppliers": ("name",),
    "ad_campaigns": ("name", "status"),
    "conversations": ("buyer_name",),
    "knowledge_docs": ("title",),
    "schedules": ("name", "enabled", "run_count"),
}
SAMPLE_ROWS = 6
# 采集连带产物的判定窗口（秒）：probe 商品与配对商品实测间隔 9~30ms
BYPRODUCT_WINDOW_SECONDS = 2.0


class CleanupError(RuntimeError):
    """用法 / 环境错误（退出码 3）。"""


def force_utf8_stdio() -> None:
    """管道 / 重定向场景强制 UTF-8，避免中文报告被按本地代码页解码成乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            continue


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def placeholders(count: int) -> str:
    return ",".join("?" * count)


def default_db_path() -> Path:
    """默认库：ERP_DB_URL 指向的文件，否则 backend/erp.db（只做字符串解析）。"""
    url = (os.getenv("ERP_DB_URL") or "").strip()
    if not url:
        return DEFAULT_DB
    match = re.match(r"^sqlite(?:\+[A-Za-z0-9_]+)?:///(?P<rest>.+)$", url)
    if not match:
        raise CleanupError("仅支持 sqlite 数据库，当前 ERP_DB_URL=%s" % url)
    return Path(match.group("rest"))


def open_db(path: Path, readonly: bool) -> sqlite3.Connection:
    """只读用 mode=ro + query_only；读写用 mode=rw 并开启外键强制。"""
    if not path.exists():
        raise CleanupError("数据库文件不存在：%s" % path)
    if path.is_dir():
        raise CleanupError("目标是目录而不是数据库文件：%s" % path)
    uri = "file:" + quote(path.resolve().as_posix(), safe="/:") + (
        "?mode=ro" if readonly else "?mode=rw")
    try:
        con = sqlite3.connect(uri, uri=True, isolation_level=None)
        con.execute("PRAGMA query_only=ON" if readonly else "PRAGMA foreign_keys=ON")
        con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as exc:
        raise CleanupError("打开数据库失败：%s（%s）" % (path, exc)) from exc
    return con


def table_names(con: sqlite3.Connection) -> list[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'"
                       " AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return [row[0] for row in rows]


def fk_edges(con: sqlite3.Connection, tables: list[str]) -> dict[str, list[tuple[str, str, str]]]:
    """child -> [(parent, child_col, parent_col)]，来自 PRAGMA foreign_key_list。"""
    return {table: [(f[2], f[3], f[4]) for f in
                    con.execute("PRAGMA foreign_key_list(%s)" % quote_ident(table))]
            for table in tables}


def children_map(tables: list[str], edges: dict) -> dict[str, set[str]]:
    """parent -> 引用它的子表集合（用于确定「子表在前」的删除序）。

    ``edges`` 允许只覆盖部分表（缺键视为「无外键」），这样本函数既能直接吃
    ``PRAGMA foreign_key_list`` 的原始结果，也能被测试用局部外键图单独驱动。
    """
    kids: dict[str, set[str]] = defaultdict(set)
    for child in tables:
        for parent, _col, _pcol in edges.get(child, ()):
            if parent != child:
                kids[parent].add(child)
    return kids


def has_id_pk(con: sqlite3.Connection, table: str) -> bool:
    info = con.execute("PRAGMA table_info(%s)" % quote_ident(table))
    return [c[1] for c in info if c[5]] == ["id"]


def find_marker_rows(con: sqlite3.Connection, rules, tables=None) -> dict[str, list[int]]:
    """按 LIKE 标记找出「根」行，返回 {表: [id, ...]}（排序，便于复现与比对）。

    ``tables`` 给定时只扫描其中存在的表——规则表清单是面向生产库写死的，
    在最小库/测试库上跑（缺 users 等表）不应直接崩，而应跳过缺失表。
    """
    hits: dict[str, list[int]] = {}
    for table, columns, patterns in rules:
        if tables is not None and table not in tables:
            continue
        # 每个「列 x 模式」组合各占一个占位符，绑定值按同序展开。
        clause = " OR ".join("LOWER(COALESCE(%s, '')) LIKE ?" % quote_ident(col)
                             for col in columns for _ in patterns)
        sql = "SELECT id FROM %s WHERE %s" % (quote_ident(table), clause)
        ids = sorted({row[0] for row in con.execute(sql, list(patterns) * len(columns))})
        if ids:
            hits[table] = ids
    return hits


def expand_closure(con: sqlite3.Connection, edges: dict, plan: dict) -> None:
    """把「引用计划行」的行并入计划，迭代到不动点（轮数上限防呆）。"""
    for _round in range(len(edges) + 2):
        added = False
        for child, links in edges.items():
            for parent, child_col, _pcol in links:
                ids = plan.get(parent)
                if not ids:
                    continue
                sql = "SELECT id FROM %s WHERE %s IN (%s)" % (
                    quote_ident(child), quote_ident(child_col), placeholders(len(ids)))
                found = {row[0] for row in con.execute(sql, sorted(ids))}
                new = found - plan.get(child, set())
                if new:
                    plan.setdefault(child, set()).update(new)
                    added = True
        if not added:
            return
    raise CleanupError("外键闭包未收敛，疑似外键图存在环")


def deletion_order(tables: list[str], edges: dict, plan: dict) -> list[str]:
    """子表在前、父表在后；只保留计划中非空的表。有环则报错而不是硬猜。"""
    kids = children_map(tables, edges)
    remaining = {table for table in plan if plan[table]}
    order: list[str] = []
    while remaining:
        ready = sorted(t for t in remaining if not (kids[t] & remaining))
        if not ready:
            raise CleanupError("外键图存在环，无法确定删除顺序：%s" % sorted(remaining))
        order.extend(ready)
        remaining -= set(ready)
    return order


def table_counts(con: sqlite3.Connection, tables: list[str]) -> dict[str, int]:
    return {table: int(con.execute("SELECT COUNT(*) FROM %s" % quote_ident(table)).fetchone()[0])
            for table in tables}


def checks(con: sqlite3.Connection) -> dict:
    """返回 {integrity_ok, fk_violations}；后者为 PRAGMA foreign_key_check 的行数。"""
    return {
        "integrity_ok": con.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
        "fk_violations": [tuple(row) for row in con.execute("PRAGMA foreign_key_check")],
    }


def reference_chain(con: sqlite3.Connection, tables: list[str], edges: dict, plan: dict) -> list[dict]:
    """列出「计划行被哪些表的哪些列引用」，供 dry-run 人工复核引用链。"""
    kids = children_map(tables, edges)
    chain = []
    for parent in sorted(plan):
        ids = sorted(plan[parent])
        for child in sorted(kids.get(parent, ())):
            cols = sorted({col for p, col, _pc in edges[child] if p == parent})
            total = 0
            for col in cols:
                sql = "SELECT COUNT(*) FROM %s WHERE %s IN (%s)" % (
                    quote_ident(child), quote_ident(col), placeholders(len(ids)))
                total += int(con.execute(sql, ids).fetchone()[0])
            if total:
                chain.append({"parent": parent, "child": child, "columns": cols, "rows": total})
    return chain


def describe_rows(con: sqlite3.Connection, table: str, ids: list[int],
                  limit: int = SAMPLE_ROWS) -> list[dict]:
    """取出根行的识别字段，供人工复核。"""
    columns = [c[1] for c in con.execute("PRAGMA table_info(%s)" % quote_ident(table))]
    names = [c for c in ("id", *DISPLAY_COLS.get(table, ())) if c in columns]
    sql = "SELECT %s FROM %s WHERE id IN (%s) ORDER BY id LIMIT %d" % (
        ",".join(quote_ident(c) for c in names), quote_ident(table),
        placeholders(len(ids)), limit)
    return [dict(zip(names, row)) for row in con.execute(sql, ids)]


def parse_ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def collect_byproducts(con: sqlite3.Connection, marker_ids: list[int]) -> list[dict]:
    """报告「无 probe 标记、但在 probe 商品落库后 2 秒内写入」的商品（只报告）。

    实测这些行是采集流程的连带产物，但标题与合法演示数据完全相同，无法用稳定
    标记区分，故不纳入自动删除（见模块文档「已知歧义」）。
    """
    if not marker_ids:
        return []
    marks = [ts for ts in (parse_ts(row[0]) for row in con.execute(
        "SELECT updated_at FROM products WHERE id IN (%s)" % placeholders(len(marker_ids)),
        marker_ids)) if ts is not None]
    if not marks:
        return []
    marker_set = set(marker_ids)
    found = []
    for pid, title, updated in con.execute(
            "SELECT id, title, updated_at FROM products ORDER BY id"):
        if pid in marker_set:
            continue
        ts = parse_ts(updated)
        if ts and any(abs((ts - mark).total_seconds()) <= BYPRODUCT_WINDOW_SECONDS
                      for mark in marks):
            found.append({"id": pid, "title": title, "updated_at": updated})
    return found


def apply_plan(con: sqlite3.Connection, order: list[str], plan: dict) -> dict[str, int]:
    """按拓扑序在单事务内删除；任何一步失败整体回滚。"""
    deleted: dict[str, int] = {}
    con.execute("BEGIN IMMEDIATE")
    try:
        for table in order:
            ids = sorted(plan[table])
            sql = "DELETE FROM %s WHERE id IN (%s)" % (
                quote_ident(table), placeholders(len(ids)))
            deleted[table] = con.execute(sql, ids).rowcount
        con.execute("COMMIT")
    except sqlite3.Error:
        con.execute("ROLLBACK")
        raise
    return deleted


def inspect(con: sqlite3.Connection, rules, tables: list[str], edges: dict) -> dict:
    """只读体检：根行、外键闭包计划、拓扑序、引用链、采集连带产物。"""
    roots = find_marker_rows(con, rules, tables)
    plan = {table: set(ids) for table, ids in roots.items()}
    expand_closure(con, edges, plan)
    unsupported = sorted(t for t in plan if not has_id_pk(con, t))
    if unsupported:
        raise CleanupError("以下表主键不是单一 id 列，无法按 id 删除：%s" % unsupported)
    return {
        "roots": roots,
        "plan": {table: sorted(ids) for table, ids in sorted(plan.items())},
        "order": deletion_order(tables, edges, plan),
        "reference_chain": reference_chain(con, tables, edges, plan),
        "root_rows": {t: describe_rows(con, t, ids) for t, ids in roots.items()},
        "collect_byproducts": collect_byproducts(con, roots.get("products", [])),
        "other_test_rows": find_marker_rows(con, OTHER_TEST_RULES, tables),
    }


def run(args) -> dict:
    """演练或执行；返回报告字典（含 p0 标记，决定退出码）。"""
    db_path = Path(args.db) if args.db else default_db_path()
    con = open_db(db_path, readonly=not args.apply)
    try:
        tables = table_names(con)
        edges = fk_edges(con, tables)
        rules = MARKER_RULES + ((SCHEDULES_RULE,) if args.include_schedules else ())
        before = table_counts(con, tables)
        pre = checks(con)
        found = inspect(con, rules, tables, edges)
        report = {
            "db": str(db_path.resolve()),
            "mode": "apply" if args.apply else "dry-run",
            "include_schedules": bool(args.include_schedules),
            "integrity_before": pre["integrity_ok"],
            "pre_fk_violations": pre["fk_violations"],
            "plan_rows": {t: len(v) for t, v in found["plan"].items()},
            "total_plan_rows": sum(len(v) for v in found["plan"].values()),
            "applied": False,
            "deleted": {},
            "row_delta": {},
            "fk_violations_after": None,
            "integrity_after": None,
            "p0": False,
        }
        report.update(found)
        if not args.apply:
            return report
        if report["pre_fk_violations"]:
            report["p0"] = True
            report["message"] = "删除前 foreign_key_check 非空，拒绝执行"
            return report
        if not report["total_plan_rows"]:
            report["message"] = "未发现 probe 残留，无需删除（幂等）"
            return report
        report["deleted"] = apply_plan(con, found["order"], found["plan"])
        after = table_counts(con, tables)
        post = checks(con)
        report["row_delta"] = {t: after[t] - before[t] for t in tables if after[t] != before[t]}
        report["fk_violations_after"] = post["fk_violations"]
        report["integrity_after"] = post["integrity_ok"]
        report["applied"] = True
        report["p0"] = bool(post["fk_violations"]) or not post["integrity_ok"]
        mismatch = {t: [report["deleted"].get(t, 0), -report["row_delta"].get(t, 0)]
                    for t in report["deleted"]
                    if report["deleted"].get(t, 0) != -report["row_delta"].get(t, 0)}
        if mismatch:
            report["p0"] = True
            report["delta_mismatch"] = mismatch
        return report
    finally:
        con.close()


def render(report: dict) -> str:
    lines = ["=" * 78, "probe 残留数据清理报告（mode=%s）" % report["mode"], "=" * 78,
             "数据库：%s" % report["db"],
             "删除前：integrity=%s / foreign_key_check 违规=%d" % (
                 "ok" if report["integrity_before"] else "FAIL",
                 len(report["pre_fk_violations"])),
             "", "【根】按标记命中（%d 表）" % len(report["roots"])]
    for table, ids in report["roots"].items():
        lines.append("  %s：%d 行  id=%s" % (table, len(ids), ids))
        for row in report["root_rows"].get(table, []):
            lines.append("      %s" % row)
    lines.append("")
    lines.append("【计划】子表在前（共 %d 行，含外键连带）" % report["total_plan_rows"])
    for table in report["order"]:
        lines.append("  %-28s %5d" % (table, report["plan_rows"].get(table, 0)))
    if report["reference_chain"]:
        lines.append("")
        lines.append("【引用链】计划行被谁引用")
        for item in report["reference_chain"]:
            lines.append("  %s <- %s.%s（%d 行）" % (
                item["parent"], item["child"], "/".join(item["columns"]), item["rows"]))
    if report["collect_byproducts"]:
        lines.append("")
        lines.append("【未纳入·歧义】无 probe 标记、但紧随 probe 商品写入的商品"
                     "（%d 行，需裁决）" % len(report["collect_byproducts"]))
        for row in report["collect_byproducts"]:
            lines.append("  id=%s %s updated_at=%s" % (
                row["id"], row["title"], row["updated_at"]))
    if report["other_test_rows"]:
        lines.append("")
        lines.append("【未纳入·非 probe 标记】其他测试命名残留（需裁决）")
        for table, ids in report["other_test_rows"].items():
            lines.append("  %s：%d 行  id=%s" % (table, len(ids), ids))
    if not report["include_schedules"]:
        lines.append("")
        lines.append("【未纳入】schedules 的 probe/验收 任务按 D20 / S-9 保留取证；"
                     "如需删除请加 --include-schedules")
    lines.append("")
    if report["applied"]:
        lines.append("【结果】已删除 %d 表" % len(report["deleted"]))
        for table, count in report["deleted"].items():
            lines.append("  %-28s -%d（行数变化 %+d）" % (
                table, count, report["row_delta"].get(table, 0)))
        lines.append("删除后：integrity=%s / foreign_key_check 违规=%d" % (
            "ok" if report["integrity_after"] else "FAIL",
            len(report["fk_violations_after"] or [])))
    else:
        lines.append("【结果】演练模式，未写库。%s" % report.get("message", ""))
    if report.get("delta_mismatch"):
        lines.append("P0 行数变化与计划不符：%s" % report["delta_mismatch"])
    lines.append("=" * 78)
    lines.append("exit_code=%d%s" % (2 if report["p0"] else 0,
                                     "（存在 P0 失败）" if report["p0"] else ""))
    return "\n".join(lines)


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="probe 残留数据清理器：默认只读演练，--apply 才真正删除。")
    parser.add_argument("--db", default=None,
                        help="数据库文件路径；默认 ERP_DB_URL，其次 backend/erp.db")
    parser.add_argument("--apply", action="store_true", help="真正执行删除（默认只演练）")
    parser.add_argument("--include-schedules", action="store_true",
                        help="同时删除 schedules 的 probe/验收 任务（D20 曾裁定保留取证）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出到 stdout")
    parser.add_argument("--out", default=None, help="同时把 JSON 报告写入指定文件")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    force_utf8_stdio()
    args = _parse_args(argv)
    try:
        report = run(args)
    except CleanupError as exc:
        print("cleanup error: %s" % exc, file=sys.stderr)
        return 3
    except sqlite3.Error as exc:
        print("sqlite error: %s" % exc, file=sys.stderr)
        return 3
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return 2 if report["p0"] else 0


if __name__ == "__main__":
    sys.exit(main())
