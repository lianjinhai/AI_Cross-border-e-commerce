"""店铺角色（Supply/Sales）只读盘点：找出 role 与平台默认推导不一致的店铺。

用法（在 backend 目录执行）：
    python scripts/audit_shop_roles.py            # 人类可读表格
    python scripts/audit_shop_roles.py --json     # JSON 输出（便于流水线消费）

只读保证：
    1. 数据库地址默认取 ERP_DB_URL，未设置时取 app.config.settings.db_url；
    2. SQLite 一律以 `mode=ro` URI 打开，并设置 PRAGMA query_only=ON；
    3. 不执行 CREATE/ALTER/UPDATE/DELETE/INSERT/VACUUM；修复建议 SQL 只打印，不执行。

退出码：0 = 全部一致；1 = 存在不一致或 role 为空/NULL；2 = 无法只读打开数据库。
"""
import argparse
import json
import pathlib
import sqlite3
import sys
import unicodedata
from datetime import datetime
from urllib.parse import quote

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

_COLUMNS = ("id", "tenant_id", "platform", "shop_name", "role", "status")


def _db_url() -> str:
    """默认数据库地址：ERP_DB_URL 优先，其次 app.config.settings.db_url。"""
    from app import config

    return config.settings.db_url


def _sqlite_path(url: str) -> str | None:
    """从 SQLAlchemy URL 提取 SQLite 文件路径；非 SQLite 返回 None。"""
    if not url.startswith("sqlite"):
        return None
    try:
        from sqlalchemy.engine import make_url

        u = make_url(url)
        return u.database
    except Exception:
        for prefix in ("sqlite+pysqlite:///", "sqlite:///"):
            if url.startswith(prefix):
                return url[len(prefix):]
        return None


def _connect_ro(path: str) -> sqlite3.Connection:
    """以只读 URI 打开 SQLite，并叠加 query_only 双保险。"""
    uri = "file:" + quote(pathlib.Path(path).as_posix(), safe="/:") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def _expected_role(platform: str) -> str:
    """平台默认角色：1688 = source（货源），其余 = sales（销售）。"""
    try:
        from app.services.platform_adapters import ADAPTERS

        cls = ADAPTERS.get(platform)
        if cls is not None:
            return cls.role
    except Exception:
        pass
    return "source" if platform == "1688" else "sales"


def _order_counts(con: sqlite3.Connection) -> dict[int, int]:
    """每个店铺已归属的订单数（只读证据，用于判断改角色前是否已产生销售订单）。"""
    try:
        rows = con.execute(
            "SELECT shop_id, COUNT(*) FROM orders WHERE shop_id IS NOT NULL GROUP BY shop_id"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {int(shop_id): int(n) for shop_id, n in rows}


def collect(con: sqlite3.Connection) -> dict:
    shops = con.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM shops ORDER BY id").fetchall()
    counts = _order_counts(con)
    items, mismatches, null_roles = [], [], []
    for row in shops:
        shop = dict(zip(_COLUMNS, row))
        role = (shop["role"] or "").strip()
        expected = _expected_role(shop["platform"])
        shop["expected_role"] = expected
        shop["role_missing"] = role == ""
        shop["consistent"] = (not shop["role_missing"]) and role == expected
        shop["order_count"] = counts.get(int(shop["id"]), 0)
        items.append(shop)
        if shop["role_missing"]:
            null_roles.append(shop)
        elif role != expected:
            mismatches.append(shop)
    return {"items": items, "mismatches": mismatches, "null_roles": null_roles}


def _suggest_sql(mismatches: list[dict], null_roles: list[dict]) -> list[str]:
    """修复建议 SQL（只打印，绝不执行）：按 (平台, 期望角色) 分组生成 UPDATE。"""
    groups: dict[tuple[str, str], list[int]] = {}
    for shop in mismatches:
        groups.setdefault((shop["platform"], shop["expected_role"]), []).append(int(shop["id"]))
    for shop in null_roles:
        groups.setdefault((shop["platform"], shop["expected_role"]), []).append(int(shop["id"]))
    statements = []
    for (platform, expected), ids in sorted(groups.items()):
        ids_sql = ", ".join(str(i) for i in sorted(ids))
        statements.append(
            f"UPDATE shops SET role='{expected}' WHERE id IN ({ids_sql});"
            f"  -- 平台 {platform} 默认角色为 {expected}")
    return statements


_WARNINGS = [
    "以上 SQL 仅为修复建议，本脚本不执行任何写操作（只读连接 + query_only）。",
    "执行前必须确认这些店铺是否真的产生过销售订单（见 order_count 列）："
    "若已产生销售订单，改角色会改变订单归属语义，需人工判断，且不得自动执行。",
    "订单同步/CSV 导入的 Supply/Sales 守门已生效：role != sales 的店铺会被 400 拒绝。",
]


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(text))


def _pad(text, width: int) -> str:
    text = str(text)
    return text + " " * max(0, width - _width(text))


def _print_table(payload: dict) -> None:
    headers = list(_COLUMNS) + ["expected_role", "consistent", "order_count"]
    rows = [[shop.get(h, "") for h in headers] for shop in payload["shops"]]
    widths = [max(_width(h), *(_width(r[i]) for r in rows)) if rows else _width(h)
              for i, h in enumerate(headers)]
    line = "-+-".join("-" * w for w in widths)
    print(" | ".join(_pad(h, widths[i]) for i, h in enumerate(headers)))
    print(line)
    for shop, row in zip(payload["shops"], rows):
        mark = "OK" if shop["consistent"] else "MISMATCH"
        cells = [_pad(v, widths[i]) for i, v in enumerate(row)]
        cells[headers.index("consistent")] = _pad(mark, widths[headers.index("consistent")])
        print(" | ".join(cells))
    print(line)
    print(f"数据库：{payload['database']}")
    print(f"店铺总数：{payload['total_shops']}，"
          f"role 与平台默认不一致：{payload['mismatch_count']}，"
          f"role 为空/NULL：{payload['null_role_count']}")
    if payload["suggested_sql"]:
        print("\n修复建议 SQL（只打印，不执行）：")
        for sql in payload["suggested_sql"]:
            print("  " + sql)
    print("\n注意：")
    for warning in payload["warnings"]:
        print("  - " + warning)


def main() -> int:
    parser = argparse.ArgumentParser(description="店铺 Supply/Sales 角色只读盘点")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--db", default="", help="覆盖数据库地址（默认 ERP_DB_URL / settings.db_url）")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    url = args.db or _db_url()
    path = _sqlite_path(url)
    if not path:
        print(f"仅支持 SQLite 只读盘点，当前数据库地址：{url}", file=sys.stderr)
        return 2
    if not pathlib.Path(path).exists():
        print(f"数据库文件不存在：{path}", file=sys.stderr)
        return 2
    try:
        con = _connect_ro(path)
    except sqlite3.Error as exc:
        print(f"无法以只读方式打开数据库：{path}（{exc}）", file=sys.stderr)
        return 2
    try:
        found = collect(con)
    except sqlite3.Error as exc:
        print(f"只读查询失败：{exc}", file=sys.stderr)
        return 2
    finally:
        con.close()

    mismatches, null_roles = found["mismatches"], found["null_roles"]
    payload = {
        "database": pathlib.Path(path).as_posix(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "read_only": True,
        "total_shops": len(found["items"]),
        "mismatch_count": len(mismatches),
        "null_role_count": len(null_roles),
        "shops": found["items"],
        "mismatched_shop_ids": [s["id"] for s in mismatches],
        "null_role_shop_ids": [s["id"] for s in null_roles],
        "suggested_sql": _suggest_sql(mismatches, null_roles),
        "warnings": _WARNINGS,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_table(payload)
    return 1 if (mismatches or null_roles) else 0


if __name__ == "__main__":
    raise SystemExit(main())
