"""权限矩阵与跨租户隔离回归测试（固化 scripts/security_data_audit.py 的排查能力）。

会话级夹具（client / auth_headers / 测试库清理）由 tests/conftest.py 自动注入，
本模块不 import 其它测试模块，避免收集顺序依赖（规范 §8 T-2）。
"""


def _login_role(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_role_permission_matrix(client):
    """4 角色 × 代表性端点：拦截/放行符合 RBAC 预期（viewer 只读、
    operator/admin 可写、/auth/users 仅 admin、/admin/* 仅 superadmin）。"""
    roles = {"viewer": _login_role(client, "viewer", "viewer123"),
             "operator": _login_role(client, "ops", "ops123"),
             "admin": _login_role(client, "admin", "admin123"),
             "superadmin": _login_role(client, "root", "root-test-123")}

    # (方法, 路径, body, 类别)
    # platform_read  = 平台级只读配置（所有角色可读）
    # platform_admin = 平台级配置写入（仅 admin/superadmin）
    probes = [
        ("GET", "/api/products", None, "read"),
        ("GET", "/api/shops", None, "read"),
        ("GET", "/api/listings/999999/publication-attempts", None, "read"),
        ("PUT", "/api/shops/999999", {"market": "TR", "fulfillment_mode": "DROPSHIP"}, "write"),
        ("POST", "/api/products", {"title": "probe-matrix"}, "write"),
        ("POST", "/api/products/999999/standardize", None, "write"),
        ("POST", "/api/discovery/score/999999", None, "write"),
        ("POST", "/api/discovery/trends/scan", None, "write"),
        ("POST", "/api/discovery/pick", {"limit": 1}, "write"),
        ("POST", "/api/listings/999999/review", None, "write"),
        ("POST", "/api/compliance/check", {"target_type": "listing", "ref_id": 999999}, "write"),
        ("POST", "/api/listings/999999/review/approve", {"note": "权限探针"}, "compliance_approve"),
        ("GET", "/api/orders", None, "read"),
        ("GET", "/api/pricing", None, "read"),
        ("POST", "/api/pricing/suggest", {"product_id": 999999}, "write"),
            ("GET", "/api/actions", None, "write"),
            ("GET", "/api/actions?action_type=PUBLISH_LISTING", None, "write"),
        ("GET", "/api/actions?action_type=CREATE_AD_CAMPAIGN_DRAFT", None, "write"),
        ("GET", "/api/actions?action_type=UPDATE_PRODUCT_CONTENT", None, "write"),
        ("POST", "/api/schedules/999999/run", None, "write"),
        ("POST", "/api/actions/999999/approve", {"note": "权限探针"}, "write"),
        ("POST", "/api/actions/999999/execute", None, "write"),
        ("POST", "/api/orders/sync", {"platform": "demo:shopee", "count": 1}, "write"),
        ("GET", "/api/ai/settings", None, "platform_read"),
        ("PUT", "/api/ai/settings", {"rules": {}}, "platform_admin"),
        ("GET", "/api/auth/users", None, "admin"),
        ("GET", "/api/admin/tenants", None, "superadmin"),
        ("GET", "/api/admin/ai_logs", None, "superadmin"),
        ("POST", "/api/admin/tenants", {"name": "probe-t"}, "superadmin"),
        # M4 客服知识自进化（此前完全未纳入权限矩阵，viewer 是否被拦住无覆盖）：
        # 读端点走 get_current_user（viewer 可读），写端点走 require_write（viewer 拦）。
        ("GET", "/api/knowledge/candidates", None, "read"),
        ("GET", "/api/knowledge/learning/settings", None, "read"),
        ("PUT", "/api/knowledge/learning/settings",
         {"auto_learn_enabled": False}, "write"),
        ("POST", "/api/knowledge/candidates/999999/answer", {"answer": "x"}, "write"),
        ("POST", "/api/knowledge/candidates/999999/approve", {"answer": "x"}, "write"),
        ("POST", "/api/knowledge/candidates/999999/reject", None, "write"),
        ("POST", "/api/knowledge/candidates/999999/revoke", None, "write"),
    ]
    expect_gate = {
        "viewer": {"write", "admin", "superadmin", "platform_admin", "compliance_approve"},
        "operator": {"admin", "superadmin", "platform_admin", "compliance_approve"},
        "admin": {"superadmin"},
        # superadmin 是平台身份，没有业务 Workspace：租户业务接口（read/write/admin）
        # 一律 403，必须先经 /api/admin/tenants/{id}/enter 代客进入。
        # 平台级端点（/api/admin/*、平台规则、AI 设置）仍可直达。
        "superadmin": {"read", "write", "admin", "compliance_approve"},
    }
    # 清理探测残留
    created_products = []

    for role, hdrs in roles.items():
        for method, path, body, category in probes:
            if method == "GET":
                r = client.get(path, headers=hdrs)
            elif method == "POST":
                r = client.post(path, json=body, headers=hdrs)
            else:
                r = client.put(path, json=body, headers=hdrs)
            gated = r.status_code in (401, 403)
            should_gate = category in expect_gate[role]
            assert gated == should_gate, \
                f"[{role}] {method} {path} ({category}): status={r.status_code}, 应{'拦' if should_gate else '放'}"
            if role == "admin" and method == "POST" and path == "/api/products":
                created_products.append(r.json()["id"])

    for pid in created_products:
        admin_h = roles["admin"]
        client.delete(f"/api/products/{pid}", headers=admin_h)

def test_allowed_knowledge_reject_reaches_business_validation(client):
    # 写端点被放行的角色必须真正执行业务校验（而非被权限层拦下）：
    # 不存在的候选应返回 404「不存在」，证明请求已抵达业务逻辑。
    for username, password in [("admin", "admin123"), ("ops", "ops123")]:
        headers = _login_role(client, username, password)
        r = client.post("/api/knowledge/candidates/999999/reject", headers=headers)
        assert r.status_code == 404 and "不存在" in r.json()["detail"], r.text


def test_cross_tenant_isolation(client, fetch_all):
    """A 租户不能看到/读写 B 租户的商品、订单、知识库、AI 日志。"""
    sa = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'root', 'password': 'root-test-123'}).json()['token']}"}
    # 开通 B 租户
    r = client.post("/api/admin/tenants", headers=sa,
                    json={"name": "隔离测试B", "license_days": 365,
                          "admin_username": "iso_b2", "admin_password": "iso-b2-pass"})
    tid_b = r.json()["id"]
    hb = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'iso_b2', 'password': 'iso-b2-pass'}).json()['token']}"}
    ha = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'}).json()['token']}"}

    # B 造专属商品 + 订单
    pid_b = client.post("/api/products", headers=hb,
                        json={"title": "B专属隔离探针商品"}).json()["id"]
    client.post("/api/orders/sync", headers=hb, json={"platform": "demo:shopee", "count": 2})
    campaign_b = client.post("/api/ads/campaigns", headers=hb,
                             json={"name": "B专属广告", "budget": 80}).json()["id"]
    action_b = client.post(f"/api/ads/campaigns/{campaign_b}/optimize",
                           headers=hb).json()["action_id"]
    user_b = client.post("/api/auth/users", headers=hb,
                         json={"username": "iso_b_operator", "password": "iso-pass-123",
                               "role": "operator"}).json()

    issues = []
    if any(item["id"] == action_b for item in client.get(
            "/api/actions", headers=ha).json()["items"]):
        issues.append("跨租户 Action 审批队列泄漏")
    if client.post(f"/api/actions/{action_b}/approve", headers=ha,
                   json={"note": "越权探针"}).status_code == 200:
        issues.append("跨租户审批 Action")
    # A 商品列表无 B 商品
    a_items = fetch_all("/api/products", ha)
    if any(p["id"] == pid_b for p in a_items):
        issues.append("商品列表泄漏")
    # A 读 B 商品详情 -> 404
    if client.get(f"/api/products/{pid_b}", headers=ha).status_code == 200:
        issues.append("跨租户读商品")
    # A 改 B 商品 -> 非 200
    if client.put(f"/api/products/{pid_b}", headers=ha, json={"title": "x"}).status_code == 200:
        issues.append("跨租户改商品")
    # 订单无交集
    oa = {o["id"] for o in fetch_all("/api/orders", ha)}
    ob = {o["id"] for o in fetch_all("/api/orders", hb)}
    if oa & ob:
        issues.append("订单跨租户重叠")
    # A 对 B 订单发货 -> 非 200
    if ob:
        r = client.post(f"/api/orders/{min(ob)}/ship", headers=ha)
        if r.status_code == 200:
            issues.append("跨租户发货")
    # 知识库无交集
    kb = {d["id"] for d in fetch_all("/api/knowledge/docs", hb)}
    ka = {d["id"] for d in fetch_all("/api/knowledge/docs", ha)}
    if kb & ka:
        issues.append("知识库跨租户重叠")
    # B 的 AI 日志全是自己租户的
    logs = client.get("/api/ai/logs", headers=hb, params={"limit": 200}).json()["items"]
    if any(row["tenant_id"] != tid_b for row in logs):
        issues.append("AI 日志混入他租户")
    # 用户管理同样必须租户隔离：A 不可见、不可修改、不可删除 B 用户。
    users_a = client.get("/api/auth/users", headers=ha).json()["items"]
    if any(u["id"] == user_b["id"] for u in users_a):
        issues.append("用户列表跨租户泄漏")
    if client.put(f"/api/auth/users/{user_b['id']}", headers=ha,
                  json={"display_name": "hacked"}).status_code == 200:
        issues.append("跨租户修改用户")
    if client.delete(f"/api/auth/users/{user_b['id']}", headers=ha).status_code == 200:
        issues.append("跨租户删除用户")

    # AI 原生能力（M1/M3）的归属校验：这些接口会**写库**（表现分缓存、
    # 告警确认、规则修改），越权比只读泄漏更严重，必须有回归守卫。
    if client.get(f"/api/discovery/performance/{pid_b}",
                  headers=ha).status_code == 200:
        issues.append("跨租户读商品表现分")
    # 表现分接口若越权成功会在他租户名下写入缓存行，必须校验未写入
    from app.db import SessionLocal
    from app.models import ProductPerformance

    with SessionLocal() as _db:
        if _db.query(ProductPerformance).filter(
                ProductPerformance.product_id == pid_b).count():
            issues.append("表现分跨租户污染缓存")

    # 报价必须校验商品归属：只查存在性时 A 可把报价挂到 B 商品上
    sup_a = client.get("/api/suppliers", headers=ha,
                       params={"page_size": 1}).json()["items"]
    if sup_a:
        r = client.post("/api/suppliers/offers", headers=ha, json={
            "supplier_id": sup_a[0]["id"], "product_id": pid_b, "price": 9.9})
        if r.status_code == 200:
            issues.append("跨租户给他人商品挂报价")

    # 告警确认 / 规则修改必须租户隔离
    alerts_b = client.get("/api/alerts", headers=hb).json()["items"]
    if alerts_b:
        if client.put(f"/api/alerts/{alerts_b[0]['id']}/ack",
                      headers=ha).status_code == 200:
            issues.append("跨租户确认告警")
    rules_b = client.get("/api/alerts/rules", headers=hb).json()["items"]
    if rules_b:
        if client.put(f"/api/alerts/rules/{rules_b[0]['id']}", headers=ha,
                      json={"enabled": False}).status_code == 200:
            issues.append("跨租户修改巡检规则")

    # 清理
    client.delete(f"/api/products/{pid_b}", headers=hb)
    assert issues == [], f"跨租户隔离缺陷: {issues}"


def test_oauth_state_and_encrypted_credentials(client, auth_headers):
    """OAuth state 必须一次性消费，平台凭证不得以明文落库。"""
    from urllib.parse import parse_qs, urlsplit

    from app.db import engine

    shop = client.post("/api/shops", headers=auth_headers, json={
        "platform": "ebay", "shop_name": "安全测试店", "app_key": "secure-key",
        "app_secret": "plain-secret-must-not-exist", "shop_id": "test-runame"}).json()
    url = client.get(f"/api/shops/{shop['id']}/authorize_url", headers=auth_headers)
    assert url.status_code == 200
    state = parse_qs(urlsplit(url.json()["authorize_url"]).query)["state"][0]
    assert len(state) >= 32 and state != str(shop["id"])

    denied = client.get(f"/api/shops/callback/ebay/{shop['id']}",
                        params={"state": state, "error": "access_denied"},
                        follow_redirects=False)
    # 原断言 `in (302, 307)` 无法区分「授权拒绝后跳回店铺页」与「任意跳转/路由错」。
    # 实测契约：状态落 failed 并 307 跳 /shops?auth=failed。
    assert denied.status_code == 307, denied.text
    assert denied.headers["location"] == "/shops?auth=failed"
    replay = client.get(f"/api/shops/callback/ebay/{shop['id']}",
                        params={"state": state, "error": "access_denied"},
                        follow_redirects=False)
    assert replay.status_code == 400
    with engine.connect() as conn:
        raw = conn.exec_driver_sql("SELECT app_secret FROM shops WHERE id=?", (shop["id"],)).scalar()
    assert raw.startswith("enc:v1:") and "plain-secret" not in raw
    client.delete(f"/api/shops/{shop['id']}", headers=auth_headers)


def test_login_lock_and_token_revocation(client, auth_headers):
    created = client.post("/api/auth/users", headers=auth_headers, json={
        "username": "token_revoke_user", "password": "old-secure-pass",
        "role": "viewer"}).json()
    logged = client.post("/api/auth/login", json={
        "username": "token_revoke_user", "password": "old-secure-pass"})
    old_headers = {"Authorization": f"Bearer {logged.json()['token']}"}
    assert client.get("/api/auth/me", headers=old_headers).status_code == 200
    client.put(f"/api/auth/users/{created['id']}", headers=auth_headers,
               json={"password": "new-secure-pass"})
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401
    assert client.post("/api/auth/login", json={
        "username": "token_revoke_user", "password": "new-secure-pass"}).status_code == 200

    for _ in range(5):
        client.post("/api/auth/login", json={"username": "unknown-lock-probe", "password": "bad"})
    locked = client.post("/api/auth/login", json={
        "username": "unknown-lock-probe", "password": "bad"})
    assert locked.status_code == 429
    client.delete(f"/api/auth/users/{created['id']}", headers=auth_headers)


def test_data_consistency_after_flows(client, auth_headers, fetch_all):
    """跑过采购/售后流程后：退款-订单状态联动、结算单时间戳、订单 source 合法值。"""

    # 造订单并完成整单退款
    r = client.post("/api/orders/sync", headers=auth_headers,
                    json={"platform": "demo:shopee", "count": 1})
    o = r.json()["items"][0]
    client.put(f"/api/orders/{o['id']}/status", headers=auth_headers, json={"status": "paid"})
    rid = client.post("/api/refunds", headers=auth_headers,
                      json={"order_id": o["id"], "qty": o["qty"], "type": "refund_only"}).json()["id"]
    client.put(f"/api/refunds/{rid}/status", headers=auth_headers, json={"status": "approved"})
    client.post(f"/api/refunds/{rid}/refund", headers=auth_headers)

    refunds = fetch_all("/api/refunds", auth_headers)
    orders = {x["id"]: x for x in fetch_all("/api/orders", auth_headers)}
    for rf in refunds:
        od = orders.get(rf["order_id"])
        if od is None:
            # 种子退款单可能引用分页窗口外的历史订单，跳过配对（悬空引用由 DB 外键保证）
            continue
        if rf["status"] == "refunded" and rf["qty"] >= od["qty"]:
            assert od["status"] == "refunded", f"整单退款后订单 {od['id']} 未联动"
        assert rf["amount"] <= od["amount"] + 0.01, "退款金额超订单总额"
    valid_source = {"seed", "import", "api", "demo", "manual"}
    for od in orders.values():
        assert od.get("source") in valid_source, f"订单 {od['external_no']} source 非法"
