"""Workspace Context Service（Phase 1.1 Identity Compatibility Layer）。

目标：在数据库尚未新增 WorkspaceMembership 表之前，先冻结"身份从哪里读"的唯一入口。
业务代码禁止直接读 `User.tenant_id` / `User.role`，必须通过本模块取 Context。

当前阶段实现为 **legacy-only**：

- 只包装现有 `User` + `Tenant` + `SupplierPortalMember`；
- 不写数据库、不建表、不迁移；
- 所有 legacy 路径显式标记 `source=LEGACY_FALLBACK` 并产生结构化日志。

契约见 `docs/phase1_interfaces.md`（FROZEN）。
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..models import Tenant, User

logger = logging.getLogger("erp.workspace_context")

# ---------------------------------------------------------------- 冻结枚举

SOURCE_MEMBERSHIP = "MEMBERSHIP"
SOURCE_LEGACY = "LEGACY_FALLBACK"
SOURCE_PLATFORM = "PLATFORM"
SOURCE_FACTORY = "FACTORY"

ROLE_OWNER = "OWNER"
ROLE_OPERATOR = "OPERATOR"
ROLE_READ_ONLY = "READ_ONLY"
ROLE_COMPLIANCE = "COMPLIANCE"
ROLE_PLATFORM_ADMIN = "PLATFORM_ADMIN"
ROLE_FACTORY_COLLABORATOR = "FACTORY_COLLABORATOR"

WORKSPACE_KIND_ORGANIZATION = "ORGANIZATION"
WORKSPACE_KIND_PERSONAL = "PERSONAL"
WORKSPACE_KIND_FACTORY = "FACTORY"
WORKSPACE_KIND_PLATFORM = "PLATFORM"

SCOPE_WORKSPACE_ALL = "WORKSPACE_ALL"
SCOPE_FACTORY_SELF = "FACTORY_SELF"

_LEGACY_ROLE_MAP = {
    "owner": ROLE_OWNER,
    "admin": ROLE_OWNER,
    "operator": ROLE_OPERATOR,
    "read_only": ROLE_READ_ONLY,
    "readonly": ROLE_READ_ONLY,
    "viewer": ROLE_READ_ONLY,
    "compliance": ROLE_COMPLIANCE,
    "compliance_approver": ROLE_COMPLIANCE,
    "platform_admin": ROLE_PLATFORM_ADMIN,
    "superadmin": ROLE_PLATFORM_ADMIN,
    "factory_collaborator": ROLE_FACTORY_COLLABORATOR,
    "supplier": ROLE_FACTORY_COLLABORATOR,
}

_READ_PERMISSIONS = frozenset({
    "workspace:read", "product:read", "supply:read", "listing:read", "order:read",
    "finance:read", "purchase:read", "settlement:read", "refund:read",
    "compliance:read", "ai:read",
    # support:read（2026-09-27，D39）：客服会话读取。Phase 1 目录原先没有这个域，
    # 而 Conversation Tool（架构 §10.4.1）必须有权限 key 才能进 Tool 层闸门。
    # 授予范围与现状一致：/api/support 的读端点只要求登录，本 key 归入只读角色集合。
    # 只加读、不加写：会话写入当前仍走业务 API，且 Agent 侧写操作必须经 Action 层。
    "support:read",
})
_WRITE_PERMISSIONS = frozenset({
    "workspace:write", "product:write", "supply:write", "listing:write", "order:write",
    "finance:write", "purchase:write", "settlement:write", "refund:write", "ai:write",
})

# 特殊权限 key（不属于批量读写集合）
# compliance:check = 检测报告与受限风险副本 Action；不授权内容编辑或发布
_PERM_COMPLIANCE_CHECK = "compliance:check"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_OWNER: _READ_PERMISSIONS | _WRITE_PERMISSIONS | frozenset({
        "workspace:member:admin", "compliance:approve", _PERM_COMPLIANCE_CHECK}),
    # OPERATOR 额外持有 compliance:check：与 /api/compliance/check 的契约一致
    # （该端点的 legacy 兜底角色是 ("admin","operator","compliance_approver")，
    # 且其文档写明"OWNER/OPERATOR/COMPLIANCE 拥有"）。此前常量漏了 OPERATOR，
    # 导致 MEMBERSHIP 路径下运营发起合规检测被 403——注释/兜底/实现三者不一致。
    ROLE_OPERATOR: _READ_PERMISSIONS | _WRITE_PERMISSIONS | frozenset({
        _PERM_COMPLIANCE_CHECK}),
    ROLE_READ_ONLY: _READ_PERMISSIONS,
    # 合规员：可发起检测（check）与审批（approve），但仍不能改商品/发布 Listing
    ROLE_COMPLIANCE: frozenset({
        "compliance:read", "compliance:approve", _PERM_COMPLIANCE_CHECK,
        "listing:read", "product:read"}),
    ROLE_PLATFORM_ADMIN: frozenset({"platform:admin"}),
    ROLE_FACTORY_COLLABORATOR: frozenset({"supply:read", "supply:write"}),
}


class WorkspaceContextError(Exception):
    """Context 无法解析（未登录、无可用 Workspace、身份冲突）。"""


def normalize_legacy_role(raw_role: str | None) -> str:
    """legacy 角色归一化；未知值降级为 READ_ONLY 并返回降级标记。"""
    key = (raw_role or "").strip().lower()
    return _LEGACY_ROLE_MAP.get(key, ROLE_READ_ONLY)


def is_unknown_legacy_role(raw_role: str | None) -> bool:
    return (raw_role or "").strip().lower() not in _LEGACY_ROLE_MAP


@dataclass(frozen=True)
class WorkspaceContext:
    """请求级身份快照（不可变）。字段契约见 docs/phase1_interfaces.md 第 2 节。"""

    user_id: int
    username: str
    display_name: str
    workspace_id: int | None
    workspace_name: str
    workspace_kind: str
    membership_id: int | None
    role: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    data_scope: str = SCOPE_WORKSPACE_ALL
    source: str = SOURCE_LEGACY
    is_impersonating: bool = False
    trace_id: str = ""
    legacy_tenant_id: int | None = None

    # ---- 便捷判定（新代码统一使用这些方法，禁止散落 role 字符串比较）
    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def can_write(self) -> bool:
        return bool(self.permissions & _WRITE_PERMISSIONS)

    def can_admin(self) -> bool:
        return "workspace:member:admin" in self.permissions

    def can_approve(self) -> bool:
        return "compliance:approve" in self.permissions

    def is_platform_identity(self) -> bool:
        return self.source == SOURCE_PLATFORM

    def is_factory_collaborator(self) -> bool:
        return self.source == SOURCE_FACTORY

    def to_public_dict(self) -> dict[str, Any]:
        """API 输出：不含 username 等 PII。"""
        return {
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "workspace_kind": self.workspace_kind,
            "role": self.role,
            "permissions": sorted(self.permissions),
            "data_scope": self.data_scope,
            "source": self.source,
            "is_impersonating": self.is_impersonating,
            "trace_id": self.trace_id,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        """日志用：只含非敏感标识。"""
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "legacy_tenant_id": self.legacy_tenant_id,
            "workspace_id": self.workspace_id,
            "source": self.source,
            "role": self.role,
        }


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def _permissions_for(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, _READ_PERMISSIONS)


def build_platform_context(user: User, trace_id: str | None = None) -> WorkspaceContext:
    """Platform Identity：无业务 Workspace。"""
    return WorkspaceContext(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        workspace_id=None,
        workspace_name="平台服务商",
        workspace_kind=WORKSPACE_KIND_PLATFORM,
        membership_id=None,
        role=ROLE_PLATFORM_ADMIN,
        permissions=_permissions_for(ROLE_PLATFORM_ADMIN),
        data_scope=SCOPE_WORKSPACE_ALL,
        source=SOURCE_PLATFORM,
        trace_id=trace_id or new_trace_id(),
        legacy_tenant_id=None,
    )


def build_factory_context(db, user: User, trace_id: str | None = None) -> WorkspaceContext:
    """Factory Collaborator：由 SupplierPortalMember 生成严格受限 Context。

    **必须只认 `status='active'` 的绑定关系**（与路由层 `_portal_scope` 一致）。
    曾漏掉该条件，导致已停用的门户绑定仍拿到 `supply:read/supply:write`：
    - MEMBERSHIP 路径（`_load_active_membership`）一直带 `status='ACTIVE'`，
      工厂路径是唯一漏检的分支，属实现疏漏而非有意设计；
    - G-3 之后 `/api/me/workspace-context` 对工厂账号开放，Context 成为前端
      **权威**权限来源（`permissions.js` 的 legacy 仅兜底），漏检会直接表现为
      「界面按钮可点、实际请求 403」——用户可见的不一致。

    停用绑定的处理与「未绑定」保持一致：不授予任何业务权限
    （`permissions=∅`、`workspace_id=None`），仍可访问门户自身资料。
    """
    from ..models import Supplier, SupplierPortalMember

    trace = trace_id or new_trace_id()
    member = (db.query(SupplierPortalMember)
              .filter(SupplierPortalMember.user_id == user.id,
                      SupplierPortalMember.status == "active")
              .first())
    supplier = db.get(Supplier, member.supplier_id) if member else None
    if supplier is None:
        # 无有效绑定关系（未绑定 / 绑定已停用）：不授予任何业务数据权限，
        # 但仍可访问门户自身资料。
        logger.warning("factory collaborator without supplier binding", extra={
            "trace_id": trace, "user_id": user.id, "reason": "no_portal_member"})
        return WorkspaceContext(
            user_id=user.id, username=user.username,
            display_name=user.display_name or user.username,
            workspace_id=None, workspace_name="工厂门户", workspace_kind=WORKSPACE_KIND_FACTORY,
            membership_id=None, role=ROLE_FACTORY_COLLABORATOR,
            permissions=frozenset(), data_scope=SCOPE_FACTORY_SELF,
            source=SOURCE_FACTORY, trace_id=trace,
            legacy_tenant_id=user.tenant_id,
        )
    return WorkspaceContext(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        workspace_id=supplier.tenant_id,
        workspace_name=supplier.name,
        workspace_kind=WORKSPACE_KIND_FACTORY,
        membership_id=None,
        role=ROLE_FACTORY_COLLABORATOR,
        permissions=_permissions_for(ROLE_FACTORY_COLLABORATOR),
        data_scope=SCOPE_FACTORY_SELF,
        source=SOURCE_FACTORY,
        trace_id=trace,
        legacy_tenant_id=user.tenant_id,
    )


def build_legacy_context(db, user: User, trace_id: str | None = None,
                         is_impersonating: bool = False) -> WorkspaceContext:
    """兼容期路径：由 User.tenant_id + User.role 生成 Context。

    该函数是 Phase 1 唯一的 legacy 身份读取点；所有调用都必须留下结构化日志。
    """
    trace = trace_id or new_trace_id()
    raw_role = user.role
    if is_unknown_legacy_role(raw_role):
        logger.warning("unknown legacy role downgraded to READ_ONLY", extra={
            "trace_id": trace, "user_id": user.id, "reason": "unknown_role",
            "raw_role_present": bool(raw_role)})
    role = normalize_legacy_role(raw_role)
    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id is not None else None
    logger.info("workspace context resolved from legacy identity", extra={
        "trace_id": trace,
        "user_id": user.id,
        "legacy_tenant_id": user.tenant_id,
        "workspace_id": user.tenant_id,
        "source": SOURCE_LEGACY,
        "role": role,
        "reason": "membership_table_not_yet_available",
    })
    return WorkspaceContext(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        workspace_id=user.tenant_id,
        workspace_name=(tenant.name if tenant else ""),
        workspace_kind=WORKSPACE_KIND_ORGANIZATION,
        membership_id=None,
        role=role,
        permissions=_permissions_for(role),
        data_scope=SCOPE_WORKSPACE_ALL,
        source=SOURCE_LEGACY,
        is_impersonating=is_impersonating,
        trace_id=trace,
        legacy_tenant_id=user.tenant_id,
    )


def resolve_workspace_context(db, user: User, trace_id: str | None = None,
                              is_impersonating: bool = False) -> WorkspaceContext:
    """冻结的双读入口（docs/phase1_interfaces.md 第 6 节）。

    读取顺序：Platform → Factory → MEMBERSHIP → LEGACY_FALLBACK。

    渐进启用：``workspace_memberships`` 表未落地时自动跳过 MEMBERSHIP 分支，
    行为与 Phase 1.1 完全一致；表落地（Revision A/B 执行）后无需改代码即生效。
    调用方始终只调用本函数，不得自行解析 tenant/role。
    """
    trace = trace_id or new_trace_id()
    raw_role = (user.role or "").strip().lower()
    if raw_role == "superadmin" and not is_impersonating:
        return build_platform_context(user, trace)
    if raw_role == "supplier":
        return build_factory_context(db, user, trace)
    if membership_table_available(db):
        membership_row = _load_active_membership(db, user.id)
        if membership_row is not None:
            return build_membership_context(db, user, membership_row, trace,
                                            is_impersonating=is_impersonating)
    return build_legacy_context(db, user, trace, is_impersonating=is_impersonating)


def membership_table_available(db) -> bool:
    """探测 workspace_memberships 是否已落地；供渐进启用 MEMBERSHIP 分支使用。"""
    from sqlalchemy import inspect

    try:
        # 复用调用方连接；独立 Inspector 连接的关闭可能回滚 SQLite 共用连接上的原子写入。
        return "workspace_memberships" in set(inspect(db.connection()).get_table_names())
    except Exception:  # pragma: no cover - 探测失败按未落地处理
        return False


# ---------------------------------------------------------------- P1-08 双读
#
# 说明：本模块刻意 **不定义 WorkspaceMembership 的 ORM 模型**。
# 若注册到 ``Base.metadata``，``init_db()`` 的 ``create_all`` 会在服务启动时
# 自动建表，从而绕过 Phase 1 要求的"维护窗口 + 备份 + 演练"门禁。
# 因此这里统一用运行时探测 + 原生 SQL 读取，表落地后本分支自动生效。

_MEMBERSHIP_QUERY = """
SELECT wm.id, wm.workspace_id, wm.role_key, wm.status, wm.is_primary,
       wp.name, wp.kind
FROM workspace_memberships wm
JOIN workspace_profiles wp ON wp.id = wm.workspace_id
WHERE wm.user_id = :user_id AND wm.status = 'ACTIVE'
ORDER BY wm.is_primary DESC, wm.id ASC
"""

_ROLE_PERMISSION_QUERY = """
SELECT permission_key FROM role_permissions WHERE role_key = :role_key
"""


def _load_active_membership(db, user_id: int):
    """读取用户的 ACTIVE Membership（is_primary 优先）。无则返回 None。"""
    from sqlalchemy import text

    row = db.execute(text(_MEMBERSHIP_QUERY), {"user_id": user_id}).first()
    return row


def _permissions_from_db(db, role_key: str) -> frozenset[str] | None:
    """优先读 role_permissions 表；表为空或不可用时返回 None（由调用方回退代码常量）。"""
    from sqlalchemy import text

    try:
        rows = db.execute(text(_ROLE_PERMISSION_QUERY), {"role_key": role_key}).all()
    except Exception:  # pragma: no cover - 表结构异常时回退代码常量
        return None
    if not rows:
        return None
    return frozenset(r[0] for r in rows)


def build_membership_context(db, user: User, membership_row,
                             trace_id: str | None = None,
                             is_impersonating: bool = False) -> WorkspaceContext:
    """目标态路径：由 ACTIVE WorkspaceMembership 生成 Context。"""
    trace = trace_id or new_trace_id()
    membership_id, workspace_id, role_key, _status, _is_primary, ws_name, ws_kind = membership_row

    raw_role = (role_key or "").strip().upper()
    if raw_role not in ROLE_PERMISSIONS:
        logger.warning("unknown membership role downgraded to READ_ONLY", extra={
            "trace_id": trace, "user_id": user.id, "reason": "unknown_membership_role"})
        role = ROLE_READ_ONLY
    else:
        role = raw_role

    permissions = _permissions_from_db(db, role) or _permissions_for(role)
    logger.info("workspace context resolved from membership", extra={
        "trace_id": trace,
        "user_id": user.id,
        "legacy_tenant_id": user.tenant_id,
        "workspace_id": workspace_id,
        "source": SOURCE_MEMBERSHIP,
        "role": role,
        "reason": "active_membership",
    })
    return WorkspaceContext(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        workspace_id=workspace_id,
        workspace_name=ws_name or "",
        workspace_kind=ws_kind or WORKSPACE_KIND_ORGANIZATION,
        membership_id=membership_id,
        role=role,
        permissions=permissions,
        data_scope=SCOPE_WORKSPACE_ALL,
        source=SOURCE_MEMBERSHIP,
        is_impersonating=is_impersonating,
        trace_id=trace,
        legacy_tenant_id=user.tenant_id,
    )
