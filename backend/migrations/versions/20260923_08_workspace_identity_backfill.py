"""workspace identity seed and backfill (Revision B)

幂等：可重复执行不新增记录。执行后输出 inserted/skipped 计数。
设计依据：docs/phase1_migration_abc_design.md 第 2 节。

硬性断言失败时抛异常回滚（SQLite DDL 非事务，故断言在数据写入后立即执行）。
"""
from alembic import op
import sqlalchemy as sa

revision = "20260923_08"
down_revision = "20260923_07"
branch_labels = None
depends_on = None

# 契约冻结的角色 → 权限映射（docs/phase1_interfaces.md 第 4 节）
PERMISSIONS: list[tuple[str, str, str]] = [
    ("workspace:read", "workspace", "read"),
    ("workspace:write", "workspace", "write"),
    ("workspace:member:admin", "workspace", "admin"),
    ("product:read", "product", "read"),
    ("product:write", "product", "write"),
    ("supply:read", "supply", "read"),
    ("supply:write", "supply", "write"),
    ("listing:read", "listing", "read"),
    ("listing:write", "listing", "write"),
    ("order:read", "order", "read"),
    ("order:write", "order", "write"),
    ("finance:read", "finance", "read"),
    ("finance:write", "finance", "write"),
    ("purchase:read", "purchase", "read"),
    ("purchase:write", "purchase", "write"),
    ("settlement:read", "settlement", "read"),
    ("settlement:write", "settlement", "write"),
    ("refund:read", "refund", "read"),
    ("refund:write", "refund", "write"),
    ("compliance:read", "compliance", "read"),
    ("compliance:approve", "compliance", "approve"),
    ("ai:read", "ai", "read"),
    ("ai:write", "ai", "write"),
    ("platform:admin", "platform", "admin"),
]

ROLES: list[tuple[str, str, str]] = [
    ("OWNER", "所有者", "Workspace 所有者，可管理成员与配置"),
    ("OPERATOR", "运营", "日常经营操作，可写业务数据"),
    ("READ_ONLY", "只读", "只读观察"),
    ("COMPLIANCE", "合规审批", "合规审批，可写审批类动作"),
]

_READ_ALL = [k for k, _, _ in PERMISSIONS if k.endswith(":read")]
_WRITE_ALL = [k for k, _, _ in PERMISSIONS
              if k.endswith(":write") or k == "ai:write"]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "OWNER": sorted(set(_READ_ALL) | set(_WRITE_ALL)
                    | {"workspace:member:admin", "compliance:approve"}),
    "OPERATOR": sorted(set(_READ_ALL) | set(_WRITE_ALL)),
    "READ_ONLY": sorted(set(_READ_ALL)),
    "COMPLIANCE": ["compliance:read", "compliance:approve", "listing:read", "product:read"],
}

_LEGACY_ROLE_MAP = {
    "admin": "OWNER",
    "owner": "OWNER",
    "operator": "OPERATOR",
    "viewer": "READ_ONLY",
    "read_only": "READ_ONLY",
    "readonly": "READ_ONLY",
    "compliance_approver": "COMPLIANCE",
    "compliance": "COMPLIANCE",
}


def upgrade() -> None:
    bind = op.get_bind()
    counts = {"permissions_inserted": 0, "roles_inserted": 0,
              "role_permissions_inserted": 0, "profiles_inserted": 0,
              "memberships_inserted": 0, "skipped": 0}

    # ---- 1. Permission 目录（幂等）
    existing_perms = {r[0] for r in bind.execute(sa.text("SELECT key FROM permissions"))}
    for key, domain, action in PERMISSIONS:
        if key in existing_perms:
            counts["skipped"] += 1
            continue
        bind.execute(
            sa.text("INSERT INTO permissions (key, domain, action, description) "
                    "VALUES (:k, :d, :a, :desc)"),
            {"k": key, "d": domain, "a": action, "desc": ""})
        counts["permissions_inserted"] += 1

    # ---- 2. Role 模板（幂等）
    existing_roles = {r[0] for r in bind.execute(sa.text("SELECT key FROM workspace_roles"))}
    for key, name, description in ROLES:
        if key in existing_roles:
            counts["skipped"] += 1
            continue
        bind.execute(
            sa.text("INSERT INTO workspace_roles (key, name, description, is_system) "
                    "VALUES (:k, :n, :d, 1)"),
            {"k": key, "n": name, "d": description})
        counts["roles_inserted"] += 1

    # ---- 3. Role → Permission 映射（幂等）
    existing_rp = {(r[0], r[1]) for r in bind.execute(
        sa.text("SELECT role_key, permission_key FROM role_permissions"))}
    for role_key, perm_keys in ROLE_PERMISSIONS.items():
        for perm_key in perm_keys:
            if (role_key, perm_key) in existing_rp:
                counts["skipped"] += 1
                continue
            bind.execute(
                sa.text("INSERT INTO role_permissions (role_key, permission_key) "
                        "VALUES (:r, :p)"),
                {"r": role_key, "p": perm_key})
            counts["role_permissions_inserted"] += 1

    # ---- 4. WorkspaceProfile 回填（每个真实 tenant 一条）
    # tenants 表无 id=0 行；WHERE id <> 0 为防御性写法。
    profiles = bind.execute(sa.text(
        "SELECT id, name FROM tenants WHERE id <> 0 ORDER BY id")).fetchall()
    existing_profiles = {r[0] for r in bind.execute(
        sa.text("SELECT tenant_id FROM workspace_profiles"))}
    for tenant_id, name in profiles:
        if tenant_id in existing_profiles:
            counts["skipped"] += 1
            continue
        bind.execute(
            sa.text("INSERT INTO workspace_profiles "
                    "(tenant_id, name, kind, status, owner_user_id, created_at) "
                    "VALUES (:t, :n, 'ORGANIZATION', 'active', NULL, CURRENT_TIMESTAMP)"),
            {"t": tenant_id, "n": name})
        counts["profiles_inserted"] += 1

    # ---- 5. Membership 回填（仅普通业务角色；superadmin / supplier 不回填）
    rows = bind.execute(sa.text(
        "SELECT u.id, u.tenant_id, LOWER(u.role) FROM users u "
        "JOIN workspace_profiles wp ON wp.tenant_id = u.tenant_id "
        "WHERE LOWER(u.role) IN ('admin','owner','operator','viewer','read_only',"
        "'readonly','compliance_approver','compliance')")).fetchall()
    existing_members = {(r[0], r[1]) for r in bind.execute(
        sa.text("SELECT workspace_id, user_id FROM workspace_memberships"))}
    for user_id, tenant_id, legacy_role in rows:
        profile_id = bind.execute(
            sa.text("SELECT id FROM workspace_profiles WHERE tenant_id = :t"),
            {"t": tenant_id}).scalar()
        if profile_id is None:
            counts["skipped"] += 1
            continue
        if (profile_id, user_id) in existing_members:
            counts["skipped"] += 1
            continue
        role_key = _LEGACY_ROLE_MAP.get(legacy_role)
        if role_key is None:
            counts["skipped"] += 1
            continue
        bind.execute(
            sa.text("INSERT INTO workspace_memberships "
                    "(workspace_id, user_id, role_key, status, is_primary, source, "
                    " created_at, updated_at) "
                    "VALUES (:w, :u, :r, 'ACTIVE', 1, 'LEGACY_BACKFILL', "
                    "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"w": profile_id, "u": user_id, "r": role_key})
        counts["memberships_inserted"] += 1

    # ---- 6. 硬性断言
    _assert_backfill(bind)

    print(f"[Revision B] backfill counts: {counts}")


def _assert_backfill(bind) -> None:
    """回填后硬性断言；任一不满足立即抛错回滚。"""
    def scalar(sql: str, **params):
        return bind.execute(sa.text(sql), params).scalar()

    profiles = scalar("SELECT COUNT(*) FROM workspace_profiles")
    tenants = scalar("SELECT COUNT(*) FROM tenants WHERE id <> 0")
    assert profiles == tenants, f"workspace_profiles={profiles} 应为 {tenants}"

    memberships = scalar("SELECT COUNT(*) FROM workspace_memberships")
    candidates = scalar(
        "SELECT COUNT(*) FROM users u JOIN workspace_profiles wp "
        "ON wp.tenant_id = u.tenant_id "
        "WHERE LOWER(u.role) IN ('admin','owner','operator','viewer','read_only',"
        "'readonly','compliance_approver','compliance')")
    assert memberships == candidates, \
        f"workspace_memberships={memberships} 应为 {candidates}"

    superadmin_memberships = scalar(
        "SELECT COUNT(*) FROM workspace_memberships wm JOIN users u ON u.id = wm.user_id "
        "WHERE LOWER(u.role) = 'superadmin'")
    assert superadmin_memberships == 0, "superadmin 不得有 Membership"

    supplier_memberships = scalar(
        "SELECT COUNT(*) FROM workspace_memberships wm JOIN users u ON u.id = wm.user_id "
        "WHERE LOWER(u.role) = 'supplier'")
    assert supplier_memberships == 0, "supplier 不得回填普通 Membership"

    multi = scalar(
        "SELECT COUNT(*) FROM (SELECT user_id FROM workspace_memberships "
        "GROUP BY user_id HAVING COUNT(*) > 1)")
    assert multi == 0, f"有 {multi} 个用户拥有多个 Membership"

    orphan_ws = scalar(
        "SELECT COUNT(*) FROM workspace_memberships wm "
        "LEFT JOIN workspace_profiles wp ON wp.id = wm.workspace_id "
        "WHERE wp.id IS NULL")
    assert orphan_ws == 0, f"有 {orphan_ws} 条 Membership 引用不存在的 Workspace"

    orphan_user = scalar(
        "SELECT COUNT(*) FROM workspace_memberships wm "
        "LEFT JOIN users u ON u.id = wm.user_id WHERE u.id IS NULL")
    assert orphan_user == 0, f"有 {orphan_user} 条 Membership 引用不存在的 User"

    perms = scalar("SELECT COUNT(*) FROM permissions")
    assert perms >= len(PERMISSIONS), f"permissions={perms} 少于期望 {len(PERMISSIONS)}"

    roles = scalar("SELECT COUNT(*) FROM workspace_roles")
    assert roles >= len(ROLES), f"workspace_roles={roles} 少于期望 {len(ROLES)}"


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM workspace_memberships"))
    bind.execute(sa.text("DELETE FROM workspace_profiles"))
    bind.execute(sa.text("DELETE FROM role_permissions"))
    bind.execute(sa.text("DELETE FROM workspace_roles"))
    bind.execute(sa.text("DELETE FROM permissions"))
