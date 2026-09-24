"""Revision A/B/C 迁移结构测试（不触碰主库，全部在 tmp_path 上验证）。

验证目标：
1. Revision A 建表幂等（重复 upgrade 不报错）；
2. Revision B 回填期望数量正确、可重复执行不增量；
3. Revision C 后 users.tenant_id 可空、superadmin 置 NULL、FK 违规归零；
4. 回填后 Context Service 的 MEMBERSHIP 分支探测为真；
5. 业务数据不被迁移修改。

实现方式：直接构造最小 schema（模拟 20260922_06 之后的状态），
再用 alembic 的 op 上下文执行 revision 的 upgrade 函数。
"""
import pathlib
import sqlite3

import pytest

_REVISIONS = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "versions"


def _read(path) -> sqlite3.Connection:
    """只读连接，用于断言（避免与 alembic 连接互相锁表）。"""
    return sqlite3.connect(f"file:{pathlib.Path(path).as_posix()}?mode=ro", uri=True)


def _minimal_db(path: pathlib.Path) -> sqlite3.Connection:
    """构造承载 Revision A/B/C 所需的最小库结构。"""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE tenants (
            id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL,
            plan VARCHAR(32) DEFAULT 'pro', status VARCHAR(16) DEFAULT 'active',
            license_until DATETIME, license_note VARCHAR(256) DEFAULT '',
            created_at DATETIME);
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            username VARCHAR(64) UNIQUE NOT NULL,
            password_hash VARCHAR(256) NOT NULL,
            display_name VARCHAR(64) DEFAULT '',
            role VARCHAR(16) DEFAULT 'operator',
            status VARCHAR(16) DEFAULT 'active',
            token_version INTEGER DEFAULT 0,
            created_at DATETIME);
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version VALUES ('20260922_06');

        INSERT INTO tenants (id, name) VALUES
            (1,'租户一'),(2,'租户二'),(3,'租户三');
        INSERT INTO users (id, tenant_id, username, password_hash, role) VALUES
            (1, 1, 'a-admin',   'x', 'admin'),
            (2, 1, 'a-ops',     'x', 'operator'),
            (3, 1, 'a-viewer',  'x', 'viewer'),
            (4, 0, 'root',      'x', 'superadmin'),
            (5, 2, 'b-admin',   'x', 'admin'),
            (6, 2, 'b-viewer',  'x', 'viewer'),
            (7, 3, 'c-admin',   'x', 'admin'),
            (8, 3, 'c-supplier','x', 'supplier');
    """)
    con.commit()
    return con


def _run_revision(db_path, module_name: str, func: str):
    """用 SQLAlchemy 连接执行某个 revision 的 upgrade/downgrade。

    Alembic 的 MigrationContext 需要 SQLAlchemy Connection（而非 sqlite3 连接），
    因此这里显式建立 engine/connection，执行后立即释放。
    """
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine

    spec = importlib.util.spec_from_file_location(
        module_name, _REVISIONS / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = create_engine(f"sqlite:///{pathlib.Path(db_path).as_posix()}")
    with engine.begin() as connection:
        ctx = MigrationContext.configure(connection)
        with Operations.context(ctx):
            getattr(module, func)()
    engine.dispose()
    return module


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "migration-test.db"
    con = _minimal_db(path)
    con.close()
    return path


def test_revision_a_creates_tables(db_path):
    con = _read(db_path)
    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for expected in ("workspace_profiles", "workspace_roles", "permissions",
                     "role_permissions", "workspace_memberships",
                     "membership_data_scopes"):
        assert expected in tables, f"Revision A 未创建 {expected}"
    # users 未被 Revision A 修改
    tenant_col = [r for r in con.execute("PRAGMA table_info(users)")
                  if r[1] == "tenant_id"][0]
    assert tenant_col[3] == 1, "Revision A 不应修改 users.tenant_id 的 NOT NULL"
    con.close()


def test_revision_a_is_idempotent(db_path):
    con = _read(db_path)
    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "workspace_memberships" in tables
    con.close()


def test_revision_b_backfills_expected_counts(db_path):
    con = _read(db_path)
    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    _run_revision(db_path, "20260923_08_workspace_identity_backfill", "upgrade")

    profiles = con.execute("SELECT COUNT(*) FROM workspace_profiles").fetchone()[0]
    assert profiles == 3, f"workspace_profiles 应为 3，实际 {profiles}"

    memberships = con.execute("SELECT COUNT(*) FROM workspace_memberships").fetchone()[0]
    assert memberships == 6, f"workspace_memberships 应为 6，实际 {memberships}"

    by_role = dict(con.execute(
        "SELECT role_key, COUNT(*) FROM workspace_memberships GROUP BY role_key"))
    assert by_role == {"OWNER": 3, "OPERATOR": 1, "READ_ONLY": 2}, by_role

    assert con.execute("SELECT COUNT(*) FROM workspace_memberships wm "
                       "JOIN users u ON u.id = wm.user_id "
                       "WHERE LOWER(u.role)='superadmin'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM workspace_memberships wm "
                       "JOIN users u ON u.id = wm.user_id "
                       "WHERE LOWER(u.role)='supplier'").fetchone()[0] == 0

    assert con.execute("SELECT COUNT(*) FROM permissions").fetchone()[0] >= 24
    assert con.execute("SELECT COUNT(*) FROM workspace_roles").fetchone()[0] >= 4
    con.close()


def test_revision_b_is_idempotent(db_path):
    con = _read(db_path)
    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    _run_revision(db_path, "20260923_08_workspace_identity_backfill", "upgrade")
    before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("workspace_profiles", "workspace_memberships",
                        "workspace_roles", "permissions", "role_permissions")}
    _run_revision(db_path, "20260923_08_workspace_identity_backfill", "upgrade")
    after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in before}
    assert before == after, f"重复执行产生增量：{before} → {after}"
    con.close()


def test_revision_c_makes_tenant_nullable_and_detaches_superadmin(db_path):
    con = _read(db_path)
    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    _run_revision(db_path, "20260923_08_workspace_identity_backfill", "upgrade")
    _run_revision(db_path, "20260923_09_users_nullable_workspace", "upgrade")

    tenant_col = [r for r in con.execute("PRAGMA table_info(users)")
                  if r[1] == "tenant_id"][0]
    assert tenant_col[3] == 0, "Revision C 后 users.tenant_id 应为 nullable"

    assert con.execute("SELECT COUNT(*) FROM users WHERE tenant_id IS NULL"
                       ).fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM users WHERE tenant_id = 0"
                       ).fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM users WHERE LOWER(role)='superadmin' "
                       "AND tenant_id IS NULL").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 8, \
        "Revision C 不得删除任何用户"
    con.close()


def test_revision_c_removes_fk_violation(db_path):
    con = _read(db_path)
    before = con.execute("PRAGMA foreign_key_check").fetchall()
    assert before, "构造的最小库应存在 users->tenants 的 FK 违规"

    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    _run_revision(db_path, "20260923_08_workspace_identity_backfill", "upgrade")
    _run_revision(db_path, "20260923_09_users_nullable_workspace", "upgrade")

    after = con.execute("PRAGMA foreign_key_check").fetchall()
    assert after == [], f"Revision C 后仍有 FK 违规：{after}"
    con.close()


def test_full_chain_preserves_business_rows(db_path):
    """迁移不得删除任何 tenants/users 行，也不得改变其 role。"""
    con = _read(db_path)
    users_before = con.execute(
        "SELECT id, username, role FROM users ORDER BY id").fetchall()
    tenants_before = con.execute("SELECT id, name FROM tenants ORDER BY id").fetchall()

    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    _run_revision(db_path, "20260923_08_workspace_identity_backfill", "upgrade")
    _run_revision(db_path, "20260923_09_users_nullable_workspace", "upgrade")

    users_after = con.execute(
        "SELECT id, username, role FROM users ORDER BY id").fetchall()
    tenants_after = con.execute("SELECT id, name FROM tenants ORDER BY id").fetchall()
    assert users_before == users_after, "用户行被修改"
    assert tenants_before == tenants_after, "租户行被修改"
    con.close()


def test_membership_branch_becomes_available(db_path, monkeypatch):
    """Revision B 之后，Context Service 的 MEMBERSHIP 探测应为真。"""
    con = _read(db_path)
    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    _run_revision(db_path, "20260923_08_workspace_identity_backfill", "upgrade")
    con.close()

    from sqlalchemy import create_engine, inspect
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    assert "workspace_memberships" in set(inspect(engine).get_table_names())
    engine.dispose()


def test_downgrade_restores_original_state(db_path):
    con = _read(db_path)
    _run_revision(db_path, "20260923_07_workspace_identity_expand", "upgrade")
    _run_revision(db_path, "20260923_08_workspace_identity_backfill", "upgrade")
    _run_revision(db_path, "20260923_09_users_nullable_workspace", "upgrade")
    _run_revision(db_path, "20260923_09_users_nullable_workspace", "downgrade")

    tenant_col = [r for r in con.execute("PRAGMA table_info(users)")
                  if r[1] == "tenant_id"][0]
    assert tenant_col[3] == 1, "downgrade 后 tenant_id 应恢复 NOT NULL"
    assert con.execute("SELECT COUNT(*) FROM users WHERE tenant_id IS NULL"
                       ).fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM users WHERE LOWER(role)='superadmin' "
                       "AND tenant_id = 0").fetchone()[0] == 1
    con.close()
