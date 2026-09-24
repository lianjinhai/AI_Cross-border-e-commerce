"""P1-08 认证双读测试：Membership 优先、legacy fallback 日志。

关键设计：本测试**不触碰主库**，也不依赖服务启动时建表。
它在 tmp_path 上构造一个"已执行 Revision A/B"的库，
通过 SQLAlchemy session 绑定该库来验证 MEMBERSHIP 分支真实生效。
"""
import pathlib
import sqlite3

import pytest

from app.services import workspace_context as wc

_REVISIONS = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "versions"


def _read(path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{pathlib.Path(path).as_posix()}?mode=ro", uri=True)


def _run_revision(db_path, module_name: str, func: str = "upgrade"):
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


@pytest.fixture()
def migrated_db(tmp_path):
    """构造含 Revision A/B 结构的库（与主库结构等价的最小集）。"""
    path = tmp_path / "dual-read.db"
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
        INSERT INTO tenants (id, name) VALUES (1,'租户一'),(2,'租户二');
        INSERT INTO users (id, tenant_id, username, password_hash, role, display_name)
        VALUES
            (1, 1, 'a-admin',   'x', 'admin',      'A 管理员'),
            (2, 1, 'a-ops',     'x', 'operator',   'A 运营'),
            (3, 1, 'a-viewer',  'x', 'viewer',     'A 只读'),
            (4, 0, 'root',      'x', 'superadmin', '平台服务商'),
            (5, 2, 'b-admin',   'x', 'admin',      'B 管理员');
    """)
    con.commit()
    con.close()

    _run_revision(path, "20260923_07_workspace_identity_expand")
    _run_revision(path, "20260923_08_workspace_identity_backfill")
    # Revision 15：新增 compliance:check 权限（合规员可发起检测）。
    # 必须在此执行——权限读取优先走表，不跑该迁移则表缺少新 key，
    # 与代码常量的一致性断言会失败（这正是本套测试要守护的漂移）。
    _run_revision(path, "20260924_15_compliance_check_permission")
    return path


@pytest.fixture()
def migrated_session(migrated_db):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{pathlib.Path(migrated_db).as_posix()}")
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as session:
        yield session
    engine.dispose()


def _user(session, username: str):
    from app.models import User

    user = session.query(User).filter(User.username == username).first()
    assert user is not None
    return user


def test_membership_table_detected_after_migration(migrated_session):
    assert wc.membership_table_available(migrated_session) is True


def test_membership_takes_priority_over_legacy(migrated_session):
    """表落地后必须走 MEMBERSHIP，而不是 LEGACY_FALLBACK。"""
    ctx = wc.resolve_workspace_context(migrated_session, _user(migrated_session, "a-admin"))
    assert ctx.source == wc.SOURCE_MEMBERSHIP
    assert ctx.membership_id is not None
    assert ctx.workspace_id == 1
    assert ctx.role == wc.ROLE_OWNER
    assert ctx.workspace_name == "租户一"
    assert ctx.workspace_kind == wc.WORKSPACE_KIND_ORGANIZATION


def test_membership_permissions_loaded_from_role_permissions_table(migrated_session):
    """权限应从 role_permissions 表读取（表已 seed），与代码常量一致。"""
    ctx = wc.resolve_workspace_context(migrated_session, _user(migrated_session, "a-viewer"))
    assert ctx.source == wc.SOURCE_MEMBERSHIP
    assert ctx.role == wc.ROLE_READ_ONLY
    assert ctx.permissions, "role_permissions 表应有 READ_ONLY 的权限行"
    assert all(p.endswith(":read") for p in ctx.permissions), sorted(ctx.permissions)
    assert ctx.permissions == wc.ROLE_PERMISSIONS[wc.ROLE_READ_ONLY]


def test_every_role_permissions_table_matches_code_constants(migrated_session):
    """`role_permissions` 表与代码常量必须逐角色一致。

    为什么需要：权限读取优先走表（`_permissions_from_db`），表与常量漂移时
    **表胜出**，代码里的 `ROLE_PERMISSIONS` 会变成误导性文档——审计以为改了
    常量就收紧了权限，实际线上仍按旧表放行。此前只有 READ_ONLY 一个角色
    被比对过，其余 5 个角色处于无守护状态。
    """
    from sqlalchemy import text

    rows = migrated_session.execute(
        text("SELECT role_key, permission_key FROM role_permissions")).all()
    table: dict[str, set[str]] = {}
    for role_key, permission_key in rows:
        table.setdefault(role_key, set()).add(permission_key)

    assert table, "role_permissions 表为空，回填迁移未生效"
    # 表内角色与迁移 `20260923_08` 的 ROLES 常量一致：只有这 4 个 workspace 角色。
    # `PLATFORM_ADMIN`（无业务 Workspace）与 `FACTORY_COLLABORATOR`（工厂协作，
    # 走独立的 FACTORY 分支、不落 Membership）**有意不 seed**——它们经
    # `_permissions_from_db() → None` 回退到代码常量。此断言把「有意缺席」
    # 与「意外漏行」区分开：一旦有人往表里加了这两个角色却与常量不一致，
    # 表会胜出并静默改变线上权限，必须在此被拦下。
    assert set(table) == {"OWNER", "OPERATOR", "READ_ONLY", "COMPLIANCE"}, sorted(table)
    for role_key in sorted(table):
        expected = set(wc.ROLE_PERMISSIONS[role_key])
        assert table[role_key] == expected, (
            f"{role_key} 表与代码常量不一致："
            f"表多出 {sorted(table[role_key] - expected)}，"
            f"表缺少 {sorted(expected - table[role_key])}")


def test_operator_membership_has_write_but_not_member_admin(migrated_session):
    ctx = wc.resolve_workspace_context(migrated_session, _user(migrated_session, "a-ops"))
    assert ctx.role == wc.ROLE_OPERATOR
    assert ctx.can_write() is True
    assert ctx.can_admin() is False


def test_permission_catalog_covers_every_code_permission(migrated_session):
    """`permissions` 目录表必须包含代码用到的每一个权限 key。

    为什么必须单独守护（真实缺陷已发生）：
      ``role_permissions.permission_key`` 有外键指向 ``permissions.key``
      （Revision 07 定义）。有人往代码常量加了新权限 ``compliance:check``，
      迁移只往 ``role_permissions`` 插映射、**忘了先插目录行**，在开启外键
      强制的库上直接 IntegrityError 导致迁移失败（实测复现）；即便迁移侥幸
      通过，``_permissions_from_db`` 读到的也是残缺集合，线上权限静默失效。

    判据：代码 ``ROLE_PERMISSIONS`` 里出现过的所有 key，目录表必须都有；
    反之目录表可以有多余 key（预留/历史），不算漂移。
    """
    from sqlalchemy import text

    catalog = {r[0] for r in migrated_session.execute(
        text("SELECT key FROM permissions")).all()}
    assert catalog, "permissions 表为空，回填迁移未生效"
    code_keys: set[str] = set()
    for perms in wc.ROLE_PERMISSIONS.values():
        code_keys |= set(perms)
    missing = sorted(code_keys - catalog)
    assert not missing, (
        f"代码使用但 permissions 目录表缺失的权限 key：{missing}。"
        "新增权限必须同时补目录行与 role_permissions 映射（否则外键失败或权限静默失效）")


def test_compliance_check_granted_to_declared_roles(migrated_session):
    """`compliance:check` 必须授予 OWNER / OPERATOR / COMPLIANCE 三个角色。

    为什么单独钉死这一个权限：``/api/compliance/check`` 端点的文档与 legacy 兜底
    角色都声明「OWNER/OPERATOR/COMPLIANCE 拥有」，但实现曾漏掉 OPERATOR——
    三处声明不一致时，MEMBERSHIP 路径（生产真实路径）下运营发起合规检测会被
    403，而 legacy 路径却放行，形成"测试环境能过、生产环境被拦"的隐性缺口。
    """
    from sqlalchemy import text

    granted = {r[0] for r in migrated_session.execute(
        text("SELECT role_key FROM role_permissions WHERE permission_key = :k"),
        {"k": "compliance:check"}).all()}
    assert granted == {"OWNER", "OPERATOR", "COMPLIANCE"}, sorted(granted)
    # 与代码常量交叉验证（表优先，两者必须一致）
    for role_key in granted:
        assert "compliance:check" in wc.ROLE_PERMISSIONS[role_key], role_key


def test_superadmin_still_platform_identity_after_migration(migrated_session):
    """superadmin 不回填 Membership，必须仍为 PLATFORM。"""
    ctx = wc.resolve_workspace_context(migrated_session, _user(migrated_session, "root"))
    assert ctx.source == wc.SOURCE_PLATFORM
    assert ctx.workspace_id is None
    assert ctx.membership_id is None
    assert ctx.permissions == frozenset({"platform:admin"})


def test_membership_workspace_matches_legacy_tenant(migrated_session):
    """双读一致性：MEMBERSHIP 的 workspace_id 必须等于 legacy tenant_id。"""
    for username in ("a-admin", "a-ops", "a-viewer", "b-admin"):
        user = _user(migrated_session, username)
        ctx = wc.resolve_workspace_context(migrated_session, user)
        assert ctx.source == wc.SOURCE_MEMBERSHIP
        assert ctx.workspace_id == user.tenant_id, \
            f"{username}: membership workspace 与 legacy tenant 不一致"
        assert ctx.legacy_tenant_id == user.tenant_id


def test_membership_context_logs_without_pii(migrated_session, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="erp.workspace_context"):
        wc.resolve_workspace_context(migrated_session, _user(migrated_session, "a-admin"))
    joined = "\n".join(str(r.__dict__) for r in caplog.records)
    assert "membership" in joined
    assert "a-admin" not in joined, "日志不得包含 username"
    assert "password" not in joined.lower()


def test_fallback_still_used_when_membership_missing(migrated_session):
    """表存在但用户无 ACTIVE Membership 时，必须回退 LEGACY 并留日志。"""
    from app.models import User

    orphan = User(id=99, tenant_id=1, username="no-membership", password_hash="x",
                  display_name="无成员关系", role="viewer", status="active")
    migrated_session.add(orphan)
    migrated_session.commit()
    try:
        ctx = wc.resolve_workspace_context(migrated_session, orphan)
        assert ctx.source == wc.SOURCE_LEGACY
        assert ctx.membership_id is None
        assert ctx.role == wc.ROLE_READ_ONLY
        assert ctx.workspace_id == 1
    finally:
        migrated_session.delete(orphan)
        migrated_session.commit()


def test_suspended_membership_falls_back_to_legacy(migrated_session):
    """SUSPENDED 的 Membership 不得被当作 ACTIVE 使用。"""
    from sqlalchemy import text

    migrated_session.execute(text(
        "UPDATE workspace_memberships SET status='SUSPENDED' "
        "WHERE user_id = :uid"), {"uid": _user(migrated_session, "a-ops").id})
    migrated_session.commit()

    ctx = wc.resolve_workspace_context(migrated_session, _user(migrated_session, "a-ops"))
    assert ctx.source == wc.SOURCE_LEGACY, "SUSPENDED 不应被当作 ACTIVE"
    assert ctx.membership_id is None


def test_unknown_membership_role_downgrades(migrated_session):
    from sqlalchemy import text

    migrated_session.execute(text(
        "INSERT INTO workspace_roles (key, name, description, is_system) "
        "VALUES ('AUDITOR', '审计', '', 0)"))
    migrated_session.execute(text(
        "UPDATE workspace_memberships SET role_key='AUDITOR' "
        "WHERE user_id = :uid"), {"uid": _user(migrated_session, "a-viewer").id})
    migrated_session.commit()

    ctx = wc.resolve_workspace_context(migrated_session, _user(migrated_session, "a-viewer"))
    assert ctx.role == wc.ROLE_READ_ONLY, "未知 Membership 角色必须降级为 READ_ONLY"
