"""经营画像服务端持久化（D63 / V9.1 原型 02）端到端验证。

验收口径（对应 docs/CONTRACT.md 的 business-profile 契约卡）：
  1. save → 新请求读回一致；
  2. 重新登录（新 token）读回一致；
  3. 同工作区内用户 A 的个人字段对用户 B 不可见；
  4. 跨工作区（当前实现：legacy 路径 workspace_id = user.tenant_id）完全不串数据；
  5. 客户端传入的 workspace_id 被服务端忽略；
  6. 幂等 upsert：等价两次 PUT 只有一行；
  7. 非法输入 422 且点名字段；
  8. completed 由服务端按必填字段推导，客户端声明不可信。

夹具沿用 conftest 的 client / auth_headers（admin/admin123）。辅助用户经
hash_password + /api/auth/login 走真实登录拿 token，不做任何注入捷径。
"""
from app.auth import hash_password
from app.db import SessionLocal
from app.models import BusinessProfile, Tenant, User


def _admin_tenant_id(db):
    return db.query(User).filter(User.username == "admin").first().tenant_id


def _make_user_and_headers(client, db, tenant_id, username, password="Passw0rd!"):
    """真实建号 + 真实登录拿 Bearer 头（验证「重新登录读回一致」的唯一可信方式）。"""
    user = User(tenant_id=tenant_id, username=username,
                password_hash=hash_password(password), role="operator",
                display_name=username)
    db.add(user)
    db.commit()
    r = client.post("/api/auth/login", json={"username": username,
                                             "password": password})
    assert r.status_code == 200, r.text
    return user, {"Authorization": f"Bearer {r.json()['token']}"}


def _put(client, headers, **body):
    return client.put("/api/business-profile", headers=headers, json=body)


def _get(client, headers):
    return client.get("/api/business-profile", headers=headers)


FULL_PROFILE = {"direction": "A", "budget_amount": 5000.0, "budget_currency": "USD",
                "target_market": "东南亚", "risk": "中"}


def test_put_then_get_readback_identical(client, auth_headers):
    """save → 新请求 GET 读回一致；sources 标注正确。"""
    r = _put(client, auth_headers, **FULL_PROFILE)
    assert r.status_code == 200, r.text
    g = _get(client, auth_headers)
    assert g.status_code == 200, g.text
    body = g.json()
    assert body["direction"] == "A"
    assert body["budget"] == {"amount": 5000.0, "currency": "USD"}
    assert body["target_market"] == "东南亚"
    assert body["risk"] == "中"
    assert body["completed"] is True
    assert body["sources"] == {"direction": "USER", "target_market": "WORKSPACE",
                               "risk": "WORKSPACE"}


def test_fresh_login_reads_back_same(client, auth_headers):
    """重新登录（全新 token）后画像读回一致——不依赖客户端任何缓存。"""
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        db.commit()
    finally:
        db.close()
    assert _put(client, auth_headers, **FULL_PROFILE).status_code == 200
    # 与 conftest.auth_headers 相同方式再登录一次，拿一个全新的 token
    r = client.post("/api/auth/login", json={"username": "admin",
                                             "password": "admin123"})
    assert r.status_code == 200, r.text
    fresh = {"Authorization": f"Bearer {r.json()['token']}"}
    body = _get(client, fresh).json()
    assert body["direction"] == "A"
    assert body["budget"] == {"amount": 5000.0, "currency": "USD"}
    assert body["target_market"] == "东南亚"
    assert body["risk"] == "中"
    assert body["completed"] is True


def test_personal_fields_isolated_between_users(client, auth_headers):
    """同租户用户 B 看得到共享字段，但绝看不到用户 A 的个人字段。"""
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        _, headers_b = _make_user_and_headers(client, db, tenant_id,
                                              "profile_user_b")
    finally:
        db.close()
    assert _put(client, auth_headers, **FULL_PROFILE).status_code == 200
    body = _get(client, headers_b).json()
    # 共享字段：空间内可见
    assert body["target_market"] == "东南亚"
    assert body["risk"] == "中"
    assert body["sources"]["target_market"] == "WORKSPACE"
    # 个人字段：A 的绝不能泄漏给 B
    assert body["direction"] is None
    assert body["budget"] == {"amount": None, "currency": None}
    assert body["sources"]["direction"] is None
    assert body["completed"] is False  # B 自己的画像未完成


def test_workspace_isolation_no_cross_tenant_leak(client, auth_headers):
    """租户 2（legacy 路径下即另一工作区）读不到租户 1 的任何画像字段。

    注意：这里直接 Tenant 建租户后必须调用 ensure_workspace_profile 保持
    「租户 ↔ workspace_profile 1:1 配对」不变量——否则自增 id 序列错位，
    会弄断 test_membership_write 对 endpoint 开通租户的
    workspace_id == tenant_id 金丝雀断言（全量回归实测过）。
    """
    db = SessionLocal()
    try:
        from app.services.membership_service import ensure_workspace_profile
        other = Tenant(name="画像隔离租户")
        db.add(other)
        db.flush()
        ensure_workspace_profile(db, other.id, other.name)
        _, headers_c = _make_user_and_headers(client, db, other.id,
                                              "profile_user_c")
    finally:
        db.close()
    assert _put(client, auth_headers, **FULL_PROFILE).status_code == 200
    body = _get(client, headers_c).json()
    assert body["direction"] is None
    assert body["budget"] == {"amount": None, "currency": None}
    assert body["target_market"] is None
    assert body["risk"] is None
    assert body["completed"] is False


def test_client_workspace_id_is_ignored(client, auth_headers):
    """客户端塞进请求体的 workspace_id 必须被忽略（服务端 Context 唯一事实）。"""
    r = client.put("/api/business-profile", headers=auth_headers,
                   json={**FULL_PROFILE, "workspace_id": 999999})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        # 所有行都必须归属本租户；不存在 tenant_id=999999 的孤儿行
        rows = (db.query(BusinessProfile)
                .filter(BusinessProfile.tenant_id == tenant_id).all())
        assert rows, "应至少落库一行"
        assert all(row.workspace_id == tenant_id for row in rows), \
            [row.workspace_id for row in rows]
        orphans = (db.query(BusinessProfile)
                   .filter(BusinessProfile.workspace_id == 999999).all())
        assert not orphans
    finally:
        db.close()


def test_idempotent_upsert_single_row(client, auth_headers):
    """等价两次 PUT：读回一致，且个人行只有一行（仅刷新 updated_at）。"""
    assert _put(client, auth_headers, **FULL_PROFILE).status_code == 200
    first = _get(client, auth_headers).json()
    assert _put(client, auth_headers, **FULL_PROFILE).status_code == 200
    second = _get(client, auth_headers).json()
    assert first["direction"] == second["direction"]
    assert first["budget"] == second["budget"]
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        admin_id = db.query(User).filter(User.username == "admin").first().id
        personal = (db.query(BusinessProfile)
                    .filter(BusinessProfile.tenant_id == tenant_id,
                            BusinessProfile.user_id == admin_id).all())
        assert len(personal) == 1, f"个人行应恰好 1 行，实际 {len(personal)}"
        shared = (db.query(BusinessProfile)
                  .filter(BusinessProfile.tenant_id == tenant_id,
                          BusinessProfile.user_id.is_(None)).all())
        assert len(shared) == 1, f"共享行应恰好 1 行，实际 {len(shared)}"
    finally:
        db.close()


def test_validation_422_names_the_field(client, auth_headers):
    """负数预算 / 未知币种 / 非法风险值 → 422，且报文点名字段。

    币种两态：系统基线币种（USD/EUR/CNY，订单默认 USD、定价 CNY 计价）恒定可用，
    不依赖任何环境是否配置过汇率；基线之外的未知币种（XYZ）拒绝。
    """
    r = _put(client, auth_headers, budget_amount=-1.0)
    assert r.status_code == 422, r.text
    assert "预算" in r.text
    r = _put(client, auth_headers, budget_currency="XYZ")
    assert r.status_code == 422, r.text
    assert "budget_currency" in r.text or "币种" in r.text
    r = _put(client, auth_headers, risk="非常高")
    assert r.status_code == 422, r.text
    assert "风险" in r.text
    # 合法零值不是缺值：0.0 可写入且与 None 可区分
    r = _put(client, auth_headers, budget_amount=0.0, budget_currency="CNY")
    assert r.status_code == 200, r.text
    assert _get(client, auth_headers).json()["budget"]["amount"] == 0.0


def test_completed_is_server_derived(client, auth_headers):
    """completed 是服务端推导值：客户端声明 true 不生效；字段齐全才翻转。

    会话级测试库在多个用例间共享，admin 的画像可能已被前面的用例写满，
    因此本用例先清空 admin 租户的画像行，保证从「未完成」状态出发（不依赖执行顺序）。
    """
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        db.query(BusinessProfile).filter(
            BusinessProfile.tenant_id == tenant_id).delete()
        db.commit()
    finally:
        db.close()
    r = _put(client, auth_headers, completed=True)
    assert r.status_code == 200, r.text
    body = _get(client, auth_headers).json()
    assert body["completed"] is False, "客户端声明不能伪造完成态"
    # 补齐个人字段 → 仍未完成（共享字段缺失）
    assert _put(client, auth_headers, direction="B", budget_amount=100.0,
                budget_currency="EUR").status_code == 200
    assert _get(client, auth_headers).json()["completed"] is False
    # 补齐共享字段 → 完成
    assert _put(client, auth_headers, target_market="欧美", risk="低")\
        .status_code == 200
    assert _get(client, auth_headers).json()["completed"] is True
    # 显式 null = 清除：清掉共享字段后回到未完成
    assert _put(client, auth_headers, target_market=None).status_code == 200
    body = _get(client, auth_headers).json()
    assert body["target_market"] is None
    assert body["completed"] is False


def test_read_only_account_cannot_write(client, auth_headers):
    """viewer 只读账号 PUT 必须 403（require_write 闸门）。"""
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        _, headers_v = _make_user_and_headers(client, db, tenant_id,
                                              "profile_viewer", password="View0rd!")
        # 提升为 viewer
        u = db.query(User).filter(User.username == "profile_viewer").first()
        u.role = "viewer"
        db.commit()
    finally:
        db.close()
    r = _put(client, headers_v, direction="A")
    assert r.status_code == 403, r.text
