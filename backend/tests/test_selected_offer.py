"""选中报价持久化（B3 / V9.1 原型 04/05/06）端到端验证。

验收口径（对应 docs/CONTRACT.md 的 selected-offer 契约卡）：
  1. save（PUT selected-offer）→ 新请求（overview.supply + offers 列表 is_selected）读回；
  2. 重新登录（真实第二次 /api/auth/login）读回一致；
  3. costing 使用被选中报价（即使缺货也优先）；
  4. 跨租户报价 → 404；报价属于别的商品 → 400；显式 null 清除；幂等双 PUT 单值；
  5. OfferIn 新字段落库（valid_until roundtrip，坏 source_kind → 422 点名字段）；
  6. 供应商富化字段存在且批量加载（supplier.name 出现）。
"""
from datetime import datetime

from app.auth import hash_password
from app.db import SessionLocal
from app.models import Product, SupplierOffer, Tenant, User
from app.services.costing import best_purchase


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


def _create_product(client, headers, title="SKU-A"):
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
        name = f"SUP-A-{_SUP_SEQ[0]}"
    r = client.post("/api/suppliers", headers=headers, json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_offer(client, headers, supplier_id, product_id, **kw):
    body = {"supplier_id": supplier_id, "product_id": product_id,
            "price": kw.get("price", 9.9), "currency": kw.get("currency", "CNY"),
            "in_stock": kw.get("in_stock", True)}
    for k in ("valid_until", "source_kind", "verification_status"):
        if k in kw:
            body[k] = kw[k]
    r = client.post("/api/suppliers/offers", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_put_then_overview_readback(client, auth_headers):
    """save → overview.supply 读回 selected_offer_id；offers 列表 is_selected 标记。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    oid = _create_offer(client, auth_headers, sid, pid, price=12.5)
    r = client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                   json={"offer_id": oid})
    assert r.status_code == 200, r.text
    assert r.json()["selected_offer_id"] == oid
    assert r.json()["product_id"] == pid

    ov = client.get(f"/api/products/{pid}/overview", headers=auth_headers)
    assert ov.status_code == 200, ov.text
    assert ov.json()["supply"]["selected_offer_id"] == oid

    offers = client.get(f"/api/suppliers/offers?product_id={pid}", headers=auth_headers)
    assert offers.status_code == 200, offers.text
    items = offers.json()["items"]
    assert offers.json()["selected_offer_id"] == oid
    sel = [i for i in items if i["is_selected"]]
    assert len(sel) == 1 and sel[0]["id"] == oid


def test_fresh_login_reads_back_same(client, auth_headers):
    """重新登录（全新 token）后 selected_offer 读回一致。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    oid = _create_offer(client, auth_headers, sid, pid)
    assert client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                      json={"offer_id": oid}).status_code == 200
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    fresh = {"Authorization": f"Bearer {r.json()['token']}"}
    ov = client.get(f"/api/products/{pid}/overview", headers=fresh)
    assert ov.status_code == 200, ov.text
    assert ov.json()["supply"]["selected_offer_id"] == oid


def test_costing_honors_selection_over_min_price(client, auth_headers):
    """被选中报价即使缺货，costing.best_purchase 也优先采用（证明 selection 生效）。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    # 在库更便宜报价（应被「选中」覆盖）
    cheap = _create_offer(client, auth_headers, sid, pid, price=5.0, in_stock=True)
    # 缺货但更贵报价 —— 用户显式选定它
    pricey = _create_offer(client, auth_headers, sid, pid, price=20.0, in_stock=False)
    assert client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                      json={"offer_id": pricey}).status_code == 200

    db = SessionLocal()
    try:
        product = db.get(__import__("app.models", fromlist=["Product"]).Product, pid)
        tenant_id = _admin_tenant_id(db)
        price_cny, offer_id = best_purchase(db, tenant_id, product)
    finally:
        db.close()
    assert offer_id == pricey, "costing 应返回被显式选中的（缺货）报价"
    assert round(price_cny, 2) == 20.0


def test_cross_tenant_offer_404(client, auth_headers):
    """跨租户报价不可用于本租户商品的选择 → 404 报价不存在或无访问权限。"""
    pid = _create_product(client, auth_headers)
    db = SessionLocal()
    try:
        from app.services.membership_service import ensure_workspace_profile
        other = Tenant(name="选中报价隔离租户")
        db.add(other)
        db.flush()
        ensure_workspace_profile(db, other.id, other.name)
        _, headers2 = _make_user(client, db, other.id, "sel_user_2")
    finally:
        db.close()
    # tenant2 用户建自己的商品，但提交 tenant1 的报价 id（无法获得，这里用一个不可能存在的 id）
    # 用真实存在的「另一租户报价」更贴近：在 tenant1 建一个报价，再让 tenant2 引用它。
    sid1 = _create_supplier(client, auth_headers)
    foreign_offer = _create_offer(client, auth_headers, sid1, pid)
    # tenant2 的商品
    r2 = client.post("/api/products", headers=headers2,
                     json={"title": "T2", "sku": "T2", "category": "c"})
    pid2 = r2.json()["id"]
    resp = client.put(f"/api/products/{pid2}/selected-offer", headers=headers2,
                      json={"offer_id": foreign_offer})
    assert resp.status_code == 404, resp.text
    assert "报价不存在或无访问权限" in resp.json()["detail"]


def test_offer_of_other_product_400(client, auth_headers):
    """报价属于别的商品 → 400 报价不属于该商品。"""
    p1 = _create_product(client, auth_headers, "P1")
    p2 = _create_product(client, auth_headers, "P2")
    sid = _create_supplier(client, auth_headers)
    oid = _create_offer(client, auth_headers, sid, p1)
    resp = client.put(f"/api/products/{p2}/selected-offer", headers=auth_headers,
                      json={"offer_id": oid})
    assert resp.status_code == 400, resp.text
    assert "报价不属于该商品" in resp.json()["detail"]


def test_explicit_null_clears(client, auth_headers):
    """显式 null = 清除选择；offers 列表 selected_offer_id 为 null 且全部 is_selected=False。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    oid = _create_offer(client, auth_headers, sid, pid)
    assert client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                      json={"offer_id": oid}).status_code == 200
    resp = client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                      json={"offer_id": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["selected_offer_id"] is None
    offers = client.get(f"/api/suppliers/offers?product_id={pid}", headers=auth_headers)
    assert offers.json()["selected_offer_id"] is None
    assert all(not i["is_selected"] for i in offers.json()["items"])


def test_idempotent_double_put_single_value(client, auth_headers):
    """等价两次 PUT 单值：两次均 200，selected_offer_id 相同（幂等）。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    oid = _create_offer(client, auth_headers, sid, pid)
    r1 = client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                    json={"offer_id": oid})
    r2 = client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                    json={"offer_id": oid})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["selected_offer_id"] == oid == r2.json()["selected_offer_id"]


def test_offerin_new_fields_persist_and_validate(client, auth_headers):
    """OfferIn 新字段落库（valid_until roundtrip）；坏 source_kind / verification_status → 422 点名。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    future = datetime(2030, 1, 1, 0, 0, 0).isoformat()
    oid = _create_offer(client, auth_headers, sid, pid, price=8.0,
                        valid_until=future, source_kind="scraped",
                        verification_status="unverified")
    offers = client.get(f"/api/suppliers/offers?product_id={pid}", headers=auth_headers)
    item = next(i for i in offers.json()["items"] if i["id"] == oid)
    assert "2030-01-01" in (item["valid_until"] or ""), item
    assert item["source_kind"] == "scraped"
    assert item["verification_status"] == "unverified"

    # 供应商富化字段存在且批量加载
    assert item["supplier"] is not None and item["supplier"]["name"]

    # 坏 source_kind → 422 点名
    r = client.post("/api/suppliers/offers", headers=auth_headers,
                    json={"supplier_id": sid, "product_id": pid, "price": 1.0,
                          "source_kind": "bogus"})
    assert r.status_code == 422, r.text
    assert "source_kind" in r.text

    # 坏 verification_status → 422 点名
    r = client.post("/api/suppliers/offers", headers=auth_headers,
                    json={"supplier_id": sid, "product_id": pid, "price": 1.0,
                          "verification_status": "bogus"})
    assert r.status_code == 422, r.text
    assert "verification_status" in r.text


def test_stale_selection_is_flagged_not_silent(client, auth_headers):
    """选定报价悬空（如直库把 selected_offer_id 指向不存在的行）→
    overview 显式 selected_offer_missing=True 且 cost_offer_id 回退为最低在库价——
    绝不允许无提示回退仍显示「用户选定」。（API/正常路径不会产生悬空：
    FK 强制 + 无报价删除端点，此测试只覆盖直库损坏场景。）"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    keep = _create_offer(client, auth_headers, sid, pid, price=6.0, in_stock=True)
    stale = _create_offer(client, auth_headers, sid, pid, price=20.0, in_stock=True)
    assert client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                      json={"offer_id": stale}).status_code == 200
    ov0 = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()
    assert ov0["supply"]["selected_offer_missing"] is False
    assert ov0["supply"]["cost_offer_id"] == stale

    # 直库把选定指向不存在的报价 id：本库 FK 强制会拦，故临时关闭 PRAGMA 模拟
    # 「FK 未开启的直库损坏环境」（防御性诚实信号仍须存在）
    db = SessionLocal()
    try:
        from sqlalchemy import text
        db.execute(text("PRAGMA foreign_keys=OFF"))
        p = db.get(Product, pid)
        p.selected_offer_id = 99999999
        db.commit()
    finally:
        db.close()

    ov = client.get(f"/api/products/{pid}/overview", headers=auth_headers)
    assert ov.status_code == 200, ov.text
    supply = ov.json()["supply"]
    assert supply["selected_offer_missing"] is True, supply
    assert supply["cost_offer_id"] == keep, supply
    assert supply["selected_offer_price_cny"] is None, supply


def test_pricing_calc_exposes_offer_id(client, auth_headers):
    """POST /pricing/calc 必须返回 costing 实际采用的 offer_id（选定优先于最低价）。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    cheap = _create_offer(client, auth_headers, sid, pid, price=5.0, in_stock=True)
    _create_offer(client, auth_headers, sid, pid, price=20.0, in_stock=True)

    r0 = client.post("/api/pricing/calc", headers=auth_headers, json={"product_id": pid})
    assert r0.status_code == 200, r0.text
    assert r0.json()["offer_id"] == cheap, "未选定时采用最低在库报价"

    pricey = _create_offer(client, auth_headers, sid, pid, price=20.0, in_stock=True)
    assert client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                      json={"offer_id": pricey}).status_code == 200
    r1 = client.post("/api/pricing/calc", headers=auth_headers, json={"product_id": pid})
    assert r1.status_code == 200, r1.text
    assert r1.json()["offer_id"] == pricey, "选定的更贵报价必须被 costing 采用"


def test_selected_offer_states_expired_out_of_stock_unverified(client, auth_headers):
    """三档失效规则（B3 契约）：EXPIRED / OUT_OF_STOCK / UNVERIFIED 保留偏好但
    显式给出阻断原因；删除/不可访问 → MISSING 且成本回退（另有 test_stale...）。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)

    expired = _create_offer(client, auth_headers, sid, pid, price=11.0,
                            valid_until="2020-01-01T00:00:00")
    assert client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
                      json={"offer_id": expired}).status_code == 200
    sup = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()["supply"]
    assert sup["selected_offer_state"] == "EXPIRED", sup
    assert sup["selected_offer_id"] == expired
    assert sup["selected_offer_price_cny"] is not None  # 偏好保留，仍可用于试算
    assert sup["selected_offer_limits"] and "过期" in sup["selected_offer_limits"][0]

    oos = _create_offer(client, auth_headers, sid, pid, price=12.0, in_stock=False)
    client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
               json={"offer_id": oos})
    sup = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()["supply"]
    assert sup["selected_offer_state"] == "OUT_OF_STOCK", sup
    assert "缺货" in sup["selected_offer_limits"][0]

    unv = _create_offer(client, auth_headers, sid, pid, price=13.0,
                        source_kind="scraped", verification_status="unverified")
    client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
               json={"offer_id": unv})
    sup = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()["supply"]
    assert sup["selected_offer_state"] == "UNVERIFIED", sup
    assert "待核实" in sup["selected_offer_limits"][0]

    ok = _create_offer(client, auth_headers, sid, pid, price=14.0)
    client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
               json={"offer_id": ok})
    sup = client.get(f"/api/products/{pid}/overview", headers=auth_headers).json()["supply"]
    assert sup["selected_offer_state"] == "OK", sup
    assert sup["selected_offer_limits"] == []


def _create_shop(client, headers, platform="shopee", name="B3 销售店", market="SG"):
    r = client.post("/api/shops", headers=headers,
                    json={"platform": platform, "is_demo": True, "shop_name": name,
                          "market": market})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_calc_shop_context_is_verified_and_echoed(client, auth_headers):
    """B3 成本上下文：shop_id 归属校验（未知 404、货源店 422），
    销售店回显 shop_id 且 is_generic_estimate=False；不传 shop_id 为通用试算。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    _create_offer(client, auth_headers, sid, pid, price=9.0)

    sales = _create_shop(client, auth_headers)
    r = client.post("/api/pricing/calc", headers=auth_headers,
                    json={"product_id": pid, "shop_id": sales})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["shop_id"] == sales
    assert body["is_generic_estimate"] is False
    # 市场口径：未显式给目的国时沿用店铺市场，不允许回显 null（前端不得自行推断）。
    assert body["market"] == "SG", body

    # 显式目的国优先于店铺市场。
    ro = client.post("/api/pricing/calc", headers=auth_headers,
                     json={"product_id": pid, "shop_id": sales, "destination_country": "US"})
    assert ro.status_code == 200, ro.text
    assert ro.json()["market"] == "US", ro.text

    r0 = client.post("/api/pricing/calc", headers=auth_headers, json={"product_id": pid})
    assert r0.status_code == 200, r0.text
    assert r0.json()["shop_id"] is None
    assert r0.json()["market"] is None
    assert r0.json()["is_generic_estimate"] is True

    r404 = client.post("/api/pricing/calc", headers=auth_headers,
                       json={"product_id": pid, "shop_id": 99999999})
    assert r404.status_code == 404, r404.text

    source = _create_shop(client, auth_headers, platform="1688", name="B3 货源店")
    r422 = client.post("/api/pricing/calc", headers=auth_headers,
                       json={"product_id": pid, "shop_id": source})
    assert r422.status_code == 422, r422.text
    assert "货源店铺" in r422.json()["detail"]


def test_calc_exposes_selected_offer_state(client, auth_headers):
    """成本响应必须带 offer_state / offer_limits，与 overview 同源。"""
    pid = _create_product(client, auth_headers)
    sid = _create_supplier(client, auth_headers)
    expired = _create_offer(client, auth_headers, sid, pid, price=15.0,
                            valid_until="2020-01-01T00:00:00")
    client.put(f"/api/products/{pid}/selected-offer", headers=auth_headers,
               json={"offer_id": expired})
    body = client.post("/api/pricing/calc", headers=auth_headers,
                       json={"product_id": pid}).json()
    assert body["offer_id"] == expired
    assert body["offer_state"] == "EXPIRED"
    assert body["offer_limits"] and "过期" in body["offer_limits"][0]
