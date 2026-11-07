"""四域深度对抗测试：功能状态机 / 安全越权 / 数据财务口径 / 平台协议容错。

每个域独立成类，便于单独运行：
    python -m pytest tests/test_deep_domains.py -q
    python -m pytest tests/test_deep_domains.py::TestFunctionDomain -q
"""
import hashlib
import hmac
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base

from .asset_helpers import register_reviewed_image as register_reviewed_image

# ============================================================ 域一：功能状态机

class TestFunctionDomain:
    """非法状态流转、边界数值、幂等性——全部必须给出可读中文错误而非 500。"""

    def test_illegal_order_ship(self, client, auth_headers):
        """pending 订单直接发货 -> 400（不是 500）。

        自己导一条 pending 订单，不再取演示同步的 `items[0]`：演示同步的状态是随机的
        （同文件下一条用例的注释也如实写了这一点），而且 `items[0]` 是哪一单取决于此前
        累计的演示订单量——全量跑时它常常已经是 paid/终态，PUT pending 被拒后 ship 直接 200，
        这条用例就**单跑绿、全量红**，看起来像新功能引入的回归。
        """
        product = client.post("/api/products", headers=auth_headers,
                              json={"title": "Ship Guard Probe", "category": "家居"})
        assert product.status_code == 200, product.text
        external_no = f"SHIP-GUARD-{product.json()['id']}"
        imported = client.post("/api/orders/import", headers=auth_headers, json={
            "csv_text": "external_no,platform,amount,qty,status,sku\n"
                        f"{external_no},shopee,12,1,pending,{product.json()['sku']}"})
        assert imported.status_code == 200 and imported.json()["imported"] == 1, imported.text
        order = client.get("/api/orders", headers=auth_headers,
                           params={"keyword": external_no}).json()["items"][0]
        assert order["status"] == "pending"
        r = client.post(f"/api/orders/{order['id']}/ship", headers=auth_headers)
        assert r.status_code == 400 and "已付款" in r.json()["detail"]

    def test_refund_terminal_state_rejected(self, client, auth_headers):
        """已拒绝的退款单不能再审核；已退款的订单不能再发起退款。"""
        # 演示同步会随机返回 cancelled 等终态；固定导入 paid 订单，不能强行倒退状态。
        product = client.post("/api/products", headers=auth_headers,
                              json={"title": "Refund Terminal Probe", "category": "家居"})
        assert product.status_code == 200, product.text
        pid, sku = product.json()["id"], product.json()["sku"]
        external_no = f"REFUND-TERMINAL-{pid}"
        imported = client.post("/api/orders/import", headers=auth_headers, json={
            "csv_text": "external_no,platform,amount,qty,status,sku\n"
                        f"{external_no},shopee,25,1,paid,{sku}"})
        assert imported.status_code == 200 and imported.json()["imported"] == 1, imported.text
        o = client.get("/api/orders", headers=auth_headers,
                       params={"keyword": external_no}).json()["items"][0]
        assert o["status"] == "paid"
        refund = client.post("/api/refunds", headers=auth_headers,
                             json={"order_id": o["id"], "qty": 1})
        assert refund.status_code == 200, refund.text
        rid = refund.json()["id"]
        client.put(f"/api/refunds/{rid}/status", headers=auth_headers, json={"status": "rejected"})
        r = client.put(f"/api/refunds/{rid}/status", headers=auth_headers, json={"status": "approved"})
        assert r.status_code == 400 and "不可审核" in r.json()["detail"]

    def test_po_double_receive_rejected(self, client, auth_headers):
        """已收货采购单不能再收货。"""
        r = client.post("/api/products", headers=auth_headers,
                        json={"title": "深度测试商品A", "attrs": {"supplier_price": 5, "sale_price": 12}})
        pid = r.json()["id"]
        sid = client.get("/api/suppliers", headers=auth_headers).json()["items"][0]["id"]
        client.post("/api/suppliers/offers", headers=auth_headers,
                    json={"supplier_id": sid, "product_id": pid, "price": 5})
        po_id = client.post("/api/purchases", headers=auth_headers,
                            json={"product_id": pid, "qty": 3}).json()["id"]
        client.put(f"/api/purchases/{po_id}", headers=auth_headers, json={"status": "submitted"})
        client.post(f"/api/purchases/{po_id}/receive", headers=auth_headers, json={})
        r = client.post(f"/api/purchases/{po_id}/receive", headers=auth_headers, json={})
        assert r.status_code == 400

    def test_numeric_boundaries(self, client, auth_headers):
        """零/负数/超大量值必须被拒，且 detail 为中文。"""
        cases = [
            ("/api/purchases", {"product_id": 1, "qty": 0}),
            ("/api/purchases", {"product_id": 1, "qty": -5}),
            ("/api/refunds", {"order_id": 1, "qty": 0}),
            ("/api/schedules", {"name": "x", "kind": "trend_scan", "interval_minutes": 4}),
        ]
        for path, body in cases:
            r = client.post(path, headers=auth_headers, json=body)
            assert r.status_code in (400, 404, 422), f"{path} {body} -> {r.status_code}"
            if r.status_code == 400:
                assert any("\u4e00" <= c <= "\u9fff" for c in r.json()["detail"]), \
                    f"{path} 错误信息非中文: {r.json()['detail']}"

    def test_pagination_edge(self, client, auth_headers):
        """分页边界必须给出可预期响应，不得 500。

        约束语义（`app/pagination.py`）：
        - `page_num=0/-1` → 422（`ge=1`）
        - `page_num=99999` → 200 + 空列表（越界页合法）
        - `page_size=0` / `10000` → 422（`ge=1` / `le=MAX_PAGE_SIZE`）
        超上限**刻意报错而非静默截断**：否则集合比对会漏数据（审计 #10 / DEBT-27）。
        """
        expect_422 = ({"page_num": 0}, {"page_num": -1},
                      {"page_size": 10000}, {"page_size": 0})
        for params in expect_422:
            r = client.get("/api/products", headers=auth_headers, params=params)
            assert r.status_code == 422, f"{params} 应被拒（避免静默截断），实际 {r.status_code}"
        r = client.get("/api/products", headers=auth_headers, params={"page_num": 99999})
        assert r.status_code == 200 and r.json()["items"] == [], "越界页应为空列表"
        # 上限内必须可用，且返回的 page_size 与请求一致
        r = client.get("/api/products", headers=auth_headers, params={"page_size": 200})
        assert r.status_code == 200 and r.json()["page_size"] == 200

    def test_duplicate_standardize_stable(self, client, auth_headers):
        """重复标准化同一商品：dedupe_hash 必须稳定（幂等）。"""
        r = client.post("/api/products", headers=auth_headers,
                        json={"title": "幂等测试商品 家居收纳盒", "category": "家居",
                              "attrs": {"material": "PP", "color": "白"}})
        pid = r.json()["id"]
        h1 = client.post(f"/api/products/{pid}/standardize", headers=auth_headers).json()["dedupe_hash"]
        h2 = client.post(f"/api/products/{pid}/standardize", headers=auth_headers).json()["dedupe_hash"]
        assert h1 == h2 and h1


# ============================================================ 域二：安全越权

class TestSecurityDomain:
    """越权矩阵补全 + JWT 攻击 + 注入健壮性。"""

    @pytest.mark.parametrize("role,password,write_blocked", [
        ("viewer", "viewer123", True),
        ("ops", "ops123", False),
    ])
    def test_write_matrix_all_modules(self, client, role, password, write_blocked):
        """viewer 对所有写端点 403；operator 可写业务但不能管理用户/平台。"""
        h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': role, 'password': password}).json()['token']}"}
        write_endpoints = [
            ("POST", "/api/products", {"title": "越权探针"}),
            ("POST", "/api/discovery/trends/scan", None),
            ("POST", "/api/suppliers", {"name": "越权供应商"}),
            ("POST", "/api/listings/generate", {"product_id": 1}),
            ("POST", "/api/compliance/check", {"target_type": "product", "ref_id": 1}),
            ("POST", "/api/pricing/calc", {"product_id": 1}),
            ("POST", "/api/ads/campaigns", {"name": "越权广告"}),
            ("POST", "/api/orders/sync", {"count": 1}),
            ("POST", "/api/support/conversations", {"buyer_name": "x", "content": "y"}),
            ("POST", "/api/workflows/run", {"template_key": "reprice"}),
            ("POST", "/api/knowledge/docs", {"title": "t", "content": "c"}),
            ("POST", "/api/schedules", {"name": "x", "kind": "trend_scan", "interval_minutes": 60}),
            ("POST", "/api/purchases", {"product_id": 1, "qty": 1}),
            ("POST", "/api/refunds", {"order_id": 1, "qty": 1}),
            ("POST", "/api/shops", {"platform": "1688"}),
        ]
        for _method, path, body in write_endpoints:
            r = client.post(path, json=body, headers=h)
            if write_blocked:
                assert r.status_code == 403, f"viewer {path} -> {r.status_code}（应 403）"
            else:
                assert r.status_code != 403, f"operator {path} 被误拦 403"

    def test_jwt_tampering(self, client, auth_headers):
        """篡改 JWT payload（提权/换租户）必须 401。"""
        import base64
        import json as _json

        token = auth_headers["Authorization"].split(" ", 1)[1]
        header, payload, sig = token.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        data = _json.loads(base64.urlsafe_b64decode(pad(payload)))
        # 篡改为 superadmin + 越权租户
        data["role"] = "superadmin"
        data["tid"] = 999
        forged_payload = base64.urlsafe_b64encode(
            _json.dumps(data).encode()).decode().rstrip("=")
        forged = f"{header}.{forged_payload}.{sig}"
        r = client.get("/api/admin/tenants", headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401, f"篡改 token 未被拒绝: {r.status_code}"
        # alg=none 攻击
        none_token = base64.urlsafe_b64encode(
            _json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
        r = client.get("/api/products", headers={"Authorization": f"Bearer {none_token}.{payload}."})
        assert r.status_code == 401

    def test_sql_injection_safe(self, client, auth_headers):
        """SQL 注入字符串作为查询参数不得 500 或泄漏全表。"""
        payloads = ["' OR 1=1--", "'; DROP TABLE products;--", "1' UNION SELECT * FROM users--"]
        for p in payloads:
            r = client.get("/api/products", headers=auth_headers, params={"keyword": p})
            assert r.status_code == 200, f"注入载荷导致 {r.status_code}"
            assert r.json()["total"] == 0, f"注入载荷返回了数据: {r.json()['total']}"
        # 用户名注入登录
        r = client.post("/api/auth/login", json={"username": "' OR 1=1--", "password": "x"})
        assert r.status_code == 400

    def test_path_traversal_safe(self, client, auth_headers):
        """路径穿越不得命中 SPA 兜底、不得返回前端页面。

        说明：httpx 会先规范化字面 ".."，服务端收到的是折叠后路径；真实攻击载荷是
        URL 编码的 %2e%2e（不被规范化），必须被 JSON 404 拦截。
        """
        r = client.get("/api/products/%2e%2e/%2e%2e/etc/passwd", headers=auth_headers)
        assert r.status_code == 404, f"编码穿越 -> {r.status_code}"
        assert "json" in r.headers.get("content-type", ""), \
            f"API 404 应返回 JSON，实际 {r.headers.get('content-type')}"
        # /api 前缀的未知路径一律 JSON 404，不返回前端页面
        r = client.get("/api/nonexistent", headers=auth_headers)
        assert r.status_code == 404 and "json" in r.headers.get("content-type", "")


# ============================================================ 域三：数据与财务

class TestDataFinanceDomain:
    """财务口径交叉验证、库存守恒、结算守恒、时间排序。"""

    @pytest.fixture()
    def db(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        s = Session()
        yield s
        s.close()

    def test_order_profit_identity(self, client, auth_headers, fetch_all):
        """逐条核对：订单 profit == amount - cost（误差 0.01）。"""
        items = fetch_all("/api/orders", auth_headers)
        assert items, "无订单可核对"
        bad = [o["external_no"] for o in items
               if abs(o["profit"] - (o["amount"] - o["cost"])) > 0.011]
        assert not bad, f"{len(bad)} 条订单利润恒等式不成立，如 {bad[:3]}"

    def test_inventory_conservation(self, client, auth_headers):
        """采购收货 +N 与退款退货 +M 后库存增量精确守恒。"""
        r = client.post("/api/products", headers=auth_headers,
                        json={"title": "库存守恒测试品", "attrs": {"supplier_price": 6, "sale_price": 15, "onhand": 10}})
        pid = r.json()["id"]
        sid = client.get("/api/suppliers", headers=auth_headers).json()["items"][0]["id"]
        client.post("/api/suppliers/offers", headers=auth_headers,
                    json={"supplier_id": sid, "product_id": pid, "price": 6})
        # 采购 +7
        po_id = client.post("/api/purchases", headers=auth_headers,
                            json={"product_id": pid, "qty": 7}).json()["id"]
        client.put(f"/api/purchases/{po_id}", headers=auth_headers, json={"status": "submitted"})
        client.post(f"/api/purchases/{po_id}/receive", headers=auth_headers, json={})
        after_po = client.get(f"/api/products/{pid}", headers=auth_headers).json()["attrs"]["onhand"]
        assert after_po == 17, f"采购入库后应为 17，实际 {after_po}"

    def test_settlement_amount_conservation(self, client, auth_headers, fetch_all):
        """结算单总额 == 纳入的采购单金额之和。"""
        r = client.post("/api/products", headers=auth_headers,
                        json={"title": "结算守恒测试品", "attrs": {"supplier_price": 11, "sale_price": 25}})
        pid = r.json()["id"]
        sid = client.get("/api/suppliers", headers=auth_headers).json()["items"][0]["id"]
        client.post("/api/suppliers/offers", headers=auth_headers,
                    json={"supplier_id": sid, "product_id": pid, "price": 11})
        po_ids, total = [], 0.0
        for qty in (2, 3):
            po = client.post("/api/purchases", headers=auth_headers,
                             json={"product_id": pid, "qty": qty, "supplier_id": sid}).json()
            client.put(f"/api/purchases/{po['id']}", headers=auth_headers, json={"status": "submitted"})
            client.post(f"/api/purchases/{po['id']}/receive", headers=auth_headers, json={})
            po_ids.append(po["id"])
            total += po["total"]
        st = client.post("/api/settlements/generate", headers=auth_headers,
                         json={"supplier_id": sid}).json()
        # 结算单汇总该供应商全部「已收货且未挂结算单」的 PO（可能含其他用例遗留单），
        # 故校验：总额不小于本批、且本批 PO 均已挂到该结算单
        assert st["total_amount"] >= round(total, 2) - 0.01, \
            f"结算总额 {st['total_amount']} 小于本批采购合计 {total}"
        assert st["po_count"] >= len(po_ids)
        pos = fetch_all("/api/purchases", auth_headers)
        linked = [p for p in pos if p["id"] in po_ids and p.get("settlement_id") == st["id"]]
        assert len(linked) == len(po_ids), f"本批 {len(po_ids)} 张 PO 未全部挂到结算单 {st['id']}"

    def test_gmv_excludes_refunded(self, client, auth_headers):
        """BI GMV 走「真实数据口径」（只统计 api/import/manual 来源），退款单不计入净收入。

        设计意图：seed/demo 是演示数据，商用看板必须排除它们——这正是数据真实性要求。
        本用例用 CSV 导入（source=import）造真实口径订单再对账。

        断言方式（规范 §8 T-2 无顺序依赖）：用「导入前后的 GMV 增量」而不是
        「全库 import 订单金额求和」。后者会把其它测试文件导入的订单也算进期望值
        （实测差额 602.00，等于 test_api.py 的 FX-CNY-001 700 CNY 按 0.14 折算），
        单独跑通过、全量跑必挂。
        订单日期取当前时间而非写死日期：BI 只统计最近 30 天，写死日期在 30 天后
        会永久失败（定时炸弹）。
        """
        stamp = int(time.time() * 1000)
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        # 不依赖商品：CSV 省略 sku 列，订单不关联 product_id，GMV 口径不需要商品
        before = client.get("/api/bi/dashboard", headers=auth_headers).json()
        csv_text = (
            "external_no,platform,qty,amount,status,country,buyer_name,created_at\n"
            f"GMV-A-{stamp},shopee,1,100.00,delivered,US,A,{now}\n"
            f"GMV-B-{stamp},shopee,1,200.00,delivered,US,B,{now}\n"
        )
        r = client.post("/api/orders/import", headers=auth_headers, json={"csv_text": csv_text})
        assert r.status_code == 200 and r.json()["imported"] == 2, r.text

        after_import = client.get("/api/bi/dashboard", headers=auth_headers).json()
        delta = round(after_import["gmv"] - before["gmv"], 2)
        assert delta == pytest.approx(300.0, abs=0.01), \
            f"导入两单（A 100 + B 200）后 GMV 增量应为 300，实际 {delta}"

        # 把 B 单整单退款
        ob = client.get("/api/orders", headers=auth_headers,
                        params={"keyword": f"GMV-B-{stamp}"}).json()["items"][0]
        rid = client.post("/api/refunds", headers=auth_headers,
                          json={"order_id": ob["id"], "qty": ob["qty"]}).json()["id"]
        client.put(f"/api/refunds/{rid}/status", headers=auth_headers, json={"status": "approved"})
        client.post(f"/api/refunds/{rid}/refund", headers=auth_headers)

        after_refund = client.get("/api/bi/dashboard", headers=auth_headers).json()
        # 口径说明：GMV 保留退款前成交额（退款只在 net_revenue 扣减），
        # 否则「先排除 refunded 订单、再扣退款额」会双减。
        assert after_refund["gmv"] == pytest.approx(after_import["gmv"], abs=0.01), \
            f"退款不应改变 GMV：退款前 {after_import['gmv']}，退款后 {after_refund['gmv']}"
        # 净收入必须精确扣减退款额 200（不只是「<= GMV」这种恒真式断言）
        deducted = round(after_import["net_revenue"] - after_refund["net_revenue"], 2)
        assert deducted == pytest.approx(200.0, abs=0.01), \
            f"净收入应扣减退款 200，实际扣减 {deducted}"
        # 退款已联动订单状态
        refunded = client.get("/api/orders", headers=auth_headers,
                              params={"keyword": f"GMV-B-{stamp}"}).json()["items"]
        assert refunded and refunded[0]["status"] == "refunded", "退款未联动订单状态"

    def test_pagination_no_overlap(self, client, auth_headers):
        """分页第二页与第一页无重复。"""
        p1 = {o["id"] for o in client.get("/api/orders", headers=auth_headers,
                                          params={"page_num": 1, "page_size": 10}).json()["items"]}
        p2 = {o["id"] for o in client.get("/api/orders", headers=auth_headers,
                                          params={"page_num": 2, "page_size": 10}).json()["items"]}
        assert not (p1 & p2), f"分页重叠: {p1 & p2}"

    def test_missing_attrs_no_crash(self, client, auth_headers):
        """商品 attrs 缺字段时定价/Listing 生成不得 500。

        自包含设计：本用例**自建商品且不添加任何供应商报价**——否则定价会取到
        其他用例为该商品写入的报价（共享库），成本变化导致公式断言随机失败
        （实测出现过 flaky：同一天 3 轮里 1 轮失败）。
        """
        r = client.post("/api/products", headers=auth_headers,
                        json={"title": f"残缺属性商品-{time.time_ns()}", "attrs": {}})
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        r1 = client.post("/api/pricing/calc", headers=auth_headers, json={"product_id": pid})
        assert r1.status_code == 200, r1.text
        calc = r1.json()
        assert calc["product_id"] == pid and calc["price"] > 0
        # 复算真实利润公式（成本项为人民币，需除汇率；佣金按售价×费率）
        expected = (calc["price"]
                    - (calc["purchase_cost"] + calc["logistics_cost"] + calc["ads_cost"]) / calc["fx"]
                    - calc["price"] * calc["platform_fee_rate"])
        assert calc["profit"] == pytest.approx(expected, abs=0.02),             f"利润公式不符：{calc['profit']} vs {expected}"
        # Listing 生成同样不得 500
        r2 = client.post("/api/listings/generate", headers=auth_headers,
                         json={"product_id": pid, "platform": "shopee"})
        assert r2.status_code == 200, r2.text

    def test_1688_signature_contract(self):
        from app.services import open_1688

        path = "/openapi/param2/1/com.alibaba.product/x/KEY"
        params = {"b": "2", "a": "1"}
        expect = hmac.new(b"SEC", b"/openapi/param2/1/com.alibaba.product/x/KEYa1b2",
                          hashlib.sha1).hexdigest().upper()
        assert open_1688.sign(path, params, "SEC") == expect

    def test_shopee_two_signature_modes(self):
        """Shop API 与 Public API 的 base string 必须不同（token/shop_id 是否参与）。"""
        from app.services.platform_adapters import ShopeeAdapter

        shop = SimpleNamespace(app_key="pk", app_secret="sk", shop_id="9",
                               access_token="AT", platform="shopee")
        a = ShopeeAdapter(None, shop)
        ts = 1700000000
        shop_api = hmac.new(b"sk", f"pk/api/v2/x{ts}AT9".encode(), hashlib.sha256).hexdigest()
        public_api = hmac.new(b"sk", f"pk/api/v2/x{ts}".encode(), hashlib.sha256).hexdigest()
        assert a._sign(f"pk/api/v2/x{ts}AT9") == shop_api
        assert a._sign(f"pk/api/v2/x{ts}") == public_api
        assert shop_api != public_api

    def test_tiktok_signature_202309_protocol(self):
        """TikTok Shop 202309+ 签名：HMAC-SHA256(secret, secret+path+排序参数+body+secret)，
        sign/access_token 不参与参数拼接。"""
        from app.services.platform_adapters import TikTokAdapter

        shop = SimpleNamespace(app_key="ak", app_secret="as", access_token="TOK",
                               shop_id="1", platform="tiktok")
        a = TikTokAdapter(None, shop)
        path, body = "/order/search", '{"page_size":20}'
        params = {"app_key": "ak", "timestamp": 1700000000, "access_token": "TOK", "sign": "x"}
        payload = f"as{path}app_keyaktimestamp1700000000{body}as"
        expect = hmac.new(b"as", payload.encode(), hashlib.sha256).hexdigest()
        assert a._sign(path, params, body) == expect
        # body 变化必须导致签名变化
        assert a._sign(path, params, '{"page_size":21}') != expect
        # access_token/sign 不参与拼接：改变它们签名不变
        params2 = dict(params, access_token="OTHER", sign="y")
        assert a._sign(path, params2, body) == expect

    def test_unauthorized_shop_errors_are_actionable(self, client, auth_headers):
        """未授权店铺的同步/发布/代发必须 400 且提示授权（不是 500）。"""
        r = client.post("/api/shops", headers=auth_headers,
                        json={"platform": "shopee", "shop_name": "未授权测试店", "role": "sales"})
        sid = r.json()["id"]
        r = client.post(f"/api/shops/{sid}/sync_orders", headers=auth_headers)
        assert r.status_code == 400 and "授权" in r.json()["detail"]
        client.delete(f"/api/shops/{sid}", headers=auth_headers)

    def test_shop_role_no_mixing(self, client, auth_headers):
        """source 店铺不能上架；sales 店铺不能代发。"""
        # dropship 需关联已付款销售订单，先准备一笔
        client.post("/api/orders/sync", headers=auth_headers, json={"platform": "demo:shopee", "count": 2})
        o = client.get("/api/orders", headers=auth_headers,
                       params={"page_num": 1, "page_size": 5}).json()["items"][0]
        client.put(f"/api/orders/{o['id']}/status", headers=auth_headers, json={"status": "paid"})
        r = client.post("/api/shops", headers=auth_headers,
                        json={"platform": "1688", "shop_name": "货源混用测试", "role": "source", "is_demo": True})
        src = r.json()["id"]
        r = client.post("/api/shops", headers=auth_headers,
                        json={"platform": "shopee", "shop_name": "销售混用测试", "role": "sales", "is_demo": True})
        sales = r.json()["id"]
        # sales 店铺不能代发
        r = client.post("/api/purchases/dropship", headers=auth_headers,
                        json={"shop_id": sales, "product_id": o["product_id"] or 1,
                              "order_id": o["id"], "qty": 1})
        assert r.status_code == 400 and "不可混用" in r.json()["detail"], r.json()
        # source 店铺不能作为上架目标
        pid = client.get("/api/products", headers=auth_headers, params={"page_size": 1}).json()["items"][0]["id"]
        lid = client.post("/api/listings/generate", headers=auth_headers,
                          json={"product_id": pid}).json()["id"]
        r = client.post(f"/api/listings/{lid}/publish", headers=auth_headers, json={"shop_id": src})
        assert r.status_code == 400 and ("货源平台" in r.json()["detail"] or "不能发布到" in r.json()["detail"]), r.json()
        client.delete(f"/api/shops/{src}", headers=auth_headers)
        client.delete(f"/api/shops/{sales}", headers=auth_headers)

    def test_rule_pack_blocks_banned_words(self, client, auth_headers):
        """违禁词双层防护：① 生成期清洗（AI 不产出违规文案）② 发布期硬门禁（人工也绕不过）。"""
        r = client.post("/api/products", headers=auth_headers,
                        json={"title": "含违禁词商品 best seller 最便宜", "category": "家居",
                              "attrs": {"sale_price": 20, "onhand": 5},
                              "images": ["https://example.com/a.jpg"]})
        pid = r.json()["id"]
        # ① 生成期：结果不得含违禁词
        gen = client.post("/api/listings/generate", headers=auth_headers,
                          json={"product_id": pid, "platform": "amazon"}).json()
        text = " ".join([gen["title"], gen.get("description", ""),
                         " ".join(gen.get("bullets") or []),
                         " ".join(gen.get("keywords") or [])]).lower()
        assert "best seller" not in text, f"生成期未清洗违禁词: {gen['title']}"
        lid = gen["id"]
        # ② 发布期：人工写入违禁词后发布必须被拒（硬门禁不可绕过）
        client.put(f"/api/listings/{lid}", headers=auth_headers,
                   json={"title": "Manual best seller listing", "description": "x",
                         "bullets": [], "keywords": []})
        r = client.post(f"/api/listings/{lid}/publish", headers=auth_headers)
        assert r.status_code == 400 and "违禁" in r.json()["detail"], r.json()

    def test_publish_is_idempotent_on_retry(self, client, auth_headers, monkeypatch, register_reviewed_image):
        """重复发布必须幂等：第二次返回 idempotent_replay，且不新建平台尝试记录。

        背景：客户端超时重试是常态，若每次都走一遍发布流程，会在平台侧
        重复创建商品。实现里有两条 idempotent_replay 早返回分支，此前零覆盖。
        """
        from app.db import SessionLocal
        from app.models import PlatformPublishAttempt
        from app.services import platform_adapters

        shop = client.post("/api/shops", headers=auth_headers, json={
            "platform": "shopee", "shop_name": "幂等测试店",
            "app_key": "k", "app_secret": "s"}).json()
        try:
            # 发布要求店铺已授权：走一次真实授权流程（平台端点用假响应替换）
            class _FakeResp:
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(self):
                    # Shopee 适配器要求业务字段包在 response 下
                    return {"response": {"access_token": "AT_IDEM",
                                         "refresh_token": "RT_IDEM",
                                         "expire_in": 86400}}

            monkeypatch.setattr(platform_adapters.httpx, "post",
                                lambda *a, **kw: _FakeResp())
            auth = client.post(f"/api/shops/{shop['id']}/exchange_code",
                               headers=auth_headers, json={"code": "IDEM_CODE"})
            assert auth.status_code == 200, auth.text

            # 直接替换适配器的上架方法：本用例只验证「幂等重放」这一层，
            # 平台侧协议细节（图片上传/类目属性）不是被测对象。
            from app.services.platform_adapters import PublishResult
            configured = client.put(f"/api/shops/{shop['id']}", headers=auth_headers,
                                    json={"market": "SG"})
            assert configured.status_code == 200, configured.text
            calls = {"n": 0}

            def _fake_publish(self, listing, product, *, resume=None, checkpoint=None):
                calls["n"] += 1
                return PublishResult(external_id=f"EXT-{listing.id}",
                                     url="https://example.com/p/1",
                                     raw={"mocked": True})

            monkeypatch.setattr(platform_adapters.ShopeeAdapter,
                                "publish_listing", _fake_publish)

            pid = client.post("/api/products", headers=auth_headers, json={
                "title": "幂等发布探针商品", "category": "家居",
                "attrs": {"sale_price": 20, "onhand": 5, "supplier_price": 5},
                "images": ["https://example.com/a.jpg"]}).json()["id"]
            register_reviewed_image(pid, shop["id"], uri="https://example.com/a.jpg")
            lid = client.post("/api/listings/generate", headers=auth_headers,
                              json={"product_id": pid, "platform": "shopee"}).json()["id"]

            first = client.post(f"/api/listings/{lid}/publish", headers=auth_headers,
                                json={"shop_id": shop["id"]})
            assert first.status_code == 200, first.text
            assert calls["n"] == 0, "审批前不得调用真实发布适配器"
            from .action_helpers import approve_and_execute
            published = approve_and_execute(client, auth_headers, first.json())
            assert not published.get("idempotent_replay"), "首次执行不应标记为重放"
            assert calls["n"] == 1

            with SessionLocal() as db:
                attempts_1 = db.query(PlatformPublishAttempt).filter(
                    PlatformPublishAttempt.listing_id == lid).count()

            second = client.post(f"/api/listings/{lid}/publish", headers=auth_headers,
                                 json={"shop_id": shop["id"]})
            assert second.status_code == 200, second.text
            assert second.json().get("idempotent_replay") is True, (
                f"重复发布应命中幂等重放，实际: {second.json()}")
            assert second.json()["action_id"] == first.json()["action_id"]
            assert calls["n"] == 1, "重放不得再次调用外部发布"

            with SessionLocal() as db:
                attempts_2 = db.query(PlatformPublishAttempt).filter(
                    PlatformPublishAttempt.listing_id == lid).count()
            assert attempts_2 == attempts_1, (
                f"重复发布不应新建平台尝试记录：{attempts_1} -> {attempts_2}")
        finally:
            client.delete(f"/api/shops/{shop['id']}", headers=auth_headers)
