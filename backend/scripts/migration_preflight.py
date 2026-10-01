"""P1-01 只读 Migration Preflight 检查器。

用法（在 backend 目录下执行）：
    python scripts/migration_preflight.py [--db <path|sqlite-url>] [--json] [--out <report.json>]

退出码：
    0 = 无 P0 失败（允许存在 P1 警告）
    2 = 存在 P0 失败
    3 = 用法错误 / 数据库文件不可读

只读保证：
    1) SQLite 一律以 ``file:<abs>?mode=ro`` URI 打开，并设置连接级 ``PRAGMA query_only=ON``；
    2) 所有查询在显式事务内执行，结束统一 ``ROLLBACK``；
    3) 本脚本不包含任何 ALTER/INSERT/UPDATE/DELETE/CREATE/VACUUM/DROP 语句；
    4) 不 import ``app.db``（避免创建指向主库的 engine），默认库路径只读取字符串配置；
    5) 报告只输出 id、数量、角色名、平台名、表名、列名等非敏感值，不含 username、
       password_hash、token、邮箱或手机号。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

BACKEND_DIR = Path(__file__).resolve().parent.parent
VERSIONS_DIR = BACKEND_DIR / "migrations" / "versions"

# 只读巡检不应在磁盘上留下任何新文件（包括 __pycache__）
sys.dont_write_bytecode = True


def _force_utf8_stdio() -> None:
    """管道/重定向场景强制 UTF-8，避免中文报告被按本地代码页解码成乱码。

    交互式终端保持原样，交给控制台自身的编码处理。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty():
                continue
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover - 依赖宿主环境
            continue

P0 = "P0"
P1 = "P1"
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

# Phase 1 目标角色（来自冻结架构）
TARGET_ROLES = ("OWNER", "OPERATOR", "READ_ONLY", "COMPLIANCE")

# 旧 role -> (目标角色/身份, 说明)；仅作为迁移建议，不修改任何数据
ROLE_MAPPING = {
    "admin": ("OWNER", "普通 Workspace 管理者"),
    "owner": ("OWNER", "已是目标角色名"),
    "operator": ("OPERATOR", "普通 Workspace 运营"),
    "viewer": ("READ_ONLY", "只读成员"),
    "readonly": ("READ_ONLY", "只读成员"),
    "read_only": ("READ_ONLY", "只读成员"),
    "compliance_approver": ("COMPLIANCE", "合规审批"),
    "compliance": ("COMPLIANCE", "合规审批"),
    "supplier": ("FACTORY_COLLABORATOR", "工厂协作关系，不创建普通 Membership"),
    "factory": ("FACTORY_COLLABORATOR", "工厂协作关系，不创建普通 Membership"),
    "superadmin": ("PLATFORM_IDENTITY", "平台身份，不创建普通 Membership"),
}

# Setting key -> (建议作用域, 理由)；只输出建议
SETTING_SCOPE_SUGGESTIONS = {
    "llm": ("global", "平台级 LLM 接入配置，跨 Workspace 共享"),
    "fx": ("global", "全局汇率表，跨 Workspace 共享"),
    "platform_fees": ("global", "平台费率目录，属于平台参考数据"),
    "rules": ("tenant", "业务规则允许按 Workspace 定制"),
}

# 跨租户关联检查清单：(子表, 外键列, 父表)
CROSS_TENANT_PAIRS = (
    ("orders", "shop_id", "shops"),
    ("purchase_orders", "sales_order_id", "orders"),
    ("listings", "product_id", "products"),
)

# 平台默认 Shop role 推导：1688 -> source，其余 -> sales
SOURCE_PLATFORM = "1688"
DEFAULT_SALES_ROLE = "sales"
DEFAULT_SOURCE_ROLE = "source"


class PreflightError(RuntimeError):
    """用法或文件读取错误（退出码 3）。"""


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _result(key: str, title: str, severity: str, status: str, message: str, evidence: dict) -> dict:
    return {
        "key": key,
        "title": title,
        "status": status,
        "severity": severity,
        "evidence": evidence,
        "message": message,
    }


def _table_names(con: sqlite3.Connection) -> list:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _column_names(con: sqlite3.Connection, table: str) -> list:
    return [r[1] for r in con.execute("PRAGMA table_info(%s)" % _quote_ident(table)).fetchall()]


def _count(con: sqlite3.Connection, table: str, where: str = "") -> int:
    sql = "SELECT COUNT(*) FROM %s" % _quote_ident(table)
    if where:
        sql += " WHERE " + where
    return int(con.execute(sql).fetchone()[0])


def _has_table(con: sqlite3.Connection, table: str) -> bool:
    return table in _table_names(con)


# --------------------------------------------------------------------------
# 数据库路径解析与只读连接
# --------------------------------------------------------------------------
def sqlite_path_from_url(url: str) -> Path:
    """把 SQLAlchemy 的 sqlite URL 转成文件系统路径（只做字符串解析）。"""
    text = (url or "").strip()
    match = re.match(r"^sqlite(?:\+[A-Za-z0-9_]+)?:///(?P<rest>.+)$", text)
    if not match:
        raise PreflightError(
            "仅支持 sqlite 数据库，当前配置为：%s" % (text or "<empty>"))
    rest = match.group("rest").strip()
    if not rest or rest == ":memory:":
        raise PreflightError("不支持内存数据库：%s" % text)
    return Path(rest)


def resolve_default_db_path() -> Path:
    """默认库路径：优先 ERP_DB_URL，其次 app.config.settings.db_url（只读字符串）。"""
    env_url = os.getenv("ERP_DB_URL", "").strip()
    if env_url:
        return sqlite_path_from_url(env_url)
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    try:
        from app.config import settings  # 只读取字符串，不创建 engine
    except Exception as exc:  # pragma: no cover - 环境异常分支
        raise PreflightError(
            "未设置 ERP_DB_URL 且无法读取 app.config.settings：%s" % exc) from exc
    return sqlite_path_from_url(settings.db_url)


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """以只读 URI 打开 SQLite，并叠加连接级 query_only 保护。"""
    path = Path(db_path)
    if not path.exists():
        raise PreflightError("数据库文件不存在：%s" % path)
    if path.is_dir():
        raise PreflightError("目标路径是目录而不是数据库文件：%s" % path)
    uri = "file:" + quote(path.resolve().as_posix(), safe="/:") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, isolation_level=None)
        con.execute("PRAGMA query_only=ON")
        con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as exc:
        raise PreflightError("只读打开失败：%s（%s）" % (path, exc)) from exc
    return con


# --------------------------------------------------------------------------
# 检查 1：schema fingerprint
# --------------------------------------------------------------------------
def check_schema_fingerprint(con: sqlite3.Connection) -> dict:
    tables = _table_names(con)
    per_table = {}
    column_count = 0
    for table in tables:
        tokens = []
        for col in con.execute("PRAGMA table_info(%s)" % _quote_ident(table)).fetchall():
            # col = (cid, name, type, notnull, dflt_value, pk)
            tokens.append("%s:%s(%s,%s,%s)" % (table, col[1], (col[2] or "").upper(), col[3], col[5]))
            column_count += 1
        blob = "|".join(sorted(tokens))
        per_table[table] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    total_blob = "\n".join("%s:%s" % (t, per_table[t]) for t in sorted(per_table))
    total_hash = hashlib.sha256(total_blob.encode("utf-8")).hexdigest()

    evidence = {
        "total_hash": total_hash,
        "table_count": len(tables),
        "column_count": column_count,
        "per_table": per_table,
        "fingerprint_format": "sha256(sorted('表名:列名(类型,notnull,pk)'))",
    }
    if not tables:
        return _result("schema_fingerprint", "Schema 指纹", P0, FAIL,
                       "数据库没有任何用户表，无法形成迁移基线指纹。", evidence)
    return _result("schema_fingerprint", "Schema 指纹", P0, PASS,
                   "已生成 %d 张表的稳定指纹，总哈希 %s，供迁移前后比对。"
                   % (len(tables), total_hash[:16]), evidence)


# --------------------------------------------------------------------------
# 检查 2：alembic 账本
# --------------------------------------------------------------------------
def discover_alembic_heads(versions_dir: Path) -> tuple:
    """解析 migrations/versions 下的 revision 链，返回 (heads, revisions, files)。"""
    revisions = {}
    files = []
    directory = Path(versions_dir)
    if not directory.is_dir():
        return [], revisions, files
    for script in sorted(directory.glob("*.py")):
        text = script.read_text(encoding="utf-8", errors="replace")
        rev = re.search(r"^\s*revision\s*=\s*[\"']([^\"']+)[\"']", text, re.M)
        if not rev:
            continue
        down = re.search(r"^\s*down_revision\s*=\s*(.+)$", text, re.M)
        downs = []
        if down:
            rhs = down.group(1).strip()
            if rhs not in ("None", "null"):
                downs = re.findall(r"[\"']([^\"']+)[\"']", rhs)
        revisions[rev.group(1)] = downs
        files.append(script.name)
    referenced = {item for downs in revisions.values() for item in downs}
    heads = sorted(set(revisions) - referenced)
    return heads, revisions, files


def _ancestry_path(revisions: dict, current: str, head: str) -> list[str] | None:
    """head 沿 down_revision 上溯到 current 的线性链（不含 current）；不可达返回 None。

    用于 `--planned-upgrade`：主库一次落后多个迁移时仍可逐级应用，但仍要求目标是
    **唯一代码 head**、且 current 在它的**唯一线性祖先链**上——分叉、跨链或目标不是
    head 一律拒绝，防漂移内核不变（D58 对 D47「直接后继」口径的精确化）。
    """
    path: list[str] = []
    node = head
    seen: set[str] = set()
    while node != current:
        if node in seen:
            return None
        seen.add(node)
        downs = revisions.get(node) or []
        if len(downs) != 1:
            return None
        node = downs[0]
        path.append(node)
    return path


def check_alembic_ledger(con: sqlite3.Connection, versions_dir: Path = VERSIONS_DIR,
                         planned_upgrade: str | None = None) -> dict:
    heads, revisions, files = discover_alembic_heads(versions_dir)
    current = []
    if _has_table(con, "alembic_version"):
        current = [r[0] for r in con.execute("SELECT version_num FROM alembic_version").fetchall()]
    evidence = {
        "db_current": sorted(current),
        "code_heads": heads,
        "head_count": len(heads),
        "revision_count": len(revisions),
        "script_files": files,
        "matches": sorted(current) == heads and len(heads) == 1,
        "planned_upgrade": planned_upgrade,
    }
    if not current:
        return _result("alembic_ledger", "Alembic 账本一致性", P0, FAIL,
                       "数据库没有 alembic_version 记录，无法确认迁移起点。", evidence)
    if len(heads) != 1:
        return _result("alembic_ledger", "Alembic 账本一致性", P0, FAIL,
                       "代码 revision 链存在 %d 个 head（%s），账本歧义，禁止 upgrade/stamp。"
                       % (len(heads), ", ".join(heads) or "无"), evidence)
    if planned_upgrade:
        path = (_ancestry_path(revisions, current[0], planned_upgrade)
                if (len(current) == 1 and heads[0] == planned_upgrade) else None)
        if path is not None:
            evidence["planned_path"] = path
            return _result("alembic_ledger", "Alembic 账本一致性", P0, PASS,
                           "计划迁移已验证：%s 可从当前版本 %s 沿线性链到达（%d 步）。"
                           % (planned_upgrade, current[0], len(path)), evidence)
        return _result("alembic_ledger", "Alembic 账本一致性", P0, FAIL,
                       "计划迁移目标必须是唯一代码 head，且数据库 current 必须是它的"
                       "线性祖先（跨链、分叉或跳过中间 revision 一律拒绝）。", evidence)
    if sorted(current) != heads:
        return _result("alembic_ledger", "Alembic 账本一致性", P0, FAIL,
                       "迁移账本漂移：数据库 current=%s，代码 head=%s；禁止直接 upgrade 或盲目 stamp。"
                       % (", ".join(sorted(current)), heads[0]), evidence)
    return _result("alembic_ledger", "Alembic 账本一致性", P0, PASS,
                   "数据库 current 与代码 head 一致（%s）。" % heads[0], evidence)


# --------------------------------------------------------------------------
# 检查 3：行数清单
# --------------------------------------------------------------------------
def check_row_count_manifest(con: sqlite3.Connection) -> dict:
    tables = _table_names(con)
    per_table = {}
    total = 0
    for table in tables:
        count = _count(con, table)
        per_table[table] = count
        total += count
    evidence = {
        "table_count": len(tables),
        "total_rows": total,
        "per_table": per_table,
    }
    if total == 0:
        return _result("row_count_manifest", "行数清单", P1, WARN,
                       "数据库所有表行数为 0，请确认是否指向了正确的库。", evidence)
    return _result("row_count_manifest", "行数清单", P1, PASS,
                   "共 %d 张表、%d 行，已形成迁移基线清单。" % (len(tables), total), evidence)


# --------------------------------------------------------------------------
# 检查 4：外键完整性
# --------------------------------------------------------------------------
def check_foreign_key_check(con: sqlite3.Connection) -> dict:
    rows = con.execute("PRAGMA foreign_key_check").fetchall()
    violations = [
        {"table": r[0], "rowid": r[1], "parent_table": r[2], "fk_index": r[3]}
        for r in rows[:100]
    ]
    evidence = {
        "violation_count": len(rows),
        "violations": violations,
        "truncated": len(rows) > len(violations),
    }
    if rows:
        return _result("foreign_key_check", "外键完整性", P0, FAIL,
                       "PRAGMA foreign_key_check 发现 %d 条违规，必须先归因修复。" % len(rows), evidence)
    return _result("foreign_key_check", "外键完整性", P0, PASS,
                   "PRAGMA foreign_key_check 无违规。", evidence)


# --------------------------------------------------------------------------
# 检查 5：tenant 0
# --------------------------------------------------------------------------
def check_tenant_zero(con: sqlite3.Connection) -> dict:
    tables = [t for t in _table_names(con) if "tenant_id" in _column_names(con, t)]
    business = {}
    excluded = []
    for table in tables:
        if table == "tenants":
            continue
        if table == "users":
            where_super = "tenant_id = 0 AND LOWER(TRIM(COALESCE(role, ''))) = 'superadmin'"
            super_count = _count(con, table, where_super)
            if super_count:
                excluded.append({"table": "users", "rows": super_count,
                                 "reason": "superadmin 平台身份，Step 7 单独迁为 tenant_id=NULL"})
            business_count = _count(con, table, "tenant_id = 0 AND NOT (%s)" % where_super)
        else:
            business_count = _count(con, table, "tenant_id = 0")
        if business_count:
            business[table] = business_count
    total = sum(business.values())
    evidence = {
        "zero_rows_business": total,
        "per_table": business,
        "scanned_tables": len(tables),
        "excluded": excluded,
        "excluded_rows": sum(item["rows"] for item in excluded),
    }
    if total:
        return _result("tenant_zero", "Tenant 0 孤立数据", P0, FAIL,
                       "存在 %d 行业务数据 tenant_id=0 且不存在 Tenant 0，禁止自动归属。" % total,
                       evidence)
    return _result("tenant_zero", "Tenant 0 孤立数据", P0, PASS,
                   "无业务数据使用 tenant_id=0。", evidence)


# --------------------------------------------------------------------------
# 检查 6：孤儿租户
# --------------------------------------------------------------------------
def check_orphan_tenants(con: sqlite3.Connection) -> dict:
    evidence = {"users_count": None, "tenants_count": None, "orphan_user_count": 0,
                "orphan_user_ids": [], "tenants_without_users_count": 0,
                "tenants_without_users": [], "skipped": []}
    if not _has_table(con, "users") or not _has_table(con, "tenants"):
        evidence["skipped"] = ["users" if not _has_table(con, "users") else "tenants"]
        return _result("orphan_tenants", "Tenant 归属完整性", P0, PASS,
                       "缺少 users 或 tenants 表，本项跳过。", evidence)

    evidence["users_count"] = _count(con, "users")
    evidence["tenants_count"] = _count(con, "tenants")
    orphans = con.execute(
        "SELECT id, tenant_id FROM users WHERE tenant_id IS NOT NULL "
        "AND tenant_id NOT IN (SELECT id FROM tenants) ORDER BY id"
    ).fetchall()
    evidence["orphan_user_count"] = len(orphans)
    evidence["orphan_user_ids"] = [{"id": r[0], "tenant_id": r[1]} for r in orphans[:50]]
    lonely = con.execute(
        "SELECT id FROM tenants WHERE id NOT IN "
        "(SELECT tenant_id FROM users WHERE tenant_id IS NOT NULL) ORDER BY id"
    ).fetchall()
    evidence["tenants_without_users_count"] = len(lonely)
    evidence["tenants_without_users"] = [r[0] for r in lonely[:50]]

    if orphans:
        return _result("orphan_tenants", "Tenant 归属完整性", P0, FAIL,
                       "有 %d 个用户的 tenant_id 不在 tenants 表中，必须先归因。" % len(orphans),
                       evidence)
    return _result("orphan_tenants", "Tenant 归属完整性", P0, PASS,
                   "无孤儿用户；无用户租户 %d 个。" % len(lonely), evidence)


# --------------------------------------------------------------------------
# 检查 7：跨租户关联
# --------------------------------------------------------------------------
def check_cross_tenant_refs(con: sqlite3.Connection) -> dict:
    details = []
    skipped = []
    total_mismatch = 0
    total_dangling = 0
    for child, column, parent in CROSS_TENANT_PAIRS:
        if not _has_table(con, child) or not _has_table(con, parent):
            skipped.append("%s.%s -> %s" % (child, column, parent))
            continue
        child_cols = _column_names(con, child)
        parent_cols = _column_names(con, parent)
        if column not in child_cols or "id" not in parent_cols or "tenant_id" not in child_cols \
                or "tenant_id" not in parent_cols:
            skipped.append("%s.%s -> %s" % (child, column, parent))
            continue
        dangling = int(con.execute(
            "SELECT COUNT(*) FROM %s c WHERE c.%s IS NOT NULL AND c.%s NOT IN (SELECT id FROM %s)"
            % (_quote_ident(child), _quote_ident(column), _quote_ident(column), _quote_ident(parent))
        ).fetchone()[0])
        mismatch = int(con.execute(
            "SELECT COUNT(*) FROM %s c JOIN %s p ON c.%s = p.id "
            "WHERE c.tenant_id IS NOT NULL AND p.tenant_id IS NOT NULL AND c.tenant_id <> p.tenant_id"
            % (_quote_ident(child), _quote_ident(parent), _quote_ident(column))
        ).fetchone()[0])
        total_dangling += dangling
        total_mismatch += mismatch
        details.append({"relation": "%s.%s -> %s.id" % (child, column, parent),
                        "cross_tenant_rows": mismatch, "dangling_rows": dangling})
    evidence = {
        "checked_relations": len(details),
        "cross_tenant_rows": total_mismatch,
        "dangling_rows": total_dangling,
        "details": details,
        "skipped_relations": skipped,
    }
    if total_mismatch:
        return _result("cross_tenant_refs", "跨租户关联", P0, FAIL,
                       "发现 %d 条跨租户关联，禁止在迁移中沿用。" % total_mismatch, evidence)
    if total_dangling:
        return _result("cross_tenant_refs", "跨租户关联", P0, FAIL,
                       "发现 %d 条悬空引用，租户归属无法判定。" % total_dangling, evidence)
    return _result("cross_tenant_refs", "跨租户关联", P0, PASS,
                   "已检查 %d 组关联，无跨租户或悬空引用。" % len(details), evidence)


# --------------------------------------------------------------------------
# 检查 8：role 映射候选
# --------------------------------------------------------------------------
def check_role_mapping_candidates(con: sqlite3.Connection) -> dict:
    if not _has_table(con, "users") or "role" not in _column_names(con, "users"):
        return _result("role_mapping_candidates", "Role 映射候选", P1, PASS,
                       "缺少 users.role 列，本项跳过。", {"skipped": True})
    raw = con.execute(
        "SELECT COALESCE(role, '<null>'), COUNT(*) FROM users GROUP BY COALESCE(role, '<null>') "
        "ORDER BY COUNT(*) DESC, 1"
    ).fetchall()
    normalized = {}
    for value, count in raw:
        key = value.strip().lower() if value != "<null>" else ""
        normalized[key] = normalized.get(key, 0) + count
    mapped = []
    unmapped = []
    for key in sorted(normalized):
        count = normalized[key]
        if not key:
            unmapped.append({"value": "<null/empty>", "rows": count,
                             "suggestion": "先按 status 判定是否为平台身份或禁用账号，再人工归因"})
        elif key in ROLE_MAPPING:
            target, note = ROLE_MAPPING[key]
            mapped.append({"value": key, "rows": count, "target": target, "note": note})
        else:
            unmapped.append({"value": key, "rows": count,
                             "suggestion": "不在 Phase 1 目标角色候选内，需人工确认后显式映射"})
    evidence = {
        "raw_distribution": [{"role": r[0], "rows": r[1]} for r in raw],
        "normalized_distribution": [{"role": k or "<null/empty>", "rows": normalized[k]}
                                    for k in sorted(normalized)],
        "mapped_candidates": mapped,
        "unmapped_values": unmapped,
        "target_roles": list(TARGET_ROLES),
        "users_count": _count(con, "users"),
    }
    if unmapped:
        return _result("role_mapping_candidates", "Role 映射候选", P1, WARN,
                       "有 %d 类 role 取值不在 Phase 1 映射候选内，需人工确认。" % len(unmapped),
                       evidence)
    return _result("role_mapping_candidates", "Role 映射候选", P1, PASS,
                   "全部 %d 类 role 取值均有映射建议（仅建议，不修改数据）。" % len(mapped),
                   evidence)


# --------------------------------------------------------------------------
# 检查 9：Setting 作用域候选
# --------------------------------------------------------------------------
def check_setting_scope_candidates(con: sqlite3.Connection) -> dict:
    if not _has_table(con, "settings"):
        return _result("setting_scope_candidates", "Setting 作用域候选", P1, PASS,
                       "缺少 settings 表，本项跳过。", {"skipped": True})
    if "key" not in _column_names(con, "settings"):
        return _result("setting_scope_candidates", "Setting 作用域候选", P1, PASS,
                       "settings 表没有 key 列，本项跳过。", {"skipped": True})
    keys = [r[0] for r in con.execute(
        "SELECT \"key\" FROM settings ORDER BY \"key\"").fetchall()]
    suggestions = []
    needs_review = []
    for key in keys:
        text = "" if key is None else str(key)
        if text in SETTING_SCOPE_SUGGESTIONS:
            scope, reason = SETTING_SCOPE_SUGGESTIONS[text]
        else:
            scope, reason = "needs_review", "未在已知目录中，需人工确认全局/租户边界"
            needs_review.append(text)
        suggestions.append({"key": text, "suggested_scope": scope, "reason": reason})
    evidence = {
        "key_count": len(keys),
        "suggestions": suggestions,
        "global_count": sum(1 for s in suggestions if s["suggested_scope"] == "global"),
        "tenant_count": sum(1 for s in suggestions if s["suggested_scope"] == "tenant"),
        "needs_review": needs_review,
        "note": "只输出分类建议，不修改任何 Setting。",
    }
    return _result("setting_scope_candidates", "Setting 作用域候选", P1, PASS,
                   "共 %d 个 Setting key 已给出全局/租户分类建议。" % len(keys), evidence)


# --------------------------------------------------------------------------
# 检查 10：Shop role 审计
# --------------------------------------------------------------------------
def check_shop_role_audit(con: sqlite3.Connection) -> dict:
    if not _has_table(con, "shops") or "role" not in _column_names(con, "shops"):
        return _result("shop_role_audit", "Shop role 审计", P1, PASS,
                       "缺少 shops.role 列，本项跳过。", {"skipped": True})
    groups = con.execute(
        "SELECT COALESCE(platform, '<null>'), COALESCE(role, '<null>'), COUNT(*) "
        "FROM shops GROUP BY COALESCE(platform, '<null>'), COALESCE(role, '<null>') "
        "ORDER BY 1, 2"
    ).fetchall()
    mismatch_rows = con.execute(
        "SELECT COALESCE(platform, '<null>'), COALESCE(role, '<null>'), COUNT(*) FROM shops "
        "WHERE LOWER(TRIM(COALESCE(role, ''))) <> CASE WHEN LOWER(TRIM(COALESCE(platform, ''))) = ? "
        "THEN ? ELSE ? END GROUP BY 1, 2 ORDER BY 1, 2",
        (SOURCE_PLATFORM, DEFAULT_SOURCE_ROLE, DEFAULT_SALES_ROLE)
    ).fetchall()
    mismatch = sum(r[2] for r in mismatch_rows)
    empty_role = _count(con, "shops", "role IS NULL OR TRIM(role) = ''")
    evidence = {
        "shop_count": _count(con, "shops"),
        "by_platform_role": [{"platform": r[0], "role": r[1], "rows": r[2]} for r in groups],
        "mismatch_count": mismatch,
        "mismatch_breakdown": [{"platform": r[0], "role": r[1], "rows": r[2]} for r in mismatch_rows],
        "empty_role_count": empty_role,
        "expected_rule": "%s -> %s，其余平台 -> %s" % (SOURCE_PLATFORM, DEFAULT_SOURCE_ROLE, DEFAULT_SALES_ROLE),
    }
    if mismatch or empty_role:
        return _result("shop_role_audit", "Shop role 审计", P1, WARN,
                       "有 %d 个店铺 role 与平台默认推导不一致，%d 个 role 为空；需独立盘点修复。"
                       % (mismatch, empty_role), evidence)
    return _result("shop_role_audit", "Shop role 审计", P1, PASS,
                   "全部店铺 role 与平台默认推导一致。", evidence)


# --------------------------------------------------------------------------
# 检查 11：Order 来源审计
# --------------------------------------------------------------------------
def check_order_source_audit(con: sqlite3.Connection) -> dict:
    if not _has_table(con, "orders"):
        return _result("order_source_audit", "Order 来源审计", P0, PASS,
                       "缺少 orders 表，本项跳过。", {"skipped": True})
    columns = _column_names(con, "orders")
    distribution = []
    if "source" in columns:
        distribution = [{"source": r[0], "rows": r[1]} for r in con.execute(
            "SELECT COALESCE(source, '<null>'), COUNT(*) FROM orders "
            "GROUP BY COALESCE(source, '<null>') ORDER BY 1").fetchall()]
    shop_id_null = _count(con, "orders", "shop_id IS NULL") if "shop_id" in columns else None
    source_shop_orders = 0
    if "shop_id" in columns and _has_table(con, "shops") and "role" in _column_names(con, "shops"):
        source_shop_orders = int(con.execute(
            "SELECT COUNT(*) FROM orders o JOIN shops s ON o.shop_id = s.id "
            "WHERE LOWER(TRIM(COALESCE(s.role, ''))) = ?", (DEFAULT_SOURCE_ROLE,)).fetchone()[0])
    evidence = {
        "orders_count": _count(con, "orders"),
        "source_distribution": distribution,
        "shop_id_null_count": shop_id_null,
        "source_shop_order_count": source_shop_orders,
        "source_role": DEFAULT_SOURCE_ROLE,
    }
    if source_shop_orders:
        return _result("order_source_audit", "Order 来源审计", P0, FAIL,
                       "有 %d 条订单挂在 role='source' 的货源店铺上，货源店铺不应产生销售订单。"
                       % source_shop_orders, evidence)
    return _result("order_source_audit", "Order 来源审计", P0, PASS,
                   "无订单挂在货源店铺；shop_id 为空的订单 %s 条。"
                   % ("未知" if shop_id_null is None else shop_id_null), evidence)


# --------------------------------------------------------------------------
# 检查 12：User 引用清单
# --------------------------------------------------------------------------
def check_user_reference_inventory(con: sqlite3.Connection) -> dict:
    columns = []
    total_non_null = 0
    total_dangling = 0
    has_users = _has_table(con, "users")
    for table in _table_names(con):
        for name in _column_names(con, table):
            if not (name.endswith("_by") or name.endswith("user_id")):
                continue
            non_null = int(con.execute(
                "SELECT COUNT(%s) FROM %s" % (_quote_ident(name), _quote_ident(table))).fetchone()[0])
            distinct = int(con.execute(
                "SELECT COUNT(DISTINCT %s) FROM %s" % (_quote_ident(name), _quote_ident(table))).fetchone()[0])
            dangling = 0
            if has_users:
                dangling = int(con.execute(
                    "SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL AND %s NOT IN (SELECT id FROM users)"
                    % (_quote_ident(table), _quote_ident(name), _quote_ident(name))).fetchone()[0])
            total_non_null += non_null
            total_dangling += dangling
            columns.append({"table": table, "column": name, "non_null_rows": non_null,
                            "distinct_users": distinct, "dangling_refs": dangling})
    evidence = {
        "column_count": len(columns),
        "columns": columns,
        "total_non_null_rows": total_non_null,
        "total_dangling_refs": total_dangling,
        "users_table_present": has_users,
        "note": "用于评估 Users Revision C 物理删用户风险。",
    }
    if total_dangling:
        return _result("user_reference_inventory", "User 引用清单", P1, WARN,
                       "发现 %d 条历史引用指向不存在的用户，物理删用户前必须先处理。" % total_dangling,
                       evidence)
    return _result("user_reference_inventory", "User 引用清单", P1, PASS,
                   "共 %d 个用户引用列、%d 行非空引用，无悬空引用。"
                   % (len(columns), total_non_null), evidence)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
CHECKS = (
    check_schema_fingerprint,
    check_alembic_ledger,
    check_row_count_manifest,
    check_foreign_key_check,
    check_tenant_zero,
    check_orphan_tenants,
    check_cross_tenant_refs,
    check_role_mapping_candidates,
    check_setting_scope_candidates,
    check_shop_role_audit,
    check_order_source_audit,
    check_user_reference_inventory,
)


def run_preflight(db_path: Path, versions_dir: Path = VERSIONS_DIR,
                  planned_upgrade: str | None = None) -> dict:
    """执行全部只读检查，返回报告字典。"""
    path = Path(db_path)
    if not path.exists():
        raise PreflightError("数据库文件不存在：%s" % path)
    size = path.stat().st_size
    con = open_readonly(path)
    try:
        con.execute("BEGIN")
        try:
            checks = []
            for check in CHECKS:
                if check is check_alembic_ledger:
                    checks.append(check(con, versions_dir, planned_upgrade))
                else:
                    checks.append(check(con))
        finally:
            con.execute("ROLLBACK")
    finally:
        con.close()

    summary = {
        "p0_fail": sum(1 for c in checks if c["severity"] == P0 and c["status"] == FAIL),
        "p1_warn": sum(1 for c in checks if c["status"] == WARN),
        "pass": sum(1 for c in checks if c["status"] == PASS),
    }
    return {
        "generated_at": _now_iso(),
        "db_path": str(path.resolve()),
        "db_size_bytes": size,
        "readonly": True,
        "summary": summary,
        "checks": checks,
    }


def render_human(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "=" * 78,
        "Migration Preflight (READ-ONLY)",
        "DB        : %s" % report["db_path"],
        "Size      : %d bytes" % report["db_size_bytes"],
        "Generated : %s" % report["generated_at"],
        "Summary   : P0_fail=%d  P1_warn=%d  pass=%d"
        % (summary["p0_fail"], summary["p1_warn"], summary["pass"]),
        "=" * 78,
    ]
    for check in report["checks"]:
        lines.append("[%-4s][%s] %s — %s" % (check["status"], check["severity"],
                                             check["key"], check["title"]))
        lines.append("    %s" % check["message"])
        evidence = json.dumps(check["evidence"], ensure_ascii=False, indent=2)
        lines.append("    evidence: " + evidence.replace("\n", "\n    "))
    lines.append("=" * 78)
    lines.append("exit_code=%d%s" % (2 if summary["p0_fail"] else 0,
                                     " (存在 P0 失败)" if summary["p0_fail"] else ""))
    return "\n".join(lines)


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="只读、可重复的 Workspace 身份迁移预检器（不修改数据库）。")
    parser.add_argument("--db", default=None,
                        help="数据库文件路径或 sqlite URL；默认 ERP_DB_URL，其次 app.config.settings.db_url")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出到 stdout")
    parser.add_argument("--out", default=None, help="同时把 JSON 报告写入指定文件")
    parser.add_argument("--versions-dir", default=None,
                        help="Alembic versions 目录；默认 backend/migrations/versions")
    parser.add_argument("--planned-upgrade", default=None,
                        help="显式指定待执行的唯一 head；仅当前版本的直接后继可通过账本检查")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _force_utf8_stdio()
    args = _parse_args(argv)
    try:
        db_path = Path(args.db) if args.db else resolve_default_db_path()
        if args.db and str(args.db).startswith("sqlite"):
            db_path = sqlite_path_from_url(args.db)
        versions_dir = Path(args.versions_dir) if args.versions_dir else VERSIONS_DIR
        report = run_preflight(db_path, versions_dir, args.planned_upgrade)
    except PreflightError as exc:
        print("preflight error: %s" % exc, file=sys.stderr)
        return 3

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human(report))
    return 2 if report["summary"]["p0_fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
