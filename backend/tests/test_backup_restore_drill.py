"""P1-04 SQLite 备份与恢复演练工具测试。

仅使用标准库与 pytest 的 tmp_path，通过 subprocess 调用真实 CLI，
从而覆盖与生产一致的退出码语义（0 通过 / 1 校验失败 / 2 运行错误）。

测试库为自建小型库，不触碰 backend/erp.db 与 backend/test_erp.db。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backup_restore_drill.py"
ALEMBIC_REVISION = "20260922_01"
KEY_TABLES = ("tenants", "users", "orders", "products", "shops", "settings")
SENTINEL_USERNAME = "sentinel-user-should-never-be-printed"

SCHEMA = """
CREATE TABLE tenants(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE users(
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id),
    username TEXT NOT NULL
);
CREATE TABLE orders(
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    amount REAL NOT NULL
);
CREATE TABLE products(id INTEGER PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE shops(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE settings(id INTEGER PRIMARY KEY, key TEXT, value TEXT);
CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
"""


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_database(path: Path, *, orphan_user: bool = False) -> Path:
    """构造小型 SQLite 库：含外键、alembic_version 与全部关键表。"""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO tenants(id, name) VALUES (1, 'tenant-a'), (2, 'tenant-b')"
        )
        conn.execute(
            "INSERT INTO users(id, tenant_id, username) VALUES (1, 1, ?)",
            (SENTINEL_USERNAME,),
        )
        conn.execute("INSERT INTO users(id, tenant_id, username) VALUES (2, 2, 'user-b')")
        if orphan_user:
            conn.execute("INSERT INTO users(id, tenant_id, username) VALUES (4, 0, 'user-orphan')")
        conn.execute("INSERT INTO orders(id, user_id, amount) VALUES (1, 1, 19.5)")
        conn.execute("INSERT INTO products(id, title) VALUES (1, 'product-a')")
        conn.execute("INSERT INTO shops(id, name) VALUES (1, 'shop-a')")
        conn.execute("INSERT INTO settings(id, key, value) VALUES (1, 'k', 'v')")
        conn.execute("INSERT INTO alembic_version(version_num) VALUES (?)", (ALEMBIC_REVISION,))
        conn.commit()
    finally:
        conn.close()
    return path


def backup_once(db: Path, out_dir: Path) -> subprocess.CompletedProcess:
    return run_cli("backup", "--db", str(db), "--out-dir", str(out_dir), "--json")

def test_backup_creates_manifest_with_complete_fields(tmp_path):
    db = create_database(tmp_path / "erp.db")
    out_dir = tmp_path / "backups"

    result = backup_once(db, out_dir)
    assert result.returncode == 0, result.stderr

    backups = sorted(out_dir.glob("erp-*.db"))
    assert len(backups) == 1
    backup = backups[0]
    assert backup.name.startswith("erp-")
    assert backup.suffix == ".db"

    manifest_file = backup.with_name(backup.name + ".manifest.json")
    assert manifest_file.exists()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    # 顶层结构
    for key in (
        "manifest_version",
        "tool",
        "created_at",
        "source",
        "backup",
        "database",
        "integrity_check",
        "foreign_key_check",
    ):
        assert key in manifest, f"manifest 缺少字段 {key}"

    # 工具版本
    assert manifest["tool"]["name"] == "backup_restore_drill"
    assert manifest["tool"]["version"]
    assert manifest["tool"]["sqlite"]

    # 源库信息
    assert Path(manifest["source"]["path"]) == db.resolve()
    assert manifest["source"]["size_bytes"] == db.stat().st_size
    assert manifest["source"]["sha256"] == sha256_file(db)
    assert manifest["source"]["changed_during_backup"] is False

    # 备份信息
    assert manifest["backup"]["size_bytes"] == backup.stat().st_size
    assert manifest["backup"]["sha256"] == sha256_file(backup)

    # 数据库统计
    assert manifest["database"]["table_count"] == 7
    assert manifest["database"]["total_rows"] == 9
    assert manifest["database"]["alembic_current"] == ALEMBIC_REVISION
    assert manifest["database"]["schema_fingerprint"]

    # 检查结果
    assert manifest["integrity_check"]["ok"] is True
    assert manifest["integrity_check"]["result"] == "ok"
    assert manifest["foreign_key_check"]["ok"] is True
    assert manifest["foreign_key_check"]["count"] == 0


def test_backup_manifest_excludes_pii(tmp_path):
    db = create_database(tmp_path / "erp.db")
    out_dir = tmp_path / "backups"
    assert backup_once(db, out_dir).returncode == 0

    backup = sorted(out_dir.glob("erp-*.db"))[0]
    text = backup.with_name(backup.name + ".manifest.json").read_text(encoding="utf-8")
    lowered = text.lower()

    assert SENTINEL_USERNAME not in text
    for banned in ("password_hash", "token", "secret"):
        assert banned not in lowered, f"manifest 不应出现敏感字段名 {banned}"


def test_backup_does_not_modify_source_database(tmp_path):
    db = create_database(tmp_path / "erp.db")
    before_hash = sha256_file(db)
    before_mtime = db.stat().st_mtime_ns
    before_size = db.stat().st_size

    assert backup_once(db, tmp_path / "backups").returncode == 0

    assert sha256_file(db) == before_hash
    assert db.stat().st_mtime_ns == before_mtime
    assert db.stat().st_size == before_size
    for suffix in ("-wal", "-shm", "-journal"):
        assert not Path(str(db) + suffix).exists(), f"源库旁出现了 {suffix} 文件"


def test_backup_never_overwrites_existing_files(tmp_path):
    db = create_database(tmp_path / "erp.db")
    out_dir = tmp_path / "backups"

    first = backup_once(db, out_dir)
    assert first.returncode == 0
    first_backup = sorted(out_dir.glob("erp-*.db"))[0]
    first_hash = sha256_file(first_backup)

    second = backup_once(db, out_dir)
    assert second.returncode == 0

    backups = sorted(out_dir.glob("erp-*.db"))
    assert len(backups) == 2, "第二次备份必须新建文件而不是覆盖"
    assert first_backup in backups
    assert sha256_file(first_backup) == first_hash, "已有备份内容被改写"

    # 两个备份都应有各自的 manifest
    for backup in backups:
        assert backup.with_name(backup.name + ".manifest.json").exists()

def test_verify_passes_for_intact_backup(tmp_path):
    db = create_database(tmp_path / "erp.db")
    out_dir = tmp_path / "backups"
    assert backup_once(db, out_dir).returncode == 0
    backup = sorted(out_dir.glob("erp-*.db"))[0]

    result = run_cli("verify", "--backup", str(backup), "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["summary"]["failed"] == 0
    assert payload["summary"]["passed"] > 0


def test_verify_fails_with_nonzero_exit_when_backup_tampered(tmp_path):
    db = create_database(tmp_path / "erp.db")
    out_dir = tmp_path / "backups"
    assert backup_once(db, out_dir).returncode == 0

    backup = sorted(out_dir.glob("erp-*.db"))[0]
    original_hash = sha256_file(backup)

    # 篡改内容但保持文件长度不变，确保不是靠 size 差异被发现
    payload = bytearray(backup.read_bytes())
    for index in range(4000, 4020):
        payload[index] ^= 0xFF
    backup.write_bytes(bytes(payload))
    assert backup.stat().st_size == len(payload)
    assert sha256_file(backup) != original_hash

    result = run_cli("verify", "--backup", str(backup), "--json")
    assert result.returncode != 0, "篡改后的备份必须以非零退出码失败"
    assert result.returncode == 1

    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    failed_names = {check["name"] for check in payload["checks"] if check["status"] == "FAIL"}
    assert "sha256" in failed_names


def test_verify_fails_when_row_counts_disagree_with_manifest(tmp_path):
    db = create_database(tmp_path / "erp.db")
    out_dir = tmp_path / "backups"
    assert backup_once(db, out_dir).returncode == 0

    backup = sorted(out_dir.glob("erp-*.db"))[0]
    manifest_file = backup.with_name(backup.name + ".manifest.json")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["database"]["total_rows"] += 1
    manifest["backup"]["sha256"] = sha256_file(backup)
    manifest["backup"]["size_bytes"] = backup.stat().st_size
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = run_cli("verify", "--backup", str(backup), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    failed_names = {check["name"] for check in payload["checks"] if check["status"] == "FAIL"}
    assert "total_rows" in failed_names


def test_verify_errors_when_manifest_missing(tmp_path):
    db = create_database(tmp_path / "erp.db")
    out_dir = tmp_path / "backups"
    assert backup_once(db, out_dir).returncode == 0
    backup = sorted(out_dir.glob("erp-*.db"))[0]
    backup.with_name(backup.name + ".manifest.json").unlink()

    result = run_cli("verify", "--backup", str(backup))
    assert result.returncode == 2
    assert "manifest" in (result.stdout + result.stderr).lower()

def test_drill_passes_for_clean_database(tmp_path):
    db = create_database(tmp_path / "erp.db")
    work_dir = tmp_path / "work"

    result = run_cli("drill", "--db", str(db), "--work-dir", str(work_dir), "--json")
    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["summary"]["failed"] == 0

    # 恢复库与源库逐项一致
    assert payload["restored_summary"]["table_count"] == payload["source_summary"]["table_count"] == 7
    assert payload["restored_summary"]["total_rows"] == payload["source_summary"]["total_rows"] == 9
    assert payload["restored_summary"]["alembic_current"] == ALEMBIC_REVISION
    assert payload["restored_summary"]["integrity_check"] == "ok"
    assert payload["restored_summary"]["foreign_key_violations"] == 0
    assert (
        payload["restored_summary"]["schema_fingerprint"]
        == payload["source_summary"]["schema_fingerprint"]
    )

    # 关键表可查询
    readable = {item["table"] for item in payload["key_tables"]["queryable"]}
    assert set(KEY_TABLES) <= readable

    # 默认清理临时目录
    assert not Path(payload["work_dir"]).exists()
    assert payload["artifacts_kept"] is False


def test_drill_fails_for_database_with_foreign_key_violation(tmp_path):
    db = create_database(tmp_path / "erp.db", orphan_user=True)
    work_dir = tmp_path / "work"

    # 默认严格模式：存量外键违规必须判 FAIL
    result = run_cli("drill", "--db", str(db), "--work-dir", str(work_dir), "--json")
    assert result.returncode == 1, "含外键违规的库必须演练失败"

    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    failed_names = {check["name"] for check in payload["checks"] if check["status"] == "FAIL"}
    assert "restored_foreign_key_check" in failed_names
    assert payload["restored_summary"]["foreign_key_violations"] == 1

    # 显式声明基线后才允许通过，且必须与基线完全一致
    baseline = run_cli(
        "drill", "--db", str(db), "--work-dir", str(work_dir),
        "--fk-baseline", "users.4->tenants", "--json",
    )
    assert baseline.returncode == 0, baseline.stderr
    assert json.loads(baseline.stdout)["ok"] is True

    # 基线不匹配仍然失败
    wrong = run_cli(
        "drill", "--db", str(db), "--work-dir", str(work_dir),
        "--fk-baseline", "orders.9->users", "--json",
    )
    assert wrong.returncode == 1


def test_drill_keep_retains_artifacts(tmp_path):
    db = create_database(tmp_path / "erp.db")
    work_dir = tmp_path / "work"

    result = run_cli("drill", "--db", str(db), "--work-dir", str(work_dir), "--keep", "--json")
    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["artifacts_kept"] is True
    assert Path(payload["backup"]).exists()
    assert Path(payload["restored"]).exists()
    assert Path(payload["restored"]).stat().st_size > 0


def test_drill_does_not_modify_source_database(tmp_path):
    db = create_database(tmp_path / "erp.db")
    before_hash = sha256_file(db)
    before_mtime = db.stat().st_mtime_ns

    result = run_cli("drill", "--db", str(db), "--work-dir", str(tmp_path / "work"))
    assert result.returncode == 0, result.stderr

    assert sha256_file(db) == before_hash
    assert db.stat().st_mtime_ns == before_mtime

def test_drill_rejects_missing_database_with_actionable_error(tmp_path):
    result = run_cli("drill", "--db", str(tmp_path / "nope.db"), "--work-dir", str(tmp_path / "work"))
    assert result.returncode == 2
    assert "不存在" in result.stderr


def test_backup_rejects_non_sqlite_file(tmp_path):
    bogus = tmp_path / "not-a-db.txt"
    bogus.write_text("this is not a sqlite database", encoding="utf-8")

    result = run_cli("backup", "--db", str(bogus), "--out-dir", str(tmp_path / "backups"))
    assert result.returncode == 2
    assert "SQLite" in result.stderr


def test_backup_creates_missing_out_dir(tmp_path):
    db = create_database(tmp_path / "erp.db")
    nested = tmp_path / "deep" / "nested" / "backups"

    result = backup_once(db, nested)
    assert result.returncode == 0, result.stderr
    assert nested.is_dir()
    assert len(list(nested.glob("erp-*.db"))) == 1


def test_cli_reports_tool_version(tmp_path):
    result = run_cli("--version")
    assert result.returncode == 0
    assert "backup_restore_drill" in result.stdout
