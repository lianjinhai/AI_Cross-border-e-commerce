"""P1-01 Migration Preflight 只读检查器的回归测试。

约束：
- 全部使用 tmp_path 临时库，绝不接触 backend/erp.db；
- 不 import app.db / app.config，避免创建指向主库的 engine；
- 通过 subprocess 调用脚本，断言基于退出码与报告结构。
"""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BACKEND_DIR / "scripts" / "migration_preflight.py"

CLEAN_SCHEMA = """
CREATE TABLE tenants (
    id INTEGER PRIMARY KEY,
    name VARCHAR(128) NOT NULL
);
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id),
    username VARCHAR(64) NOT NULL,
    role VARCHAR(32)
);
CREATE TABLE shops (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER,
    platform VARCHAR(32),
    role VARCHAR(16)
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER,
    shop_id INTEGER REFERENCES shops(id),
    source VARCHAR(16)
);
"""

EXPECTED_CHECK_KEYS = [
    "schema_fingerprint",
    "alembic_ledger",
    "row_count_manifest",
    "foreign_key_check",
    "tenant_zero",
    "orphan_tenants",
    "cross_tenant_refs",
    "role_mapping_candidates",
    "setting_scope_candidates",
    "shop_role_audit",
    "order_source_audit",
    "user_reference_inventory",
]


def test_planned_upgrade_ledger_requires_current_head_and_stays_readonly(tmp_path):
    """契约守护：旧库需要显式计划，不能将新head账本漂移静默放行。

    计划目标必须是「唯一代码 head」且数据库 current 位于其线性祖先链上。追加迁移后
    这一对会随 head 前移更新（D56 为 18→19，D58 为 19→20，D59 为 20→21）。
    """
    db = _build_db(tmp_path, alembic_rev="20261011_22")
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    versions = BACKEND_DIR / "migrations" / "versions"
    result = _run(db, versions, "--planned-upgrade", "20261011_23")
    assert result.returncode == 0
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    result = _run(db, versions)
    assert result.returncode == 2


def _write_versions(tmp_path: Path, revision: str, down_revision=None) -> Path:
    """在临时目录写一个最小 Alembic revision 链。"""
    versions = tmp_path / "versions"
    versions.mkdir(exist_ok=True)
    down = "None" if down_revision is None else repr(down_revision)
    (versions / ("%s_base.py" % revision)).write_text(
        "revision = %r\ndown_revision = %s\n" % (revision, down), encoding="utf-8")
    return versions


def _connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.executescript(CLEAN_SCHEMA)
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    return con


def _build_db(tmp_path: Path, alembic_rev="test_01") -> Path:
    """构造最小干净库：1 租户、1 用户、1 店铺、1 订单，无违规。"""
    db = tmp_path / "tmp_erp.db"
    con = _connect(db)
    con.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (alembic_rev,))
    con.execute("INSERT INTO tenants (id, name) VALUES (1, 'tenant-a')")
    con.execute("INSERT INTO users (id, tenant_id, username, role) VALUES (1, 1, 'u1', 'admin')")
    con.execute("INSERT INTO shops (id, tenant_id, platform, role) VALUES (1, 1, 'shopee', 'sales')")
    con.execute("INSERT INTO orders (id, tenant_id, shop_id, source) VALUES (1, 1, 1, 'api')")
    con.commit()
    con.close()
    return db


def _run(db: Path, versions: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(db),
         "--versions-dir", str(versions), *extra],
        capture_output=True, text=True, encoding="utf-8", cwd=str(BACKEND_DIR))


def _report(result: subprocess.CompletedProcess) -> dict:
    return json.loads(result.stdout)


def _check(report: dict, key: str) -> dict:
    for item in report["checks"]:
        if item["key"] == key:
            return item
    raise AssertionError("缺少检查项：%s" % key)


def test_clean_database_passes_with_exit_code_zero(tmp_path):
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)

    result = _run(db, versions, "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(result)
    assert report["summary"]["p0_fail"] == 0
    p0 = [c for c in report["checks"] if c["severity"] == "P0"]
    assert p0, "报告应包含 P0 检查项"
    failing = [c["key"] for c in p0 if c["status"] != "PASS"]
    assert failing == [], "干净库不应有 P0 失败：%s" % failing


def test_alembic_ledger_mismatch_fails_with_exit_code_two(tmp_path):
    versions = _write_versions(tmp_path, "test_02")
    db = _build_db(tmp_path, alembic_rev="test_01")

    result = _run(db, versions, "--json")

    assert result.returncode == 2
    check = _check(_report(result), "alembic_ledger")
    assert check["status"] == "FAIL"
    assert check["severity"] == "P0"
    assert check["evidence"]["db_current"] == ["test_01"]
    assert check["evidence"]["code_heads"] == ["test_02"]


def test_explicit_direct_successor_upgrade_passes(tmp_path):
    versions = _write_versions(tmp_path, "test_01")
    (versions / "test_02_next.py").write_text(
        "revision = 'test_02'\ndown_revision = 'test_01'\n", encoding="utf-8")
    db = _build_db(tmp_path)

    result = _run(db, versions, "--planned-upgrade", "test_02", "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(result)
    assert report["summary"]["p0_fail"] == 0
    assert _check(report, "alembic_ledger")["status"] == "PASS"


def test_planned_upgrade_requires_head_and_linear_ancestry(tmp_path):
    """契约：目标必须是最新 head，且数据库 current 必须是它的线性祖先。

    落后多版（test_01 → test_02 → test_03）时允许沿链一次声明到 head；但目标不是
    head、或 current 不在 head 的祖先链上（跨链）一律拒绝，防漂移内核不变。
    """
    versions = _write_versions(tmp_path, "test_01")
    (versions / "test_02_next.py").write_text(
        "revision = 'test_02'\ndown_revision = 'test_01'\n", encoding="utf-8")
    (versions / "test_03_next.py").write_text(
        "revision = 'test_03'\ndown_revision = 'test_02'\n", encoding="utf-8")
    db = _build_db(tmp_path)

    # 目标不是唯一 head（test_02 只是中间版）、或目标不存在 → 拒绝
    for target in ("test_02", "unknown"):
        result = _run(db, versions, "--planned-upgrade", target, "--json")
        assert result.returncode == 2, target
        assert _check(_report(result), "alembic_ledger")["status"] == "FAIL"

    # 目标 = 唯一 head 且 current 在其线性祖先链上 → 允许（落后两版可一次声明到 head）
    ok = _run(db, versions, "--planned-upgrade", "test_03", "--json")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    ledger = _check(_report(ok), "alembic_ledger")
    assert ledger["status"] == "PASS"
    assert ledger["evidence"]["planned_path"] == ["test_02", "test_01"]

    # current 不在 head 的祖先链上（跨链 revision）→ 拒绝
    other = tmp_path / "other"
    other.mkdir()
    orphan = _build_db(other, alembic_rev="test_09")
    bad = _run(orphan, versions, "--planned-upgrade", "test_03", "--json")
    assert bad.returncode == 2
    assert _check(_report(bad), "alembic_ledger")["status"] == "FAIL"


def test_planned_upgrade_does_not_hide_other_p0_failures(tmp_path):
    versions = _write_versions(tmp_path, "test_01")
    (versions / "test_02_next.py").write_text(
        "revision = 'test_02'\ndown_revision = 'test_01'\n", encoding="utf-8")
    db = _build_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO orders (id, tenant_id, shop_id, source) "
                "VALUES (2, 0, NULL, 'seed')")
    con.commit()
    con.close()

    result = _run(db, versions, "--planned-upgrade", "test_02", "--json")

    assert result.returncode == 2
    report = _report(result)
    assert _check(report, "alembic_ledger")["status"] == "PASS"
    assert _check(report, "tenant_zero")["status"] == "FAIL"


def test_tenant_zero_business_row_fails_with_exit_code_two(tmp_path):
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO orders (id, tenant_id, shop_id, source) VALUES (2, 0, NULL, 'seed')")
    con.commit()
    con.close()

    result = _run(db, versions, "--json")

    assert result.returncode == 2
    check = _check(_report(result), "tenant_zero")
    assert check["status"] == "FAIL"
    assert check["severity"] == "P0"
    assert check["evidence"]["per_table"]["orders"] == 1


def test_platform_identity_with_null_tenant_keeps_all_p0_checks_passing(tmp_path):
    """迁移目标态：平台身份 tenant_id 为 NULL，不应触发任何 P0 失败。"""
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO users (id, tenant_id, username, role) "
                "VALUES (2, NULL, 'root', 'superadmin')")
    con.commit()
    con.close()

    result = _run(db, versions, "--json")

    report = _report(result)
    check = _check(report, "tenant_zero")
    assert check["status"] == "PASS"
    assert check["evidence"]["zero_rows_business"] == 0
    assert _check(report, "orphan_tenants")["status"] == "PASS"
    assert report["summary"]["p0_fail"] == 0
    assert result.returncode == 0


def test_superadmin_tenant_zero_is_excluded_from_tenant_zero_but_still_orphan(tmp_path):
    """superadmin 不计入 tenant 0 业务行，但其 tenant_id=0 仍是待处理的孤儿引用。"""
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO users (id, tenant_id, username, role) "
                "VALUES (2, 0, 'root', 'superadmin')")
    con.commit()
    con.close()

    result = _run(db, versions, "--json")

    report = _report(result)
    check = _check(report, "tenant_zero")
    assert check["status"] == "PASS"
    assert check["evidence"]["zero_rows_business"] == 0
    assert check["evidence"]["excluded_rows"] == 1
    assert _check(report, "orphan_tenants")["status"] == "FAIL"
    assert result.returncode == 2


def test_foreign_key_violation_fails_with_exit_code_two(tmp_path):
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO orders (id, tenant_id, shop_id, source) VALUES (3, 1, 999, 'api')")
    con.commit()
    con.close()

    result = _run(db, versions, "--json")

    assert result.returncode == 2
    check = _check(_report(result), "foreign_key_check")
    assert check["status"] == "FAIL"
    assert check["severity"] == "P0"
    assert check["evidence"]["violation_count"] >= 1
    assert check["evidence"]["violations"][0]["table"] == "orders"


def test_json_report_structure_is_complete(tmp_path):
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)

    result = _run(db, versions, "--json")
    report = _report(result)

    assert set(report) >= {"generated_at", "db_path", "db_size_bytes",
                           "readonly", "summary", "checks"}
    assert report["readonly"] is True
    assert isinstance(report["db_size_bytes"], int) and report["db_size_bytes"] > 0
    assert Path(report["db_path"]) == db.resolve()
    assert set(report["summary"]) == {"p0_fail", "p1_warn", "pass"}
    assert [c["key"] for c in report["checks"]] == EXPECTED_CHECK_KEYS
    for check in report["checks"]:
        assert set(check) >= {"key", "title", "status", "severity", "evidence", "message"}
        assert check["status"] in ("PASS", "WARN", "FAIL")
        assert check["severity"] in ("P0", "P1")
        assert isinstance(check["evidence"], dict)
        assert isinstance(check["message"], str) and check["message"]


def test_preflight_never_modifies_database_file(tmp_path):
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)
    before = (db.stat().st_size, db.stat().st_mtime_ns,
              hashlib.sha256(db.read_bytes()).hexdigest())

    result = _run(db, versions)

    after = (db.stat().st_size, db.stat().st_mtime_ns,
             hashlib.sha256(db.read_bytes()).hexdigest())
    assert result.returncode == 0
    assert before == after, "只读巡检不得改动数据库文件"


def test_out_flag_writes_json_report_and_stdout_stays_human_readable(tmp_path):
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)
    out_file = tmp_path / "reports" / "preflight.json"

    result = _run(db, versions, "--out", str(out_file))

    assert result.returncode == 0
    assert "Migration Preflight (READ-ONLY)" in result.stdout
    written = json.loads(out_file.read_text(encoding="utf-8"))
    assert written["summary"]["p0_fail"] == 0
    assert [c["key"] for c in written["checks"]] == EXPECTED_CHECK_KEYS


def test_missing_database_returns_usage_error_code(tmp_path):
    versions = _write_versions(tmp_path, "test_01")

    result = _run(tmp_path / "not_here.db", versions)

    assert result.returncode == 3
    assert "preflight error" in result.stderr


def test_p1_warning_only_still_exits_zero(tmp_path):
    """仅 P1 警告时退出码为 0，但报告必须标注 WARN。"""
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO shops (id, tenant_id, platform, role) "
                "VALUES (2, 1, '1688', 'sales')")
    con.commit()
    con.close()

    result = _run(db, versions, "--json")

    report = _report(result)
    check = _check(report, "shop_role_audit")
    assert check["status"] == "WARN"
    assert check["severity"] == "P1"
    assert check["evidence"]["mismatch_count"] == 1
    assert report["summary"]["p0_fail"] == 0
    assert report["summary"]["p1_warn"] >= 1
    assert result.returncode == 0


def test_unknown_role_value_is_flagged_as_mapping_candidate(tmp_path):
    """不在 Phase 1 目标角色候选内的 role 取值必须被标出并给建议。"""
    versions = _write_versions(tmp_path, "test_01")
    db = _build_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO users (id, tenant_id, username, role) "
                "VALUES (5, 1, 'legacy-user', 'warehouse_keeper')")
    con.commit()
    con.close()

    result = _run(db, versions, "--json")

    report = _report(result)
    check = _check(report, "role_mapping_candidates")
    assert check["status"] == "WARN"
    assert check["severity"] == "P1"
    unmapped = {item["value"] for item in check["evidence"]["unmapped_values"]}
    assert "warehouse_keeper" in unmapped
    assert result.returncode == 0
