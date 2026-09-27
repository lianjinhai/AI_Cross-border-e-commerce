"""新增权限 key support:read（客服会话读取，Conversation Tool 的前置）

背景（docs/DECISIONS.md D39）：Agent OS §10.4.1 第二批清单新增 Conversation Tool，
它的权限 key 必须来自冻结权限目录。Phase 1 目录（docs/phase1_interfaces.md §4）
原先没有「客服会话」这个域，因此按「只增不改」补 `support:read`。

授予范围与现状一致：`/api/support` 的读端点只要求登录，本 key 归入只读角色集合
（OWNER / OPERATOR / READ_ONLY）。**只加读、不加写**：会话写入仍走业务 API，
Agent 侧写操作必须经 Action 层（§9.1）。

为什么必须走迁移而不是只改代码常量：权限读取**优先走表**
（`workspace_context._permissions_from_db`），表与常量漂移时**表胜出**——只改常量
在线上不生效（tests/test_workspace_dual_read.py 已固化该契约）。

**必须先写 permissions 再写 role_permissions**：`role_permissions.permission_key`
有外键指向 `permissions.key`（Revision 07 定义），顺序颠倒会在开启外键强制的库上
IntegrityError（Revision 15 已实测复现）。

幂等：INSERT 前检查 key / (role_key, permission_key) 是否已存在。不修改、不删除
任何既有行。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260927_17"
down_revision = "20260924_16"
branch_labels = None
depends_on = None

# 新增权限 key → 授予的角色（与 workspace_context.ROLE_PERMISSIONS 保持一致）
NEW_PERMISSIONS = {
    "support:read": ("OWNER", "OPERATOR", "READ_ONLY"),
}
# 权限目录元数据（domain, action, description），写入 permissions 表
PERMISSION_META = {
    "support:read": ("support", "read", "读取客服会话（不含买家 PII）"),
}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {"permissions", "role_permissions"} <= tables:
        print("[Revision 17] 权限表不存在（旧库未执行 Revision 07/08），跳过")
        return

    # ---- 1. 先补 permissions 目录（role_permissions 的外键指向这里）
    existing_keys = {r[0] for r in bind.execute(sa.text("SELECT key FROM permissions"))}
    for perm_key in NEW_PERMISSIONS:
        if perm_key in existing_keys:
            print(f"[Revision 17] permissions 已有 {perm_key}，跳过")
            continue
        domain, action, desc = PERMISSION_META.get(perm_key, ("", "", ""))
        bind.execute(
            sa.text("INSERT INTO permissions (key, domain, action, description) "
                    "VALUES (:k, :d, :a, :desc)"),
            {"k": perm_key, "d": domain, "a": action, "desc": desc})
        print(f"[Revision 17] permissions 新增 {perm_key}")

    # ---- 2. 再补 role_permissions 映射
    existing = {(r[0], r[1]) for r in bind.execute(
        sa.text("SELECT role_key, permission_key FROM role_permissions"))}
    inserted = []
    for perm_key, role_keys in NEW_PERMISSIONS.items():
        for role_key in role_keys:
            if (role_key, perm_key) in existing:
                continue
            bind.execute(
                sa.text("INSERT INTO role_permissions (role_key, permission_key) "
                        "VALUES (:r, :p)"),
                {"r": role_key, "p": perm_key})
            inserted.append(f"{role_key}->{perm_key}")
    print(f"[Revision 17] 已插入权限映射: {inserted or '无（均已存在）'}")


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {"permissions", "role_permissions"} <= tables:
        return
    for perm_key, role_keys in NEW_PERMISSIONS.items():
        for role_key in role_keys:
            bind.execute(
                sa.text("DELETE FROM role_permissions "
                        "WHERE role_key = :r AND permission_key = :p"),
                {"r": role_key, "p": perm_key})
        # 映射删完再删目录行（否则外键拦截）
        bind.execute(sa.text("DELETE FROM permissions WHERE key = :k"), {"k": perm_key})
    print("[Revision 17] 已回滚 support:read 权限映射")
