"""Phase 1.1 Identity Compatibility Layer 测试（legacy-only，无数据库结构变更）。

覆盖：四种 source 分流、legacy 角色归一化、未知角色降级、权限映射、
双读顺序、日志不含 PII、MEMBERSHIP 分支尚未启用时的行为。
"""
import logging

from app.db import SessionLocal
from app.models import Supplier, SupplierPortalMember, User
from app.services import workspace_context as wc


def _user(db, username: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    assert user is not None, f"种子数据缺少用户 {username}"
    return user


def test_legacy_role_normalization():
    assert wc.normalize_legacy_role("admin") == wc.ROLE_OWNER
    assert wc.normalize_legacy_role("ADMIN") == wc.ROLE_OWNER
    assert wc.normalize_legacy_role("owner") == wc.ROLE_OWNER
    assert wc.normalize_legacy_role("operator") == wc.ROLE_OPERATOR
    assert wc.normalize_legacy_role("viewer") == wc.ROLE_READ_ONLY
    assert wc.normalize_legacy_role("compliance_approver") == wc.ROLE_COMPLIANCE
    assert wc.normalize_legacy_role("superadmin") == wc.ROLE_PLATFORM_ADMIN
    assert wc.normalize_legacy_role("supplier") == wc.ROLE_FACTORY_COLLABORATOR


def test_unknown_role_downgrades_to_read_only():
    assert wc.normalize_legacy_role("auditor") == wc.ROLE_READ_ONLY
    assert wc.normalize_legacy_role("") == wc.ROLE_READ_ONLY
    assert wc.normalize_legacy_role(None) == wc.ROLE_READ_ONLY
    assert wc.is_unknown_legacy_role("auditor") is True
    assert wc.is_unknown_legacy_role("viewer") is False


def test_permission_mapping_matches_contract():
    owner = wc.ROLE_PERMISSIONS[wc.ROLE_OWNER]
    assert "workspace:member:admin" in owner
    assert "compliance:approve" in owner

    operator = wc.ROLE_PERMISSIONS[wc.ROLE_OPERATOR]
    assert "order:write" in operator
    assert "workspace:member:admin" not in operator
    assert "platform:admin" not in operator

    read_only = wc.ROLE_PERMISSIONS[wc.ROLE_READ_ONLY]
    # 不能写 `read_only == wc._READ_PERMISSIONS`：`ROLE_READ_ONLY` 的定义就是
    # 同一个对象，等于 `x == x`（恒真），无法发现只读集合被误加写权限。
    assert read_only == frozenset({
        "ai:read", "compliance:read", "finance:read", "listing:read", "order:read",
        "product:read", "purchase:read", "refund:read", "settlement:read",
        "supply:read", "workspace:read"}), read_only
    assert not any(p.endswith(":write") for p in read_only), read_only

    compliance = wc.ROLE_PERMISSIONS[wc.ROLE_COMPLIANCE]
    assert compliance == frozenset({
        "compliance:read", "compliance:approve", "compliance:check",
        "listing:read", "product:read"})

    assert wc.ROLE_PERMISSIONS[wc.ROLE_PLATFORM_ADMIN] == frozenset({"platform:admin"})
    assert wc.ROLE_PERMISSIONS[wc.ROLE_FACTORY_COLLABORATOR] == frozenset({
        "supply:read", "supply:write"})


def test_platform_identity_has_no_business_workspace(client):
    with SessionLocal() as db:
        root = _user(db, "root")
        ctx = wc.resolve_workspace_context(db, root)
    assert ctx.source == wc.SOURCE_PLATFORM
    assert ctx.workspace_id is None
    assert ctx.role == wc.ROLE_PLATFORM_ADMIN
    assert ctx.is_platform_identity() is True
    assert "order:read" not in ctx.permissions
    assert "platform:admin" in ctx.permissions


def test_admin_resolves_with_owner_identity(client):
    """admin 的身份不变量：OWNER 角色 + 归属自身 tenant（与来源分支无关）。

    `source` 不再是字面量断言：身份表落地后走 MEMBERSHIP，未落地才走 LEGACY。
    本用例只守护与来源无关的硬不变量，来源分支由下方两个专项用例覆盖。
    """
    with SessionLocal() as db:
        admin = _user(db, "admin")
        ctx = wc.resolve_workspace_context(db, admin)
        expected_tenant = admin.tenant_id
    # 期望值固定为生产态（MEMBERSHIP），不由被测的 membership_table_available()
    # 推导：conftest 已把测试库推进到完整迁移链，身份表必然存在。用被测函数推导
    # 期望值是自证式断言——探测函数坏掉（恒返回 False）时用例仍会通过。
    assert ctx.source == wc.SOURCE_MEMBERSHIP
    assert ctx.role == wc.ROLE_OWNER
    assert ctx.workspace_id == expected_tenant
    assert ctx.legacy_tenant_id == expected_tenant
    assert ctx.membership_id is not None, "MEMBERSHIP 分支必须带 membership_id"
    assert ctx.workspace_kind == wc.WORKSPACE_KIND_ORGANIZATION
    assert ctx.can_write() is True
    assert ctx.can_admin() is True
    assert ctx.has("order:read") is True


def test_viewer_is_read_only_and_operator_can_write(client):
    with SessionLocal() as db:
        viewer_ctx = wc.resolve_workspace_context(db, _user(db, "viewer"))
        ops_ctx = wc.resolve_workspace_context(db, _user(db, "ops"))
    assert viewer_ctx.role == wc.ROLE_READ_ONLY
    assert viewer_ctx.can_write() is False
    assert viewer_ctx.has("order:read") is True
    assert viewer_ctx.can_admin() is False

    assert ops_ctx.role == wc.ROLE_OPERATOR
    assert ops_ctx.can_write() is True
    assert ops_ctx.can_admin() is False


def test_factory_collaborator_context_is_restricted(client):
    with SessionLocal() as db:
        tenant = _user(db, "admin").tenant_id
        supplier = Supplier(tenant_id=tenant, name="ctx-test-supplier")
        db.add(supplier)
        db.flush()
        collaborator = User(tenant_id=tenant, username="ctx-factory-user",
                            password_hash="x", display_name="工厂协作",
                            role="supplier", status="active")
        db.add(collaborator)
        db.flush()
        db.add(SupplierPortalMember(tenant_id=tenant, supplier_id=supplier.id,
                                    user_id=collaborator.id))
        db.commit()

        ctx = wc.resolve_workspace_context(db, collaborator)
        assert ctx.source == wc.SOURCE_FACTORY
        assert ctx.data_scope == wc.SCOPE_FACTORY_SELF
        assert ctx.permissions == frozenset({"supply:read", "supply:write"})
        assert ctx.has("order:read") is False
        assert ctx.is_factory_collaborator() is True

        db.query(SupplierPortalMember).filter(
            SupplierPortalMember.user_id == collaborator.id).delete()
        db.delete(collaborator)
        db.delete(supplier)
        db.commit()


def test_factory_collaborator_without_binding_gets_no_permissions(client):
    with SessionLocal() as db:
        tenant = _user(db, "admin").tenant_id
        orphan = User(tenant_id=tenant, username="ctx-unbound-factory",
                      password_hash="x", display_name="未绑定工厂",
                      role="supplier", status="active")
        db.add(orphan)
        db.commit()
        ctx = wc.resolve_workspace_context(db, orphan)
        assert ctx.source == wc.SOURCE_FACTORY
        assert ctx.permissions == frozenset()
        assert ctx.workspace_id is None
        db.delete(orphan)
        db.commit()


def test_impersonation_keeps_workspace_and_marks_flag(client):
    with SessionLocal() as db:
        root = _user(db, "root")
        target = _user(db, "admin").tenant_id
        ctx = wc.resolve_workspace_context(db, root, is_impersonating=True)
    # 代客访问不是 Platform Identity：必须落到目标 Workspace
    assert ctx.source != wc.SOURCE_PLATFORM
    assert ctx.workspace_id == root.tenant_id
    assert ctx.is_impersonating is True
    assert target is not None


def test_membership_branch_gated_by_table_availability(client):
    """渐进启用契约：MEMBERSHIP 分支只在身份表落地后生效，且**来源与表状态自洽**。

    原断言写死"表不存在 → LEGACY"，那是测试库缺陷的产物（测试库曾用 create_all
    建表、缺 workspace_memberships，而生产库已执行迁移）。现在 conftest 会补跑
    Revision A/B，因此改为按表状态断言，两条分支都不会误报：
      - 表未落地：不得出现 MEMBERSHIP（旧行为，防提前启用）
      - 表已落地：必须走 MEMBERSHIP 且带 membership_id（生产路径，防静默回退）
    """
    with SessionLocal() as db:
        table_available = wc.membership_table_available(db)
        ctx = wc.resolve_workspace_context(db, _user(db, "admin"))
    if table_available:
        assert ctx.source == wc.SOURCE_MEMBERSHIP
        assert ctx.membership_id is not None
    else:
        assert ctx.source == wc.SOURCE_LEGACY
        assert ctx.membership_id is None


def test_public_dict_excludes_pii(client):
    with SessionLocal() as db:
        ctx = wc.resolve_workspace_context(db, _user(db, "admin"))
    public = ctx.to_public_dict()
    assert "username" not in public
    assert "password_hash" not in public
    assert set(public) == {
        "user_id", "workspace_id", "workspace_name", "workspace_kind", "role",
        "permissions", "data_scope", "source", "is_impersonating", "trace_id"}
    audit = ctx.to_audit_dict()
    assert set(audit) == {
        "trace_id", "user_id", "legacy_tenant_id", "workspace_id", "source", "role"}


def test_context_logs_without_pii_on_active_branch(client, caplog):
    """身份解析日志的 PII 红线：不论走哪条分支，都不得回显凭证。

    原用例断言日志里必须含 "legacy"，前提是"身份表不存在"——那是测试库缺陷的
    产物。日志内容随分支变化（membership / legacy），但**不含 PII 是与分支无关
    的硬约束**，这里改为对实际生效分支断言，并额外验证分支名如实记录。
    """
    with SessionLocal() as db:
        table_available = wc.membership_table_available(db)
        with caplog.at_level(logging.INFO, logger="erp.workspace_context"):
            wc.resolve_workspace_context(db, _user(db, "admin"))
    joined = "\n".join(str(record.__dict__) for record in caplog.records)
    assert "admin123" not in joined
    assert "pbkdf2" not in joined
    assert "password" not in joined.lower()
    expected_branch = "membership" if table_available else "legacy"
    assert expected_branch in joined, f"日志未如实记录来源分支：{joined}"


def test_unknown_role_logs_downgrade_warning(client, caplog):
    with SessionLocal() as db:
        tenant = _user(db, "admin").tenant_id
        odd = User(tenant_id=tenant, username="ctx-odd-role", password_hash="x",
                   display_name="未知角色", role="auditor", status="active")
        db.add(odd)
        db.commit()
        with caplog.at_level(logging.WARNING, logger="erp.workspace_context"):
            ctx = wc.resolve_workspace_context(db, odd)
        db.delete(odd)
        db.commit()
    assert ctx.role == wc.ROLE_READ_ONLY
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "未知角色必须产生告警日志"
    assert "auditor" not in str(warnings[0].__dict__), "日志不得回显原始角色值以外的 PII"


def test_trace_id_is_unique_per_resolution(client):
    with SessionLocal() as db:
        admin = _user(db, "admin")
        first = wc.resolve_workspace_context(db, admin)
        second = wc.resolve_workspace_context(db, admin)
    assert first.trace_id and second.trace_id
    assert first.trace_id != second.trace_id


def test_inactive_portal_binding_grants_no_permissions(client):
    """已停用的门户绑定不得授予任何业务权限（fail-closed）。

    真实缺陷（G-3 排查中发现）：`build_factory_context()` 查询
    `SupplierPortalMember` 时**只按 user_id 过滤、未校验 status**，而路由层
    `_portal_scope` 一直带 `status == "active"`。两条路径判定不一致，形成
    fail-open：绑定停用后，门户 API 拒绝（403），但 Context 仍宣称
    `supply:read/supply:write`。

    影响面随 G-3 放大：`/api/me/workspace-context` 现已对工厂账号开放，
    Context 是前端**权威**权限来源（`permissions.js` 的 legacy 仅兜底），
    于是表现为「界面按钮可点、实际请求 403」；且 `require_permission`
    也以 Context 为权威判定路径，属后端鉴权面。

    对照断言：MEMBERSHIP 路径（`_load_active_membership`）一直带
    `status='ACTIVE'`，本条只补工厂路径的同等校验。
    """
    from app.auth import hash_password
    from app.models import Supplier, SupplierPortalMember

    with SessionLocal() as db:
        tenant = _user(db, "admin").tenant_id
        supplier = Supplier(tenant_id=tenant, name="ctx-inactive-supplier")
        db.add(supplier)
        db.flush()
        account = User(tenant_id=tenant, username="ctx-inactive-portal",
                       password_hash=hash_password("x"), display_name="停用门户",
                       role="supplier", status="active")
        db.add(account)
        db.flush()
        member = SupplierPortalMember(tenant_id=tenant, supplier_id=supplier.id,
                                      user_id=account.id, status="inactive")
        db.add(member)
        db.commit()
        try:
            ctx = wc.resolve_workspace_context(db, account)
            # 绑定已停用 → 与「未绑定」同等对待：无权限、无 Workspace
            assert ctx.source == wc.SOURCE_FACTORY
            assert ctx.permissions == frozenset(), "停用绑定不得授予权限"
            assert ctx.workspace_id is None, "停用绑定不得暴露 Workspace"
            assert ctx.is_factory_collaborator() is True
        finally:
            db.query(SupplierPortalMember).filter(
                SupplierPortalMember.user_id == account.id).delete()
            db.delete(account)
            db.delete(supplier)
            db.commit()


def test_active_portal_binding_still_grants_permissions(client):
    """对照组：status='active' 的绑定必须正常授权（防止把校验改过头）。"""
    from app.auth import hash_password
    from app.models import Supplier, SupplierPortalMember

    with SessionLocal() as db:
        tenant = _user(db, "admin").tenant_id
        supplier = Supplier(tenant_id=tenant, name="ctx-active-supplier")
        db.add(supplier)
        db.flush()
        account = User(tenant_id=tenant, username="ctx-active-portal",
                       password_hash=hash_password("x"), display_name="有效门户",
                       role="supplier", status="active")
        db.add(account)
        db.flush()
        db.add(SupplierPortalMember(tenant_id=tenant, supplier_id=supplier.id,
                                    user_id=account.id, status="active"))
        db.commit()
        try:
            ctx = wc.resolve_workspace_context(db, account)
            assert ctx.permissions == frozenset({"supply:read", "supply:write"})
            assert ctx.workspace_id == supplier.tenant_id
        finally:
            db.query(SupplierPortalMember).filter(
                SupplierPortalMember.user_id == account.id).delete()
            db.delete(account)
            db.delete(supplier)
            db.commit()
