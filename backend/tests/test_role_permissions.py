"""角色权限矩阵验收（对照 docs/页面操作权限对照表.md）。

设计意图：把「哪个角色能调哪个端点」固化成可执行契约，任何权限漂移
（前端按钮放开但后端没拦、或后端误拦）都会被此文件抓住。

覆盖 6 角色：viewer / operator / admin(OWNER) / compliance_approver / superadmin / supplier。
"""
import pathlib

import pytest

# client / auth_headers 由 tests/conftest.py 提供（会话级夹具），无需显式导入


def _login(client, username: str, password: str):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        return None
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def role_headers(client):
    """6 角色认证头（合规员账号按需创建）。"""
    admin = _login(client, "admin", "admin123")
    assert admin, "admin 登录失败（测试库未就绪）"
    # 合规员账号：不存在则创建
    if not _login(client, "role_probe_comp", "comp-pass-123"):
        client.post("/api/auth/users", headers=admin, json={
            "username": "role_probe_comp", "password": "comp-pass-123",
            "role": "compliance_approver", "display_name": "权限矩阵合规员"})
    return {
        "viewer": _login(client, "viewer", "viewer123"),
        "operator": _login(client, "ops", "ops123"),
        "admin": admin,
        "compliance": _login(client, "role_probe_comp", "comp-pass-123"),
        "superadmin": _login(client, "root", "root-test-123"),
    }


# 端点 → 允许的角色集合（与对照表一致；未列出的角色必须被拦）
PROBES = [
    # (方法, 路径, body, 允许角色集合, 说明)
    ("POST", "/api/compliance/check", {"target_type": "product", "ref_id": 1},
     {"operator", "admin", "compliance"}, "发起合规检测（compliance:check）"),
    ("POST", "/api/products", {"title": "权限矩阵探针"},
     {"operator", "admin"}, "商品写（product:write）"),
    ("POST", "/api/listings/generate", {"product_id": 1},
     {"operator", "admin"}, "Listing 生成（listing:write）"),
    ("POST", "/api/auth/users", {"username": "probe_role_x", "password": "x12345678", "role": "viewer"},
     {"admin"}, "用户管理（workspace:member:admin）"),
    # 读端点：合规员也在白名单内（对照表 §2：COMPLIANCE 有 compliance:read /
    # listing:read / product:read；BI 看板与商品列表属其可读范围）
    ("GET", "/api/bi/dashboard", None,
     {"viewer", "operator", "admin", "compliance"}, "经营看板（读权限）"),
    ("GET", "/api/products", None,
     {"viewer", "operator", "admin", "compliance"}, "商品列表（读权限）"),
]


def test_permission_matrix_by_role(client, role_headers):
    """6 角色 × 端点：放行/拦截必须与对照表一致。"""
    violations = []
    for method, path, body, allowed, desc in PROBES:
        for rname, hdrs in role_headers.items():
            if hdrs is None:
                violations.append(f"{rname} 未登录（测试前置失败）")
                continue
            r = (client.post(path, json=body, headers=hdrs) if method == "POST"
                 else client.get(path, headers=hdrs))
            gated = r.status_code in (401, 403)
            expect_gate = rname not in allowed
            if gated != expect_gate:
                violations.append(
                    f"{desc}: {rname} {path} 期望{'拦截' if expect_gate else '放行'} "
                    f"实际 {r.status_code} {r.text[:80]}")
    assert not violations, "权限矩阵违规：\n" + "\n".join(violations)


def test_compliance_role_can_check_but_not_write_business(client, role_headers):
    """合规员职责边界：可发起检测、可审批；不能改商品、不能发布、不能管用户。"""
    h = role_headers["compliance"]
    assert h, "合规员登录失败"
    # 可发起检测（本轮新增能力）
    r = client.post("/api/compliance/check", headers=h,
                    json={"target_type": "product", "ref_id": 1})
    assert r.status_code == 200, f"合规员应可发起检测: {r.status_code} {r.text[:80]}"
    # 不能改商品
    r = client.post("/api/products", headers=h, json={"title": "合规员不应能建商品"})
    assert r.status_code == 403
    # 不能生成/发布 Listing
    r = client.post("/api/listings/generate", headers=h, json={"product_id": 1})
    assert r.status_code == 403
    # 不能管用户
    r = client.post("/api/auth/users", headers=h,
                    json={"username": "x", "password": "x12345678", "role": "viewer"})
    assert r.status_code == 403


def test_viewer_has_zero_write_permission(client, role_headers):
    """viewer 对所有写端点必须 403（只读角色的硬边界）。"""
    h = role_headers["viewer"]
    assert h, "viewer 登录失败"
    write_endpoints = [
        ("POST", "/api/products", {"title": "viewer 不应能建"}),
        ("POST", "/api/discovery/trends/scan", None),
        ("POST", "/api/suppliers", {"name": "viewer 不应能建"}),
        ("POST", "/api/listings/generate", {"product_id": 1}),
        ("POST", "/api/compliance/check", {"target_type": "product", "ref_id": 1}),
        ("POST", "/api/orders/sync", {"platform": "demo:shopee", "count": 1}),
        ("POST", "/api/refunds", {"order_id": 1, "qty": 1}),
        ("POST", "/api/settlements/generate", {"supplier_id": 1}),
        ("POST", "/api/knowledge/docs", {"title": "x", "content": "y"}),
        ("POST", "/api/schedules", {"name": "x", "kind": "trend_scan", "interval_minutes": 60}),
        ("POST", "/api/workflows/run", {"template_key": "reprice"}),
        ("POST", "/api/ai/chat", {"message": "hi"}),
    ]
    for method, path, body in write_endpoints:
        # 用 client.request(method, ...) 而不是写死 post：数据表里已经声明了方法，
        # 写死会让"方法列"变成装饰品（新增 GET 端点时不会被真正按方法调用）。
        r = client.request(method, path, json=body, headers=h)
        assert r.status_code == 403, f"viewer 不应能写 {path}：{r.status_code}"


def test_superadmin_has_no_business_permission(client, role_headers):
    """平台身份无业务 Workspace：直接调业务 API 必须 403（需先进入租户）。"""
    h = role_headers["superadmin"]
    assert h, "superadmin 登录失败"
    for path, body in [("/api/products", {"title": "平台身份不应直接写"}),
                       ("/api/compliance/check", {"target_type": "product", "ref_id": 1})]:
        r = client.post(path, json=body, headers=h)
        assert r.status_code == 403, f"平台身份不应能直接写 {path}：{r.status_code}"
    # 平台专属端点可用
    r = client.get("/api/admin/tenants", headers=h)
    assert r.status_code == 200


def test_permission_keys_consistent_with_contract(client, role_headers):
    """Context 权限目录与对照表一致（防前端/后端漂移）。"""
    h = role_headers["admin"]
    ctx = client.get("/api/me/workspace-context", headers=h).json()
    perms = set(ctx.get("permissions", []))
    # 对照表 §1 列出的 key 必须都在（OWNER 拥有全部）
    expected = {
        "workspace:read", "product:read", "supply:read", "listing:read", "order:read",
        "finance:read", "purchase:read", "settlement:read", "refund:read",
        "compliance:read", "ai:read",
        "workspace:write", "product:write", "supply:write", "listing:write", "order:write",
        "finance:write", "purchase:write", "settlement:write", "refund:write", "ai:write",
        "workspace:member:admin", "compliance:approve", "compliance:check",
    }
    missing = expected - perms
    assert not missing, f"OWNER 缺少对照表中的权限 key：{sorted(missing)}"
    # 合规员权限必须精确（不能多出写权限）
    ch = role_headers["compliance"]
    cctx = client.get("/api/me/workspace-context", headers=ch).json()
    cperms = set(cctx.get("permissions", []))
    assert "compliance:check" in cperms and "compliance:approve" in cperms
    assert not [p for p in cperms if p.endswith(":write")], \
        f"合规员不应有写权限：{sorted(p for p in cperms if p.endswith(':write'))}"

# ============================================================ 前后端权限契约（专家探讨 P3）

_FRONTEND_PERMISSIONS = (pathlib.Path(__file__).resolve().parent.parent.parent
                         / "frontend" / "src" / "permissions.js")


def test_frontend_legacy_capabilities_match_backend_matrix():
    """契约测试（D24 后）：前端**不得**存在第二份「角色→权限」表。

    历史（本测试前身）：前端曾用 `LEGACY_CAPABILITIES` 手工维护一份角色→权限
    映射，作为 Context 不可用时的兜底；本测试双向比对它与后端 `ROLE_PERMISSIONS`
    的一致性。D24 采纳「只读降级」后该常量**已整体删除**——Context 不可用时
    写权限一律 false，不再有任何前端兜底表。

    因此守护点从「两张表一致」变成「**不存在第二份表**」：
      1. 前端不得重新引入 `LEGACY_CAPABILITIES`（回退会静默恢复 legacy 授权，
         等于把 D24 的收口推翻，且前端伪造 `erp_user.role` 会再次获得写权限）；
      2. 写权限判定必须走 `hasPermission()`，且缺失时 fail-closed（`?? false`）。
    """
    import re

    assert _FRONTEND_PERMISSIONS.is_file(), f"前端权限文件不存在：{_FRONTEND_PERMISSIONS}"
    text = _FRONTEND_PERMISSIONS.read_text(encoding="utf-8")

    # 1) 禁止重新引入前端权限兜底表（D24）
    assert "LEGACY_CAPABILITIES" not in text, (
        "前端重新引入了 LEGACY_CAPABILITIES 兜底表——D24 已将其删除，"
        "Context 不可用时写权限必须 fail-closed（见 docs/DECISIONS.md D24）")

    # 2) 能力判定必须 fail-closed：hasPermission 为 null（Context 不可用）时返回 false
    assert re.search(r"hasPermission\(capability\)[\s\S]{0,200}?return false", text), (
        "前端 can() 未 fail-closed：Context 不可用时必须返回 false，"
        "禁止回退到任何 legacy 角色判定")
    for fn, key in (("canWrite", "order:write"),
                    ("canAdmin", "workspace:member:admin"),
                    ("canApprove", "compliance:approve")):
        pattern = rf"export const {fn} = \(\) => hasPermission\('{re.escape(key)}'\) \?\? false"
        assert re.search(pattern, text), (
            f"前端 {fn}() 未按 D24 fail-closed（期望 `hasPermission('{key}') ?? false`）")


def test_backend_has_no_orphan_write_permission():
    """后端不应有「前端完全未使用」的写权限 key（防止加了 key 但页面没接）。

    为什么改成扫**整个 src/**：D24 之前前端把写权限 key 集中列在
    `LEGACY_CAPABILITIES` 里，扫一个文件即可；该常量删除后，key 只出现在
    真正使用它的视图里（如 `Orders.vue` 的 `can('order:write')`）。
    若仍只扫 `permissions.js`，所有写权限都会被误报为 orphan——那不是缺陷，
    而是扫描范围没跟上设计变更。
    """
    from app.services.workspace_context import ROLE_PERMISSIONS

    all_write = set()
    for keys in ROLE_PERMISSIONS.values():
        all_write |= {k for k in keys if k.endswith(":write")}

    src_dir = _FRONTEND_PERMISSIONS.parent
    used = set()
    for path in src_dir.rglob("*"):
        if path.is_file() and path.suffix in (".js", ".vue"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for key in all_write:
                if f"'{key}'" in text or f'"{key}"' in text:
                    used.add(key)
    unused = sorted(all_write - used)
    assert not unused, (
        f"以下写权限 key 未被前端任何页面使用（后端已定义但页面没接）：{unused}")
