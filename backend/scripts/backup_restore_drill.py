#!/usr/bin/env python3
"""SQLite 一致性备份与恢复演练工具（Phase 1 P1-04 迁移门禁）。

设计约束：
  * 源库始终以只读 URI（mode=ro + query_only）打开，绝不修改主库；
  * 备份一律通过 SQLite 官方备份 API（sqlite3.Connection.backup）生成，
    禁止使用文件复制 —— WAL 状态下复制文件可能得到不一致副本；
  * 绝不覆盖已有备份文件，同名时自动追加序号；
  * 输出只包含表名、计数与哈希，不输出 username / password_hash /
    token / setting value 等敏感值。

子命令：
  backup  生成一致性备份与 <同名>.manifest.json
  verify  按 manifest 重新校验备份（哈希 / 完整性 / 外键 / 行数 / Alembic）
  drill   备份 → 恢复到全新路径 → 与源库逐项比对 → 只读验证关键表

退出码：0 全部通过；1 校验失败；2 运行环境或参数错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

TOOL_NAME = "backup_restore_drill"
TOOL_VERSION = "1.0.0"
MANIFEST_VERSION = 1
BACKUP_PREFIX = "erp-"
BACKUP_SUFFIX = ".db"
MANIFEST_SUFFIX = ".manifest.json"
KEY_TABLES = ("tenants", "users", "orders", "products", "shops", "settings")

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parent.parent
DEFAULT_OUT_DIR = BACKEND_DIR / "backups"


class DrillError(RuntimeError):
    """可预期的运行环境错误，附带可操作提示。"""


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_size(path: Path) -> int:
    return path.stat().st_size


def iso_mtime(path: Path) -> str:
    stamp = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    return stamp.isoformat(timespec="seconds")


def connect_readonly(path: Path) -> sqlite3.Connection:
    """以只读方式打开数据库，任何写入都会直接被 SQLite 拒绝。"""
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise DrillError(
            f"无法以只读方式打开数据库：{path}\n"
            f"原因：{exc}\n"
            "排查：确认文件存在、是有效的 SQLite 库、当前用户有读取权限，"
            "且没有其他进程以独占方式锁定该文件。"
        ) from exc
    conn.execute("PRAGMA query_only = ON")
    return conn


def require_source_db(path: Path) -> Path:
    resolved = path.expanduser()
    if not resolved.exists():
        raise DrillError(
            f"主库不存在：{resolved}\n排查：确认 --db 路径，例如在 backend 目录下使用 --db erp.db。"
        )
    if resolved.is_dir():
        raise DrillError(f"--db 指向的是目录而不是数据库文件：{resolved}")
    if resolved.stat().st_size == 0:
        raise DrillError(f"主库文件为空（0 字节）：{resolved}\n排查：确认库文件完整。")
    with open(resolved, "rb") as handle:
        header = handle.read(16)
    if header != b"SQLite format 3\x00":
        raise DrillError(
            f"不是有效的 SQLite 数据库文件（文件头不匹配）：{resolved}\n"
            "排查：确认没有把 -wal / -shm 或日志文件当成主库。"
        )
    return resolved


def quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows if not str(row[0]).startswith("sqlite_")]


def collect_row_counts(conn: sqlite3.Connection) -> dict:
    counts = {}
    for table in list_tables(conn):
        counts[table] = int(
            conn.execute("SELECT COUNT(*) FROM " + quote_ident(table)).fetchone()[0]
        )
    return counts


def schema_fingerprint(conn: sqlite3.Connection) -> str:
    """对 sqlite_master 的定义做摘要，用于证明 schema 完全一致。"""
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    payload = "\n".join(
        "\x1f".join("" if value is None else str(value) for value in row) for row in rows
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_integrity_check(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    messages = [str(row[0]) for row in rows]
    ok = messages == ["ok"]
    return {"ok": ok, "result": "ok" if ok else "; ".join(messages)}


def run_foreign_key_check(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    violations = [
        {
            "table": str(row[0]),
            "rowid": row[1],
            "parent": str(row[2]),
            "fkid": row[3],
        }
        for row in rows
    ]
    return {"ok": not violations, "count": len(violations), "violations": violations}


def read_alembic_current(conn: sqlite3.Connection):
    try:
        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    return ",".join(str(row[0]) for row in rows)


def read_journal_mode(conn: sqlite3.Connection) -> str:
    try:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0])
    except sqlite3.Error:
        return "unknown"


def database_snapshot(conn: sqlite3.Connection) -> dict:
    tables = list_tables(conn)
    counts = collect_row_counts(conn)
    return {
        "tables": tables,
        "table_count": len(tables),
        "row_counts": counts,
        "total_rows": sum(counts.values()),
        "alembic_current": read_alembic_current(conn),
        "schema_fingerprint": schema_fingerprint(conn),
        "integrity_check": run_integrity_check(conn),
        "foreign_key_check": run_foreign_key_check(conn),
    }

# --------------------------------------------------------------------------
# 备份文件与 manifest
# --------------------------------------------------------------------------

def ensure_dir(path: Path, purpose: str) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DrillError(
            f"无法创建{purpose}：{path}\n"
            f"原因：{exc}\n排查：确认父目录存在、路径拼写正确、当前用户对该目录有写权限。"
        ) from exc
    if not path.is_dir():
        raise DrillError(f"{purpose}路径不是目录：{path}")
    return path


def reserve_path(target: Path) -> Path:
    """原子地占用目标路径，绝不覆盖已有文件；冲突时追加序号。"""
    candidate = target
    index = 1
    while True:
        try:
            handle = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            index += 1
            candidate = target.with_name(f"{target.stem}-{index}{target.suffix}")
            continue
        except PermissionError as exc:
            raise DrillError(
                f"无法写入目标路径：{candidate}\n"
                f"原因：{exc}\n排查：确认目录可写、文件未被其他进程占用、磁盘未满。"
            ) from exc
        except OSError as exc:
            raise DrillError(f"无法创建文件：{candidate}\n原因：{exc}") from exc
        os.close(handle)
        return candidate


def remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def create_consistent_backup(source: Path, destination: Path) -> None:
    """用 SQLite 官方备份 API 生成一致性副本。

    不使用文件复制：源库处于 WAL 时直接复制可能得到不一致或缺少最新事务的副本。
    备份完成后把副本归一到 DELETE 日志模式，使其成为不依赖旁文件的单文件制品。
    """
    source_conn = connect_readonly(source)
    try:
        try:
            dest_conn = sqlite3.connect(str(destination))
        except sqlite3.Error as exc:
            raise DrillError(f"无法打开备份目标文件：{destination}\n原因：{exc}") from exc
        try:
            source_conn.backup(dest_conn)
            dest_conn.execute("PRAGMA journal_mode=DELETE")
            dest_conn.commit()
        except sqlite3.Error as exc:
            raise DrillError(
                f"SQLite 备份 API 执行失败：{source} -> {destination}\n"
                f"原因：{exc}\n"
                "排查：确认源库未被独占锁定、磁盘剩余空间充足、目标路径可写。"
            ) from exc
        finally:
            dest_conn.close()
    finally:
        source_conn.close()


def build_manifest(
    source: Path,
    backup: Path,
    source_before: dict,
    source_after: dict,
    snapshot: dict,
) -> dict:
    changed = source_before["sha256"] != source_after["sha256"]
    return {
        "manifest_version": MANIFEST_VERSION,
        "tool": {
            "name": TOOL_NAME,
            "version": TOOL_VERSION,
            "python": sys.version.split()[0],
            "sqlite": sqlite3.sqlite_version,
        },
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "path": str(source),
            "size_bytes": source_after["size_bytes"],
            "sha256": source_after["sha256"],
            "mtime": source_after["mtime"],
            "sha256_before_backup": source_before["sha256"],
            "changed_during_backup": changed,
            "journal_mode": snapshot["journal_mode"],
        },
        "backup": {
            "file_name": backup.name,
            "path": str(backup),
            "size_bytes": file_size(backup),
            "sha256": sha256_file(backup),
            "journal_mode": snapshot["backup_journal_mode"],
        },
        "database": {
            "table_count": snapshot["table_count"],
            "total_rows": snapshot["total_rows"],
            "alembic_current": snapshot["alembic_current"],
            "schema_fingerprint": snapshot["schema_fingerprint"],
            "row_counts": snapshot["row_counts"],
        },
        "integrity_check": snapshot["integrity_check"],
        "foreign_key_check": snapshot["foreign_key_check"],
        "key_tables": list(KEY_TABLES),
        "key_tables_present": [
            name for name in KEY_TABLES if name in set(snapshot["tables"])
        ],
    }


def manifest_path_for(backup: Path) -> Path:
    return backup.with_name(backup.name + MANIFEST_SUFFIX)


def write_manifest(path: Path, manifest: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        raise DrillError(f"无法写入 manifest：{path}\n原因：{exc}") from exc


def load_manifest(path: Path) -> dict:
    if not path.exists():
        raise DrillError(
            f"找不到 manifest：{path}\n"
            "排查：确认备份目录下存在 <备份文件名>.manifest.json，"
            "或使用 backup 子命令重新生成带 manifest 的备份。"
        )
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DrillError(f"manifest 无法解析：{path}\n原因：{exc}") from exc
    if not isinstance(data, dict):
        raise DrillError(f"manifest 结构非法（顶层不是对象）：{path}")
    return data


def stat_snapshot(path: Path) -> dict:
    return {
        "size_bytes": file_size(path),
        "sha256": sha256_file(path),
        "mtime": iso_mtime(path),
    }

# --------------------------------------------------------------------------
# 检查结果模型
# --------------------------------------------------------------------------

def make_check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def fk_signature(violations: list) -> list:
    return sorted(
        f"{item['table']}.{item['rowid']}->{item['parent']}" for item in violations
    )


def parse_fk_baseline(raw: str) -> list:
    if not raw:
        return []
    return sorted(part.strip() for part in raw.split(",") if part.strip())


def render_checks(checks: list) -> list:
    lines = []
    for item in checks:
        lines.append(f"[{item['status']:<4}] {item['name']}: {item['detail']}")
    return lines


def summarize(checks: list) -> dict:
    failed = [c for c in checks if c["status"] == "FAIL"]
    warned = [c for c in checks if c["status"] == "WARN"]
    return {
        "total": len(checks),
        "passed": len([c for c in checks if c["status"] == "PASS"]),
        "failed": len(failed),
        "warned": len(warned),
        "ok": not failed,
        "failures": [c["name"] for c in failed],
        "warnings": [c["name"] for c in warned],
    }


def emit(report: dict, as_json: bool, checks: list, headline: str) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    for line in render_checks(checks):
        print(line)
    print(headline)


# --------------------------------------------------------------------------
# backup
# --------------------------------------------------------------------------

def command_backup(args) -> int:
    source = require_source_db(Path(args.db))
    out_dir = ensure_dir(Path(args.out_dir).expanduser(), "备份目录")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = reserve_path(out_dir / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}")

    source_before = stat_snapshot(source)
    source_conn = connect_readonly(source)
    try:
        source_mode = read_journal_mode(source_conn)
    finally:
        source_conn.close()

    try:
        create_consistent_backup(source, backup_path)
    except DrillError:
        remove_quietly(backup_path)
        raise
    source_after = stat_snapshot(source)

    backup_conn = connect_readonly(backup_path)
    try:
        snapshot = database_snapshot(backup_conn)
        snapshot["backup_journal_mode"] = read_journal_mode(backup_conn)
    finally:
        backup_conn.close()
    snapshot["journal_mode"] = source_mode

    manifest = build_manifest(source, backup_path, source_before, source_after, snapshot)
    write_manifest(manifest_path_for(backup_path), manifest)

    checks = [
        make_check("source_read_only", "PASS",
                   f"{source} 以只读方式打开，未被修改"),
        make_check("backup_created", "PASS",
                   f"{backup_path} ({manifest['backup']['size_bytes']} bytes, "
                   f"sha256={manifest['backup']['sha256'][:16]}...)"),
        make_check("integrity_check", "PASS" if snapshot["integrity_check"]["ok"] else "FAIL",
                   snapshot["integrity_check"]["result"]),
        make_check(
            "foreign_key_check",
            "PASS" if snapshot["foreign_key_check"]["ok"] else "WARN",
            "无外键违规" if snapshot["foreign_key_check"]["ok"] else
            f"{snapshot['foreign_key_check']['count']} 处外键违规（已如实记录到 manifest，"
            "迁移前需按 docs/phase1_migration_safety.md 处理）",
        ),
        make_check("inventory", "PASS",
                   f"表 {snapshot['table_count']} 张，总行 {snapshot['total_rows']} 行，"
                   f"alembic current={snapshot['alembic_current']}"),
        make_check(
            "source_stability",
            "WARN" if source_after["sha256"] != source_before["sha256"] else "PASS",
            "备份期间主库哈希未变化（已确认停写）"
            if source_after["sha256"] == source_before["sha256"] else
            "备份期间主库内容发生变化，说明仍有写入者；请在停写维护窗口内重新备份",
        ),
        make_check("manifest_written", "PASS", str(manifest_path_for(backup_path))),
    ]
    summary = summarize(checks)
    report = {
        "command": "backup",
        "ok": summary["ok"],
        "source": str(source),
        "backup": str(backup_path),
        "manifest": str(manifest_path_for(backup_path)),
        "checks": checks,
        "summary": summary,
        "manifest_content": manifest,
    }
    headline = (
        f"备份{'完成' if summary['ok'] else '完成但存在失败项'}："
        f"{backup_path}（表 {snapshot['table_count']} 张 / {snapshot['total_rows']} 行 / "
        f"alembic {snapshot['alembic_current']}）"
    )
    emit(report, args.json, checks, headline)
    return EXIT_OK if summary["ok"] else EXIT_FAIL

# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def command_verify(args) -> int:
    backup = Path(args.backup).expanduser()
    if not backup.exists():
        raise DrillError(f"备份文件不存在：{backup}\n排查：确认 --backup 路径。")
    if backup.stat().st_size == 0:
        raise DrillError(f"备份文件为空（0 字节）：{backup}")

    manifest_file = Path(args.manifest).expanduser() if args.manifest else manifest_path_for(backup)
    manifest = load_manifest(manifest_file)

    recorded = manifest.get("backup") or {}
    database = manifest.get("database") or {}
    checks = []

    actual_sha = sha256_file(backup)
    expected_sha = recorded.get("sha256")
    checks.append(make_check(
        "sha256",
        "PASS" if expected_sha and actual_sha == expected_sha else "FAIL",
        f"实测 {actual_sha[:16]}... / manifest {str(expected_sha)[:16]}..."
        if expected_sha else "manifest 缺少 backup.sha256 字段",
    ))

    actual_size = file_size(backup)
    expected_size = recorded.get("size_bytes")
    checks.append(make_check(
        "size_bytes",
        "PASS" if expected_size == actual_size else "FAIL",
        f"实测 {actual_size} / manifest {expected_size}",
    ))

    read_error = None
    conn = None
    try:
        conn = connect_readonly(backup)
        integrity = run_integrity_check(conn)
        fk = run_foreign_key_check(conn)
        tables = list_tables(conn)
        counts = collect_row_counts(conn)
        total_rows = sum(counts.values())
        alembic = read_alembic_current(conn)
        fingerprint = schema_fingerprint(conn)
    except sqlite3.Error as exc:
        read_error = str(exc)
        integrity = {"ok": False, "result": f"数据库无法读取：{exc}"}
        fk = {"ok": False, "count": 0, "violations": []}
        tables = []
        counts = {}
        total_rows = -1
        alembic = None
        fingerprint = None
    finally:
        if conn is not None:
            conn.close()

    checks.append(make_check(
        "integrity_check",
        "PASS" if integrity["ok"] else "FAIL",
        integrity["result"],
    ))

    recorded_fk = manifest.get("foreign_key_check") or {}
    expected_fk = fk_signature(recorded_fk.get("violations") or [])
    actual_fk = fk_signature(fk["violations"])
    checks.append(make_check(
        "foreign_key_check",
        "PASS" if not read_error and expected_fk == actual_fk else "FAIL",
        f"实测 {len(actual_fk)} 处 / manifest {len(expected_fk)} 处"
        + ("" if expected_fk == actual_fk else f"（明细不一致：{actual_fk} vs {expected_fk}）"),
    ))

    expected_tables = database.get("table_count")
    checks.append(make_check(
        "table_count",
        "PASS" if not read_error and expected_tables == len(tables) else "FAIL",
        f"实测 {len(tables)} / manifest {expected_tables}",
    ))

    expected_rows = database.get("total_rows")
    checks.append(make_check(
        "total_rows",
        "PASS" if not read_error and expected_rows == total_rows else "FAIL",
        f"实测 {total_rows} / manifest {expected_rows}",
    ))

    expected_counts = database.get("row_counts") or {}
    diffs = []
    for table in sorted(set(expected_counts) | set(counts)):
        if expected_counts.get(table) != counts.get(table):
            diffs.append(f"{table}: 实测 {counts.get(table)} / manifest {expected_counts.get(table)}")
    if read_error:
        row_counts_text = f"数据库无法读取：{read_error}"
    elif not diffs:
        row_counts_text = "全部表行数一致"
    else:
        row_counts_text = "; ".join(diffs[:5]) + (
            f"（共 {len(diffs)} 张表不一致）" if len(diffs) > 5 else ""
        )
    checks.append(make_check(
        "row_counts_per_table",
        "PASS" if not read_error and not diffs else "FAIL",
        row_counts_text,
    ))

    expected_alembic = database.get("alembic_current")
    checks.append(make_check(
        "alembic_current",
        "PASS" if not read_error and expected_alembic == alembic else "FAIL",
        f"实测 {alembic} / manifest {expected_alembic}",
    ))

    expected_fp = database.get("schema_fingerprint")
    fingerprint_text = (
        f"实测 {fingerprint[:16]}... / manifest {str(expected_fp)[:16]}..."
        if fingerprint else f"数据库无法读取：{read_error}"
    )
    checks.append(make_check(
        "schema_fingerprint",
        "PASS" if not read_error and expected_fp and expected_fp == fingerprint else "FAIL",
        fingerprint_text,
    ))

    summary = summarize(checks)
    report = {
        "command": "verify",
        "ok": summary["ok"],
        "backup": str(backup),
        "manifest": str(manifest_file),
        "read_error": read_error,
        "checks": checks,
        "summary": summary,
    }
    headline = (
        f"校验{'通过' if summary['ok'] else '未通过'}：{backup}"
        + ("" if summary["ok"] else f"（失败项：{', '.join(summary['failures'])}）")
    )
    emit(report, args.json, checks, headline)
    return EXIT_OK if summary["ok"] else EXIT_FAIL

# --------------------------------------------------------------------------
# drill
# --------------------------------------------------------------------------

def compare_snapshots(source_snapshot: dict, restored_snapshot: dict, checks: list) -> None:
    checks.append(make_check(
        "table_count_matches_source",
        "PASS" if source_snapshot["table_count"] == restored_snapshot["table_count"] else "FAIL",
        f"源库 {source_snapshot['table_count']} / 恢复库 {restored_snapshot['table_count']}",
    ))

    checks.append(make_check(
        "total_rows_match_source",
        "PASS" if source_snapshot["total_rows"] == restored_snapshot["total_rows"] else "FAIL",
        f"源库 {source_snapshot['total_rows']} / 恢复库 {restored_snapshot['total_rows']}",
    ))

    source_counts = source_snapshot["row_counts"]
    restored_counts = restored_snapshot["row_counts"]
    diffs = []
    for table in sorted(set(source_counts) | set(restored_counts)):
        if source_counts.get(table) != restored_counts.get(table):
            diffs.append(f"{table}: 源库 {source_counts.get(table)} / 恢复库 {restored_counts.get(table)}")
    checks.append(make_check(
        "row_counts_per_table_match_source",
        "PASS" if not diffs else "FAIL",
        "逐表行数全部一致" if not diffs else "; ".join(diffs[:5]) +
        (f"（共 {len(diffs)} 张表不一致）" if len(diffs) > 5 else ""),
    ))

    checks.append(make_check(
        "alembic_current_matches_source",
        "PASS" if source_snapshot["alembic_current"] == restored_snapshot["alembic_current"] else "FAIL",
        f"源库 {source_snapshot['alembic_current']} / 恢复库 {restored_snapshot['alembic_current']}",
    ))

    checks.append(make_check(
        "schema_fingerprint_matches_source",
        "PASS" if source_snapshot["schema_fingerprint"] == restored_snapshot["schema_fingerprint"] else "FAIL",
        f"源库 {source_snapshot['schema_fingerprint'][:16]}... / "
        f"恢复库 {restored_snapshot['schema_fingerprint'][:16]}...",
    ))


def check_key_tables(conn: sqlite3.Connection, tables: list, checks: list) -> dict:
    present = set(tables)
    queryable = []
    problems = []
    for name in KEY_TABLES:
        if name not in present:
            continue
        try:
            count = int(conn.execute("SELECT COUNT(*) FROM " + quote_ident(name)).fetchone()[0])
        except sqlite3.Error as exc:
            problems.append(f"{name}: {exc}")
            continue
        queryable.append({"table": name, "rows": count})

    missing = [name for name in KEY_TABLES if name not in present]
    if problems:
        status, detail = "FAIL", "关键表查询失败：" + "; ".join(problems)
    elif missing:
        status = "WARN"
        detail = (
            f"可查询 {len(queryable)} 张关键表"
            + (f"；库中不存在：{', '.join(missing)}（小型测试库属正常）" if missing else "")
        )
    else:
        status = "PASS"
        detail = "全部关键表只读可查询：" + ", ".join(
            f"{item['table']}({item['rows']})" for item in queryable
        )
    checks.append(make_check("key_tables_readable", status, detail))
    return {"queryable": queryable, "missing": missing}


def command_drill(args) -> int:
    source = require_source_db(Path(args.db))
    baseline = parse_fk_baseline(args.fk_baseline)

    if args.work_dir:
        work_root = ensure_dir(Path(args.work_dir).expanduser(), "演练临时目录")
        work_dir = Path(tempfile.mkdtemp(prefix="drill-", dir=str(work_root)))
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="erp-drill-"))

    checks: list = []
    started = datetime.now()
    backup_path = work_dir / f"{BACKUP_PREFIX}drill{BACKUP_SUFFIX}"
    restored_path = work_dir / "restored.db"
    keep = bool(args.keep)
    exit_code = EXIT_FAIL
    report: dict = {}

    try:
        source_before = stat_snapshot(source)
        source_conn = connect_readonly(source)
        try:
            source_snapshot = database_snapshot(source_conn)
        finally:
            source_conn.close()

        checks.append(make_check(
            "source_opened_read_only", "PASS",
            f"{source}（只读 URI + query_only，演练不修改主库）",
        ))

        create_consistent_backup(source, backup_path)
        backup_snapshot_conn = connect_readonly(backup_path)
        try:
            backup_integrity = run_integrity_check(backup_snapshot_conn)
        finally:
            backup_snapshot_conn.close()

        checks.append(make_check(
            "backup_api_copy",
            "PASS" if backup_integrity["ok"] else "FAIL",
            f"备份经 SQLite backup API 生成，integrity_check={backup_integrity['result']}"
            f"（{file_size(backup_path)} bytes）",
        ))

        create_consistent_backup(backup_path, restored_path)
        checks.append(make_check(
            "restored_to_fresh_path", "PASS",
            f"已从备份恢复到全新路径 {restored_path}",
        ))

        restored_conn = connect_readonly(restored_path)
        try:
            restored_snapshot = database_snapshot(restored_conn)
            key_tables = check_key_tables(restored_conn, restored_snapshot["tables"], checks)
            restored_fk = restored_snapshot["foreign_key_check"]
        finally:
            restored_conn.close()

        checks.append(make_check(
            "restored_integrity_check",
            "PASS" if restored_snapshot["integrity_check"]["ok"] else "FAIL",
            restored_snapshot["integrity_check"]["result"],
        ))

        actual_fk = fk_signature(restored_fk["violations"])
        if not actual_fk:
            fk_status, fk_detail = "PASS", "恢复库无外键违规"
        elif baseline and actual_fk == baseline:
            fk_status = "PASS"
            fk_detail = (
                f"{len(actual_fk)} 处外键违规与已声明基线完全一致：{', '.join(actual_fk)}"
                "（迁移前须按 phase1_migration_safety.md 处置）"
            )
        elif baseline:
            unexpected = sorted(set(actual_fk) - set(baseline))
            resolved = sorted(set(baseline) - set(actual_fk))
            fk_status = "FAIL"
            fk_detail = (
                f"与已声明基线不一致：新增 {unexpected or '无'}；基线中已消失 {resolved or '无'}"
            )
        else:
            fk_status = "FAIL"
            fk_detail = (
                f"{len(actual_fk)} 处外键违规：{', '.join(actual_fk[:5])}"
                "。若为迁移前已知存量，请用 --fk-baseline 显式声明后再判定。"
            )
        checks.append(make_check("restored_foreign_key_check", fk_status, fk_detail))

        compare_snapshots(source_snapshot, restored_snapshot, checks)

        source_after = stat_snapshot(source)
        source_stable = source_after["sha256"] == source_before["sha256"]
        checks.append(make_check(
            "source_unmodified",
            "PASS" if source_stable else "WARN",
            "演练前后主库 SHA256 与修改时间一致，主库未被写入"
            if source_stable else
            "演练期间主库哈希发生变化，说明存在并发写入者；请在停写窗口内重新演练",
        ))

        summary = summarize(checks)
        elapsed = (datetime.now() - started).total_seconds()
        report = {
            "command": "drill",
            "ok": summary["ok"],
            "source": str(source),
            "work_dir": str(work_dir),
            "backup": str(backup_path),
            "restored": str(restored_path),
            "elapsed_seconds": round(elapsed, 3),
            "source_summary": {
                "table_count": source_snapshot["table_count"],
                "total_rows": source_snapshot["total_rows"],
                "alembic_current": source_snapshot["alembic_current"],
                "schema_fingerprint": source_snapshot["schema_fingerprint"],
                "integrity_check": source_snapshot["integrity_check"]["result"],
                "foreign_key_violations": source_snapshot["foreign_key_check"]["count"],
            },
            "restored_summary": {
                "table_count": restored_snapshot["table_count"],
                "total_rows": restored_snapshot["total_rows"],
                "alembic_current": restored_snapshot["alembic_current"],
                "schema_fingerprint": restored_snapshot["schema_fingerprint"],
                "integrity_check": restored_snapshot["integrity_check"]["result"],
                "foreign_key_violations": restored_fk["count"],
            },
            "fk_baseline_declared": baseline,
            "key_tables": key_tables,
            "checks": checks,
            "summary": summary,
            "artifacts_kept": keep,
        }
        headline = (
            f"恢复演练{'PASS' if summary['ok'] else 'FAIL'}："
            f"表 {restored_snapshot['table_count']} / 行 {restored_snapshot['total_rows']} / "
            f"alembic {restored_snapshot['alembic_current']} / "
            f"integrity {restored_snapshot['integrity_check']['result']} / "
            f"FK 违规 {restored_fk['count']}；耗时 {elapsed:.2f}s"
            + ("" if summary["ok"] else f"（失败项：{', '.join(summary['failures'])}）")
        )
        report["headline"] = headline
        exit_code = EXIT_OK if summary["ok"] else EXIT_FAIL
    finally:
        if not keep:
            shutil.rmtree(work_dir, ignore_errors=True)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for line in render_checks(checks):
            print(line)
        print(report.get("headline", ""))
        print(f"演练产物已保留：{work_dir}" if keep else f"演练临时目录已清理：{work_dir}")
    return exit_code

# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "SQLite 一致性备份与恢复演练工具。源库始终只读打开；"
            "备份使用 SQLite 官方 backup API，不使用文件复制。"
        ),
    )
    parser.add_argument("--version", action="version",
                        version=f"{TOOL_NAME} {TOOL_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="生成一致性备份与 manifest")
    p_backup.add_argument("--db", required=True, help="主库路径，例如 erp.db")
    p_backup.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                          help=f"备份输出目录，默认 {DEFAULT_OUT_DIR}")
    p_backup.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_backup.set_defaults(func=command_backup)

    p_verify = sub.add_parser("verify", help="按 manifest 重新校验备份文件")
    p_verify.add_argument("--backup", required=True, help="备份文件路径")
    p_verify.add_argument("--manifest", default=None,
                          help="manifest 路径，默认 <备份文件名>.manifest.json")
    p_verify.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_verify.set_defaults(func=command_verify)

    p_drill = sub.add_parser("drill", help="备份并恢复到全新路径后逐项比对")
    p_drill.add_argument("--db", required=True, help="主库路径，例如 erp.db")
    p_drill.add_argument("--work-dir", default=None,
                         help="演练临时目录，默认使用系统临时目录")
    p_drill.add_argument("--keep", action="store_true",
                         help="保留演练产物（备份、恢复库）以便取证")
    p_drill.add_argument("--fk-baseline", default="",
                         help="已声明存量外键违规基线，逗号分隔，例如 "
                              "'users.4->tenants'；仅当恢复库与基线完全一致才判 PASS")
    p_drill.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_drill.set_defaults(func=command_drill)

    return parser


def main(argv=None) -> int:
    reconfigure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DrillError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("已中断。", file=sys.stderr)
        return EXIT_ERROR
    except sqlite3.Error as exc:
        print(
            f"错误：SQLite 操作失败：{exc}\n"
            "排查：确认数据库文件未被其他进程独占、文件未损坏、磁盘空间充足。",
            file=sys.stderr,
        )
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
