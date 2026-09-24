"""Workspace Context API（P1-09）契约测试。

覆盖三端点的状态码与字段契约、PII 红线、以及"切换失败不产生状态变更"。
会话级夹具由 tests/conftest.py 自动注入，本模块不 import 其它测试模块（规范 §8 T-2）。

来源（source）断言说明（审计 P0-2）：
    本模块此前的三处断言硬编码 `source == "LEGACY_FALLBACK"`，那是**测试库缺陷**
    的产物——测试库用 `create_all()` 建表、缺 `workspace_memberships`，而生产库
    已执行 20260923_07/08 迁移。等于固化了"生产不可能出现的行为"，让 MEMBERSHIP
    生产路径在 API 层零覆盖。
    conftest.py 现在会补跑 Revision A/B，使测试库与生产库结构一致，因此这三处
    改为 `_expected_source()`：按身份表是否落地取真实期望值。
"""
from app.db import SessionLocal
from app.models import User
from app.services import workspace_context as wc

WORKSPACE_ITEM_FIELDS = {"id", "name", "kind", "role", "source", "is_active"}
CONTEXT_FIELDS = {
    "user_id", "workspace_id", "workspace_name", "workspace_kind", "role",
    "permissions", "data_scope", "source", "is_impersonating", "trace_id"}


def _expected_source() -> str:
    """身份表落地后期望 MEMBERSHIP，未落地（理论兜底）期望 LEGACY_FALLBACK。

    conftest 会执行 Revision A/B，正常路径恒为 MEMBERSHIP；保留分支是为了让
    本模块在"未跑迁移"的独立场景下仍给出可解释的期望值，而不是写死一个
    只在测试库成立的字面量。
    """
    with SessionLocal() as db:
        available = wc.membership_table_available(db)
    return wc.SOURCE_MEMBERSHIP if available else wc.SOURCE_LEGACY


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _tenant_id(username: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        assert user is not None, "种子数据缺少用户"
        return user.tenant_id


def test_three_endpoints_require_login(client):
    assert client.get("/api/me/workspaces").status_code == 401
    assert client.get("/api/me/workspace-context").status_code == 401
    assert client.post("/api/me/workspaces/1/switch").status_code == 401


def test_admin_workspace_list_matches_contract(client, auth_headers):
    r = client.get("/api/me/workspaces", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"items", "total"}
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert set(item) == WORKSPACE_ITEM_FIELDS
    assert isinstance(item["id"], int)
    assert item["id"] == _tenant_id("admin")
    assert item["kind"] == "ORGANIZATION"
    assert item["role"] == "OWNER"
    assert item["source"] == _expected_source()
    assert item["is_active"] is True


def test_admin_context_matches_contract_without_pii(client, auth_headers):
    r = client.get("/api/me/workspace-context", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == CONTEXT_FIELDS
    assert "username" not in body
    assert "password_hash" not in body
    assert body["role"] == "OWNER"
    assert body["source"] == _expected_source()
    assert isinstance(body["permissions"], list)
    assert "workspace:member:admin" in body["permissions"]
    assert body["trace_id"]


def test_viewer_context_is_read_only(client):
    headers = _login(client, "viewer", "viewer123")
    r = client.get("/api/me/workspace-context", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "READ_ONLY"
    assert body["permissions"], "READ_ONLY 必须至少有读权限"
    assert all(p.endswith(":read") for p in body["permissions"]), body["permissions"]


def test_operator_can_write_but_not_admin(client):
    headers = _login(client, "ops", "ops123")
    r = client.get("/api/me/workspace-context", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "OPERATOR"
    assert "order:write" in body["permissions"]
    assert "workspace:member:admin" not in body["permissions"]


def test_platform_identity_has_no_workspace_and_switch_forbidden(client):
    headers = _login(client, "root", "root-test-123")
    r = client.get("/api/me/workspaces", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "total": 0}

    ctx = client.get("/api/me/workspace-context", headers=headers)
    assert ctx.status_code == 200, ctx.text
    assert ctx.json()["workspace_id"] is None
    assert ctx.json()["source"] == "PLATFORM"

    switch = client.post("/api/me/workspaces/1/switch", headers=headers)
    assert switch.status_code == 403, switch.text


def test_impersonated_context_is_not_platform_and_flags_impersonation(client):
    """缺陷回归：代客进入租户后，Context 必须是「租户身份 + is_impersonating=True」。

    修复前 `me.py` 未把代客标记透传给 `resolve_workspace_context`，于是代客态被判成
    Platform 身份（workspace_id=None、source=PLATFORM）。前端据此无法区分
    「平台本尊」与「代客进入」，也就无法显示「返回平台控制台」。
    """
    root = _login(client, "root", "root-test-123")
    tenant_id = _tenant_id("admin")

    r = client.post(f"/api/admin/tenants/{tenant_id}/enter", headers=root)
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    ctx = client.get("/api/me/workspace-context", headers=headers)
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert body["source"] != "PLATFORM", f"代客态被误判为平台身份: {body}"
    assert body["is_impersonating"] is True, body
    assert body["workspace_id"] == tenant_id, body


def test_impersonated_session_consistent_across_all_me_endpoints(client):
    """代客标记必须在三个 /api/me/* 端点上一致透传。

    契约守护（非可复现缺陷回归，已如实标注）：`/workspaces` 与 `/switch` 此前
    未透传 `is_impersonating`，只有 `/workspace-context` 传了。当前**无可观测
    差异**——因为代客态 role 固定为 `operator`，不会落进 Platform 分支。
    但这是脆弱的隐式依赖：一旦代客角色改成保留原角色（或 Platform 分支条件
    调整），两个端点会立刻返回空集合 / 403，而 Context 仍然正确，形成
    「同一会话三个端点互相矛盾」的难查故障。本用例把三者锁成一致。
    """
    root = _login(client, "root", "root-test-123")
    tenant_id = _tenant_id("admin")
    entered = client.post(f"/api/admin/tenants/{tenant_id}/enter", headers=root)
    assert entered.status_code == 200, entered.text
    impersonated = {"Authorization": f"Bearer {entered.json()['token']}"}

    listed = client.get("/api/me/workspaces", headers=impersonated)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1, listed.json()
    assert listed.json()["items"][0]["id"] == tenant_id, listed.json()

    switched = client.post(f"/api/me/workspaces/{tenant_id}/switch", headers=impersonated)
    assert switched.status_code == 200, switched.text
    assert switched.json()["source"] != "PLATFORM", switched.json()

    # 三个端点的身份必须一致（同一会话不能给出互相矛盾的 Workspace 视图）
    ctx = client.get("/api/me/workspace-context", headers=impersonated).json()
    assert ctx["workspace_id"] == tenant_id
    assert ctx["is_impersonating"] is True


def test_admin_switch_to_own_workspace_is_idempotent_success(client, auth_headers):
    tenant_id = _tenant_id("admin")
    r = client.post(f"/api/me/workspaces/{tenant_id}/switch", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"ok", "workspace_id", "role", "source"}
    assert body["ok"] is True
    assert body["workspace_id"] == tenant_id
    assert body["role"] == "OWNER"
    assert body["source"] == _expected_source()


def test_admin_switch_to_unknown_workspace_is_not_found(client, auth_headers):
    r = client.post("/api/me/workspaces/99999/switch", headers=auth_headers)
    assert r.status_code == 404, r.text


def test_failed_switch_does_not_change_context(client, auth_headers):
    before = client.get("/api/me/workspace-context", headers=auth_headers).json()
    failed = client.post("/api/me/workspaces/99999/switch", headers=auth_headers)
    assert failed.status_code == 404
    after = client.get("/api/me/workspace-context", headers=auth_headers).json()
    assert after["workspace_id"] == before["workspace_id"]
    assert after["source"] == before["source"]
    assert after["role"] == before["role"]


def test_factory_portal_account_reaches_read_only_context(client, auth_headers):
    """工厂门户账号可读自己的 Context，但拿不到写语义端点（G-3）。

    背景（本用例前身固化的是 403）：Phase 1.8 的身份解析以 Context 为权威源、
    legacy `localStorage` 仅作兜底。工厂账号此前被 auth 路径门禁挡在 `/api/me/*`
    之外，Context 永远为空 —— 这使前端**只能**依赖 legacy 兜底，成为
    「删除旧入口」卡住的唯一前置。

    现在放行**只读**端点（`/api/me/workspaces`、`/api/me/workspace-context`），
    同时刻意**不放行** `/switch`（写语义）：工厂的活动 Workspace 由
    `SupplierPortalMember` 唯一确定，不存在可切换的第二个 Workspace，
    放行只会扩大攻击面。三条断言一起锁死这个边界。
    """
    from app.auth import hash_password
    from app.models import Supplier, SupplierPortalMember
    from app.routers.me import _accessible_workspaces
    from app.services import workspace_context as wc

    with SessionLocal() as db:
        tenant_id = _tenant_id("admin")
        # 幂等清理：本用例自带建/删数据，重复运行或残留数据都不应影响结果
        for stale in db.query(Supplier).filter(
                Supplier.tenant_id == tenant_id, Supplier.name == "api-ctx-factory").all():
            db.query(SupplierPortalMember).filter(
                SupplierPortalMember.supplier_id == stale.id).delete()
            db.delete(stale)
        db.query(User).filter(User.username == "api_ctx_portal").delete()
        db.flush()
        supplier = Supplier(tenant_id=tenant_id, name="api-ctx-factory")
        db.add(supplier)
        db.flush()
        account = User(tenant_id=tenant_id, username="api_ctx_portal",
                       password_hash=hash_password("portal-pass-123"),
                       display_name="门户工厂", role="supplier", status="active")
        db.add(account)
        db.flush()
        db.add(SupplierPortalMember(tenant_id=tenant_id, supplier_id=supplier.id,
                                    user_id=account.id))
        db.commit()
        supplier_id, account_id = supplier.id, account.id
        factory_ctx = wc.resolve_workspace_context(db, account)

    # Router 层：Factory Collaborator 只能看到自己的 Factory Workspace
    items = _accessible_workspaces(factory_ctx)
    assert len(items) == 1
    assert set(items[0]) == WORKSPACE_ITEM_FIELDS
    # Service 既有语义：Factory Workspace 的 id 取 supplier.tenant_id
    assert items[0]["id"] == factory_ctx.workspace_id
    assert items[0]["kind"] == "FACTORY"
    assert items[0]["role"] == "FACTORY_COLLABORATOR"
    assert items[0]["source"] == "FACTORY"

    try:
        headers = _login(client, "api_ctx_portal", "portal-pass-123")
        # 1) 只读端点放行：列表与 Context 都能取到（前端身份解析的权威源）
        r = client.get("/api/me/workspaces", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 1
        assert r.json()["items"][0]["source"] == "FACTORY"
        ctx_resp = client.get("/api/me/workspace-context", headers=headers)
        assert ctx_resp.status_code == 200, ctx_resp.text
        assert ctx_resp.json()["role"] == "FACTORY_COLLABORATOR"
        assert ctx_resp.json()["source"] == "FACTORY"
        assert ctx_resp.json()["permissions"] == ["supply:read", "supply:write"]
        # 2) 写语义端点仍被拒（工厂无「可切换」的 Workspace）
        switch = client.post(
            f"/api/me/workspaces/{factory_ctx.workspace_id}/switch", headers=headers)
        assert switch.status_code == 403, switch.text
        # 3) 业务 API 边界未被放宽：工厂账号依旧进不去
        assert client.get("/api/suppliers", headers=headers).status_code == 403
    finally:
        with SessionLocal() as db:
            db.query(SupplierPortalMember).filter(
                SupplierPortalMember.user_id == account_id).delete()
            db.query(User).filter(User.id == account_id).delete()
            db.query(Supplier).filter(Supplier.id == supplier_id).delete()
            db.commit()
