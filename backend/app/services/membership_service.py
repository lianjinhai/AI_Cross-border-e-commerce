"""Workspace Membership 写入侧（Phase 1.8 收口）。

为什么需要本模块（三个同源缺陷）：
    Phase 1.1~1.7 只实现了**读取侧**（`resolve_workspace_context` 双读），
    写入侧一直缺失，导致：
      1. `POST /api/admin/tenants` 不建 `workspace_profiles` → 新租户永远拿不到
         MEMBERSHIP Context（实测 `source=LEGACY_FALLBACK`）；
      2. `POST /api/auth/users` 不建 `workspace_memberships` → 新用户同上；
      3. `PUT /api/auth/users/{id}` 改角色只改 `users.role`，而 MEMBERSHIP 是
         **权威路径** → 把 operator 降为 viewer **不生效**（实测 Context 仍返回
         OPERATOR）。这是安全缺陷：降权操作被静默忽略。
    三者根因相同——身份表没有写入口。本模块是唯一写入口。

渐进启用（与读取侧一致，勿改成强制写）：
    `workspace_profiles` / `workspace_memberships` 由 Alembic 迁移创建，
    `models.py` 刻意不注册（否则 `create_all` 会绕过 Phase 1 的维护窗口门禁）。
    因此表未落地时本模块**全部为 no-op**，行为与 Phase 1.1 完全一致；
    表落地后自动生效，无需改调用方。

依赖方向：本模块属 `services/`，只依赖 `models` 与同层 `workspace_context`，
禁止反向 import `routers/`（规范 §4 L-1）。
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import User
from .workspace_context import (
    ROLE_FACTORY_COLLABORATOR,
    ROLE_PLATFORM_ADMIN,
    membership_table_available,
    normalize_legacy_role,
)

logger = logging.getLogger("erp.membership")

# 这两种身份**不属于任何业务 Workspace**，不得生成 Membership
# （与迁移 20260923_08 的回填规则一致：superadmin / supplier 不回填）。
_NO_MEMBERSHIP_ROLES = frozenset({ROLE_PLATFORM_ADMIN, ROLE_FACTORY_COLLABORATOR})

_PROFILE_BY_TENANT = "SELECT id FROM workspace_profiles WHERE tenant_id = :t"
_MEMBERSHIP_BY_USER = "SELECT id, role_key, status FROM workspace_memberships WHERE user_id = :u"


def role_for_membership(legacy_role: str | None) -> str | None:
    """legacy 角色 → Membership role_key；不该有 Membership 的身份返回 None。

    复用读取侧的 `normalize_legacy_role`，保证写侧与读侧**同一张映射表**——
    两处各写一份是权限漂移的经典成因（例如 `compliance_approver` 一边映射
    COMPLIANCE、另一边漏掉，就会出现「写进去的角色读不出来」）。
    """
    role = normalize_legacy_role(legacy_role)
    if role in _NO_MEMBERSHIP_ROLES:
        return None
    return role


def ensure_workspace_profile(db: Session, tenant_id: int, name: str) -> int | None:
    """确保租户有对应的 WorkspaceProfile，返回其 id（表未落地时返回 None）。

    幂等：已存在则直接返回既有 id，不覆盖名称——Workspace 名称是用户数据，
    租户改名不应静默改写（改名走 Phase 2 的 Workspace 管理界面）。
    """
    if not membership_table_available(db):
        return None
    row = db.execute(text(_PROFILE_BY_TENANT), {"t": tenant_id}).first()
    if row is not None:
        return int(row[0])
    db.execute(
        text("INSERT INTO workspace_profiles "
             "(tenant_id, name, kind, status, owner_user_id, created_at) "
             "VALUES (:t, :n, 'ORGANIZATION', 'active', NULL, CURRENT_TIMESTAMP)"),
        {"t": tenant_id, "n": name or ""})
    db.flush()
    created = db.execute(text(_PROFILE_BY_TENANT), {"t": tenant_id}).first()
    return int(created[0]) if created is not None else None


def sync_membership(db: Session, user: User, workspace_name: str = "") -> int | None:
    """把用户的 legacy 身份**同步**到 Membership（幂等 upsert），返回 workspace_id。

    何时调用：用户创建、角色变更、租户开通。调用方负责 commit。

    为什么要 upsert 而不是只 insert：`PUT /api/auth/users/{id}` 改角色时必须
    更新 `role_key`，否则 MEMBERSHIP 权威路径会继续下发**旧角色**的权限
    （降权失效）。本函数同时覆盖「新建」与「改角色」两种场景。
    """
    if user.tenant_id is None:
        return None
    role_key = role_for_membership(user.role)
    if role_key is None:
        return None
    workspace_id = ensure_workspace_profile(db, user.tenant_id, workspace_name)
    if workspace_id is None:
        return None

    existing = db.execute(text(_MEMBERSHIP_BY_USER), {"u": user.id}).first()
    if existing is None:
        db.execute(
            text("INSERT INTO workspace_memberships "
                 "(workspace_id, user_id, role_key, status, is_primary, source, "
                 " created_at, updated_at) "
                 "VALUES (:w, :u, :r, 'ACTIVE', 1, 'API_SYNC', "
                 "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"w": workspace_id, "u": user.id, "r": role_key})
        db.flush()
        logger.info("membership created", extra={
            "user_id": user.id, "workspace_id": workspace_id, "role": role_key})
        return workspace_id

    membership_id, old_role, status = int(existing[0]), existing[1], existing[2]
    if old_role == role_key and status == "ACTIVE":
        return workspace_id
    # 改角色：只更新 role_key（status 保持，避免把停用成员意外激活）
    db.execute(
        text("UPDATE workspace_memberships "
             "SET role_key = :r, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"r": role_key, "id": membership_id})
    db.flush()
    logger.info("membership role synced", extra={
        "user_id": user.id, "workspace_id": workspace_id,
        "old_role": old_role, "new_role": role_key})
    return workspace_id


def remove_user_memberships(db: Session, user_id: int) -> int:
    """删除用户的全部 Membership 行（用户删除时调用），返回删除条数。

    为什么必须显式删除：`workspace_memberships.user_id` 声明了
    ``FK → users.id`` 且 `PRAGMA foreign_keys=ON`，直接删用户会
    ``IntegrityError``（实测 500）。身份行随账号消亡是正确的语义——
    它不是业务数据，不需要保留归属。
    """
    if not membership_table_available(db):
        return 0
    result = db.execute(
        text("DELETE FROM workspace_memberships WHERE user_id = :u"), {"u": user_id})
    return int(result.rowcount or 0)


def remove_user_portal_bindings(db: Session, user_id: int) -> int:
    """删除用户的工厂门户绑定（用户删除时调用），返回删除条数。

    与 Membership 同源：`supplier_portal_members.user_id` 也是 ``FK → users.id``，
    不清理同样会 IntegrityError。工厂账号与 Membership 互斥（`supplier` 角色
    不生成 Membership），但两者都必须在删账号时清理。

    注意：**不**用 `membership_table_available` 做门禁——`SupplierPortalMember`
    是 ORM 模型（`models.py` 注册），`create_all` 一定会建表，与 Phase 1 身份表
    的渐进启用无关。用身份表探测门禁会让本函数在迁移前静默 no-op，
    反而漏掉清理、删账号时撞外键。
    """
    result = db.execute(
        text("DELETE FROM supplier_portal_members WHERE user_id = :u"), {"u": user_id})
    return int(result.rowcount or 0)
