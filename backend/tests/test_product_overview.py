"""商品概览（GET /api/products/{id}/overview）端到端验证。

验收口径（docs/CONTRACT.md overview 契约卡）：
  1. 顶层键严格为 product / supply / channels / performance / stage / generated_at；
  2. channels 形状 == product_channels 端点形状（复用同一函数）；
  3. stage 阶梯：无报价 → NO_SUPPLY 且 reasons 非空；有报价 → 进阶；
  4. 多店独立性：一商品两店渠道都被反映且不互相覆盖；
  5. performance 无可靠数据时为 null（绝不臆造 0）；
  6. 列表 signals：本页 product_id 的批量聚合计数正确。
"""
from app.auth import hash_password
from app.db import SessionLocal
from app.models import (Listing, Product, Shop, Supplier, SupplierOffer, User,
                        WorkflowRun, WorkflowStep)
from app.workflows.contract_profiles import simple_contract


def _admin_tenant_id(db):
    return db.query(User).filter(User.username == "admin").first().tenant_id


def _make_user(client, db, tenant_id, username, password="Passw0rd!"):
    user = User(tenant_id=tenant_id, username=username,
                password_hash=hash_password(password), role="operator",
                display_name=username)
    db.add(user)
    db.commit()
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return user, {"Authorization": f"Bearer {r.json()['token']}"}


def _create_product(client, headers, title="OVW"):
    r = client.post("/api/products", headers=headers,
                    json={"title": title, "sku": title, "category": "cat"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


_SUP_SEQ = [0]


def _create_supplier(client, headers, name=None):
    # suppliers 有 (tenant_id, name, source_url) 唯一约束，且测试库会话级共享——
    # 缺省名必须带序号，跨用例复用缺省名才不会撞约束。
    if name is None:
        _SUP_SEQ[0] += 1
        name = f"OVW-SUP-{_SUP_SEQ[0]}"
    r = client.post("/api/suppliers", headers=headers, json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_offer(client, headers, supplier_id, product_id, price=9.9):
    r = client.post("/api/suppliers/offers", headers=headers,
                    json={"supplier_id": supplier_id, "product_id": product_id, "price": price})
    assert r.status_code == 200, r.text
    return r.json()["id"]


_LAUNCH_SEQ = [0]


def _create_launch(db, tenant_id, product_id, platform="shopee"):
    """建一店 + 一母稿 + 一可渲染 Launch run。

    对齐 tests/test_launch_state.py 的正确建法：WorkflowRun 必须带 revision/
    workflow_version/definition_hash 与 READY 状态，且附三条与 simple_contract
    固定定义一致的 WorkflowStep 实例行——否则 launch_dto._channel 渲染时抛
    「实例步骤与固定定义不一致」。店名带序号避免 (tenant, platform, shop_name) 相撞。
    """
    _LAUNCH_SEQ[0] += 1
    seq = _LAUNCH_SEQ[0]
    shop = Shop(tenant_id=tenant_id, platform=platform,
                shop_name=f"店-{product_id}-{platform}-{seq}",
                market="ANY", fulfillment_mode="ANY", role="sales")
    db.add(shop)
    db.flush()
    listing = Listing(tenant_id=tenant_id, product_id=product_id, shop_id=shop.id, platform=platform,
                     title="listing")
    db.add(listing)
    db.flush()
    run = WorkflowRun(tenant_id=tenant_id, template_key="SIMPLE_CONTRACT",
                      flow_kind="PLATFORM_LAUNCH", workspace_id=tenant_id,
                      product_id=product_id, shop_id=shop.id, listing_id=listing.id,
                      definition_snapshot=simple_contract(), environment="CONTRACT_TEST",
                      platform=platform, market="ANY", fulfillment_mode="ANY",
                      revision=1, workflow_version=1, definition_hash="ovw-probe",
                      execution_status="READY", platform_status="NOT_SUBMITTED",
                      verification_status="UNKNOWN", current_step="INFORMATION",
                      active_slot=None)
    db.add(run)
    db.flush()
    for code, kind in (("INFORMATION", "DATA_PREPARATION"),
                       ("COMPLIANCE", "COMPLIANCE"),
                       ("SUBMISSION", "PLATFORM_SUBMISSION"),
                       ("ACTIVATION", "PLATFORM_ACTIVATION"),
                       ("MONITORING", "MONITORING")):
        db.add(WorkflowStep(tenant_id=tenant_id, run_id=run.id, step_code=code,
                            business_type=kind, step_status="READY", agent="", action=""))
    db.commit()
    return shop.id, run.id


def test_overview_top_level_keys_exact(client, auth_headers):
    pid = _create_product(client, auth_headers)
    ov = client.get(f"/api/products/{pid}/overview", headers=auth_headers)
    assert ov.status_code == 200, ov.text
    body = ov.json()
    assert set(body.keys()) == {"product", "supply", "channels", "performance", "stage", "generated_at"}
    assert set(body["supply"].keys()) == {
        "offers_count", "selected_offer_id", "selected_offer_price_cny",
        "min_offer_price_cny", "cost_missing", "cost_complete",
        "selected_offer_missing", "selected_offer_state",
        "selected_offer_limits", "cost_offer_id"}
    assert set(body["stage"].keys()) == {"key", "label", "reasons"}


def test_channels_shape_equals_endpoint(client, auth_headers):
    """overview.channels 与 product_channels 端点返回形状完全一致（复用同一函数）。"""
    pid = _create_product(client, auth_headers)
    ov = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()
    ch = client.get(f"/api/products/{pid}/channels", headers=auth_headers)
    assert ch.status_code == 200, ch.text
    assert ov["channels"] == ch.json()


def test_stage_ladder_no_offer_then_with_offer(client, auth_headers):
    """无报价 → NO_SUPPLY 且 reasons 非空；有报价 → 进阶（不再是 NO_SUPPLY）。"""
    pid = _create_product(client, auth_headers)
    ov0 = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()
    assert ov0["stage"]["key"] == "NO_SUPPLY", ov0["stage"]
    assert ov0["stage"]["reasons"], "NO_SUPPLY 必须有中文原因"

    sid = _create_supplier(client, auth_headers)
    _create_offer(client, auth_headers, sid, pid)
    ov1 = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()
    assert ov1["stage"]["key"] != "NO_SUPPLY", ov1["stage"]
    assert ov1["supply"]["offers_count"] == 1


def test_multi_shop_independence(client, auth_headers):
    """一商品两店渠道：overview 同时反映两店，且不互相覆盖。"""
    pid = _create_product(client, auth_headers)
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        shop_a, _ = _create_launch(db, tenant_id, pid, platform="shopee")
        shop_b, _ = _create_launch(db, tenant_id, pid, platform="shopee")
    finally:
        db.close()

    ov = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()
    assert ov["channels"]["total"] == 2, ov["channels"]
    shop_ids = {c["shop"]["id"] for c in ov["channels"]["channels"]}
    assert shop_ids == {shop_a, shop_b}, shop_ids
    # 两次读取一致（不互相覆盖）
    ov2 = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()
    assert {c["shop"]["id"] for c in ov2["channels"]["channels"]} == {shop_a, shop_b}


def test_performance_null_safe_without_orders(client, auth_headers):
    """无真实订单 → performance 为 null（绝不臆造 0 / 假绿分数）。"""
    pid = _create_product(client, auth_headers)
    ov = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()
    assert ov["performance"] is None, ov["performance"]


def test_list_signals_batched_counts(client, auth_headers):
    """列表 signals：本页两商品的 offers/channels 计数来自 3 条批量聚合。"""
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        # 商品 A：有报价，无渠道
        pa = _create_product(client, auth_headers, "SIG-A")
        sa = _create_supplier(client, auth_headers, "SIG-SUP")
        _create_offer(client, auth_headers, sa, pa, price=3.0)
        _create_offer(client, auth_headers, sa, pa, price=4.0)
        # 商品 B：有渠道，无报价
        pb = _create_product(client, auth_headers, "SIG-B")
        _create_launch(db, tenant_id, pb, platform="shopee")
    finally:
        db.close()

    r = client.get("/api/products", headers=auth_headers, params={"page_size": 200})
    assert r.status_code == 200, r.text
    items = {it["id"]: it for it in r.json()["items"]}
    assert pa in items and pb in items
    assert items[pa]["signals"] == {"offers_count": 2, "channels_count": 0,
                                     "assets_verified_count": 0}, items[pa]["signals"]
    assert items[pb]["signals"] == {"offers_count": 0, "channels_count": 1,
                                     "assets_verified_count": 0}, items[pb]["signals"]
