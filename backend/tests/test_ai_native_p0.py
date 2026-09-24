"""P0 AI 原生能力验收：M1 选品数据飞轮 / M3 主动巡检 / M6 决策解释。

方案依据：docs/AI原生能力升级方案.md（定稿）
四条设计红线：
  1) AI 巡检只告警不执行  2) 自动学习可撤销（M4，本轮未实施）
  3) 演示数据不进飞轮      4) 决策审计只增不删
"""
import time
from datetime import datetime, timedelta


class TestSelectionFlywheel:
    """M1：真实经营结果反哺选品评分。"""

    def test_performance_endpoint(self, client, auth_headers):
        """表现分端点可用，无真实订单时返回中性分 50 且 has_data=False。"""
        # 自建商品：不依赖种子存量（purge 用例会清空全租户业务数据，
        # 依赖 `items[0]` 会形成跨文件顺序依赖，违反规范 §8 T-2）。
        pid = client.post("/api/products", headers=auth_headers, json={
            "title": "表现分中性态测试品", "category": "家居",
            "attrs": {"supplier_price": 10, "sale_price": 25, "onhand": 5,
                      "weight_kg": 0.3}}).json()["id"]
        r = client.get(f"/api/discovery/performance/{pid}", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d) >= {"product_id", "performance_score", "has_data", "computed_at"}
        assert d["product_id"] == pid
        # 断言具体值而非区间：`0 <= score <= 100` 是恒真式（实现已对三项分项做
        # clamp），无法发现"新品被误判为有数据"或"中性分被改坏"。
        assert d["has_data"] is False, f"全新商品不应有真实经营数据: {d}"
        assert d["performance_score"] == 50.0, f"无数据时应为中性分 50: {d}"

    def test_real_orders_raise_score(self, client, auth_headers):
        """红线 3：真实订单（import 来源）应提升表现分；演示数据不影响。"""
        r = client.post("/api/products", headers=auth_headers,
                        json={"title": "飞轮测试商品 高销量", "category": "家居",
                              "attrs": {"supplier_price": 10, "sale_price": 40,
                                        "onhand": 5, "weight_kg": 0.3}})
        pid = r.json()["id"]
        before = client.get(f"/api/discovery/performance/{pid}",
                            headers=auth_headers).json()
        assert before["has_data"] is False and before["performance_score"] == 50.0

        # 导入 10 笔真实订单（source=import，高毛利）
        sku = client.get("/api/products", headers=auth_headers,
                         params={"page_size": 1}).json()["items"][0]["sku"]
        stamp = int(time.time())
        # 订单日期必须相对当前时间：表现分走 30 天窗口（product_performance.
        # _window_metrics），写死日期会在 30 天后让 units_sold 归零、用例永久失败。
        recent = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        lines = ["external_no,platform,qty,amount,status,sku,country,buyer_name,created_at"]
        for i in range(10):
            lines.append(f"FLY-{stamp}-{i},shopee,1,40.00,delivered,{sku},US,B{i},{recent}")
        r = client.post("/api/orders/import", headers=auth_headers,
                        json={"csv_text": "\n".join(lines)})
        assert r.status_code == 200 and r.json()["imported"] == 10, r.text
        # 关联订单到该商品（CSV 的 sku 列指向其他商品，这里直接改 product_id 更精确）
        from app.db import SessionLocal
        from app.models import Order

        db = SessionLocal()
        try:
            for o in db.query(Order).filter(Order.external_no.like(f"FLY-{stamp}-%")).all():
                o.product_id = pid
            db.commit()
        finally:
            db.close()

        after = client.get(f"/api/discovery/performance/{pid}",
                           headers=auth_headers).json()
        assert after["has_data"] is True, after
        assert after["units_sold"] >= 10
        assert after["performance_score"] != 50.0, "有真实销售后表现分应变化"

    def test_scoring_uses_performance(self, client, auth_headers):
        """评分 reasons 必须体现经营表现，且表现分要真正参与打分。

        原断言是 `"表现分" in reasons or "暂无真实销售数据" in reasons`——
        reasons 由实现按构造必然含其一，属于恒真断言（永不失败）。
        这里改为造真实订单后断言具体数值与总分变化。
        """
        from app.db import SessionLocal
        from app.models import Order, ProductPerformance, User

        pid = client.post("/api/products", headers=auth_headers, json={
            "title": "回归-评分反馈探针", "category": "家居",
            "attrs": {"supplier_price": 10, "sale_price": 40,
                      "onhand": 100, "weight_kg": 0.3},
        }).json()["id"]
        db = SessionLocal()
        try:
            tenant_id = db.query(User).filter(User.username == "admin").first().tenant_id
            # 先在没有销售数据时评一次
            r0 = client.post(f"/api/discovery/score/{pid}", headers=auth_headers)
            assert r0.status_code == 200, r0.text
            assert "暂无真实销售数据" in " ".join(r0.json()["reasons"]), r0.json()

            for i in range(12):
                db.add(Order(tenant_id=tenant_id, external_no=f"SC-{i}",
                             platform="shopee", qty=1, amount=40.0, profit=20.0,
                             status="delivered", product_id=pid, source="import"))
            db.commit()
            # 有真实销售后重评：reasons 必须给出具体件数，而不是中性分话术
            r1 = client.post(f"/api/discovery/score/{pid}", headers=auth_headers)
            assert r1.status_code == 200, r1.text
            reasons = " ".join(r1.json()["reasons"])
            assert "售出 12 件" in reasons, reasons
            assert "暂无真实销售数据" not in reasons, reasons
            assert r1.json()["total"] != r0.json()["total"], (
                "表现分未参与总分：有真实销售后总分应变化")
        finally:
            db.query(Order).filter(Order.product_id == pid).delete(synchronize_session=False)
            db.query(ProductPerformance).filter(
                ProductPerformance.product_id == pid).delete(synchronize_session=False)
            db.commit()
            db.close()

    def test_pick_threshold_is_enforced(self, client):
        """门槛守护：低于 60 分的候选必须被 pick 排除。

        为什么必须隔离租户（回退法实测教训）：
          演示租户里种子商品的机会分普遍 >= 60，占满了 limit 窗口——把
          `pick_candidates` 的 `min_total` 默认值变异为 0 后，`test_discovery_flow`
          里"结果非空"和"候选都 >= 60 分"两条断言**都仍然通过**（低分商品本来就
          挤不进前 19 名）。只有在"租户内候选全部低于门槛"的隔离场景里，
          门槛失效才会让结果从空变非空，断言才真正有判别力（规范 §8 T-11）。
        """
        from app.agents.discovery import DiscoveryAgent
        from app.db import SessionLocal
        from app.models import Product, ProductScore, Tenant, utcnow

        db = SessionLocal()
        try:
            tenant = Tenant(name="选品门槛守护租户", plan="trial", status="active",
                            license_until=utcnow() + timedelta(days=1))
            db.add(tenant)
            db.flush()
            for i in range(3):
                p = Product(tenant_id=tenant.id, sku=f"THR-{tenant.id}-{i}",
                            title=f"低分守护商品{i}", category="门槛守护类目",
                            attrs={}, images=[])
                db.add(p)
                db.flush()
                # total=20 明确低于门槛 60；competition/risk 取高值以贴近真实低分形态
                db.add(ProductScore(tenant_id=tenant.id, product_id=p.id,
                                    demand=10, competition=95, profit=5, risk=80,
                                    total=20.0, reasons=["低分守护"], model="rule"))
            db.commit()
            tenant_id = tenant.id
        finally:
            db.close()

        try:
            with DiscoveryAgent(tenant_id) as agent:
                default_call = agent.pick_candidates(limit=3)
            assert default_call["items"] == [], (
                f"低于门槛(60)的候选被推出了，门槛形同虚设: {default_call['items']}")
            with DiscoveryAgent(tenant_id) as agent:
                explicit_zero = agent.pick_candidates(limit=3, min_total=0)
            assert len(explicit_zero["items"]) == 3, (
                f"显式传 min_total=0 时应返回全部 3 个候选: {explicit_zero['items']}")
            assert all(i["total"] == 20.0 for i in explicit_zero["items"]), explicit_zero
        finally:
            db = SessionLocal()
            try:
                db.query(ProductScore).filter(
                    ProductScore.tenant_id == tenant_id).delete(synchronize_session=False)
                db.query(Product).filter(
                    Product.tenant_id == tenant_id).delete(synchronize_session=False)
                db.query(Tenant).filter(Tenant.id == tenant_id).delete(synchronize_session=False)
                db.commit()
            finally:
                db.close()

    def test_explore_quota(self, client, auth_headers):
        """探索配额：必须真的留出名额给「无真实销售的新品」。

        原断言 `"explore_floor" in body` 是恒真断言——实现无条件返回该键
        （无配额时为 None），永不失败，等于 M1 探索配额整块没有覆盖。
        """
        # 自建候选：探索配额要求 ranked 里至少有 limit 个候选（常规名额 limit-1，
        # 留 1 个给探索位）。依赖种子评分会在清库用例之后让 ranked 为空，
        # reserve 直接归零（实测跨文件组合跑必挂，规范 §8 T-2）。
        # 三个同参数商品 → 分数接近，保证最低分也 >= 中位数×0.7（探索位门槛）。
        for i in range(3):
            pid = client.post("/api/products", headers=auth_headers, json={
                "title": f"探索配额探针商品{i + 1}", "category": "探索配额探针类目",
                "attrs": {"supplier_price": 6.0, "sale_price": 20.0, "weight_kg": 0.3,
                          "material": "silicone", "color": "blue", "scene": "home"},
            }).json()["id"]
            scored = client.post(f"/api/discovery/score/{pid}", headers=auth_headers)
            assert scored.status_code == 200, scored.text
        r = client.post("/api/discovery/pick", headers=auth_headers, json={"limit": 3})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["items"], "选品结果不应为空"
        # limit>=2 且有候选时必须启用探索配额（reserve=1）
        assert body["explore_floor"] is not None, (
            f"limit=3 时探索配额未启用: {body.get('explore_floor')}")
        assert isinstance(body["explore_floor"], (int, float)), body["explore_floor"]
        explores = [i for i in body["items"] if i.get("explore_pick")]
        assert explores, (
            f"limit=3 应保留 1 个探索名额给新品，实际结果: "
            f"{[(i['product_id'], i.get('explore_pick')) for i in body['items']]}")
        assert len(explores) == 1, f"探索名额应恰好 1 个，实际 {len(explores)}"
        # 探索位的理由必须写明是探索配额（用户要能看出为什么推这个新品）
        assert any("探索配额" in x for x in explores[0]["reasons"]), explores[0]["reasons"]


class TestAlertScanning:
    """M3：主动巡检，只告警不执行（红线 1）。"""

    def test_default_rules_initialized(self, client, auth_headers):
        """9 条默认规则可用且可配置。"""
        r = client.get("/api/alerts/rules", headers=auth_headers)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        keys = {i["key"] for i in items}
        expected = {"stockout_risk", "ads_burning", "price_below_floor", "policy_changed",
                    "refund_spike", "supplier_delay", "fx_volatility", "shipping_degraded",
                    "listing_stale"}
        assert expected <= keys, f"缺少规则: {expected - keys}"
        assert all(i["enabled"] for i in items)

    def test_scan_detects_stockout(self, client, auth_headers):
        """造断货商品（有销量、库存 0）→ 巡检产生 high 告警，含具体数值。"""
        r = client.post("/api/products", headers=auth_headers,
                        json={"title": "断货测试商品", "category": "家居",
                              "attrs": {"supplier_price": 8, "sale_price": 30,
                                        "onhand": 0, "weight_kg": 0.3}})
        pid = r.json()["id"]
        # 造真实销量（import 来源），使周需求 > 0
        sku = client.get("/api/products", headers=auth_headers,
                         params={"page_size": 1}).json()["items"][0]["sku"]
        stamp = int(time.time())
        # 同上：断货判定走 28 天窗口（alerting._weekly_demand），日期必须相对当前时间
        recent = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        lines = ["external_no,platform,qty,amount,status,sku,country,buyer_name,created_at"]
        for i in range(12):
            lines.append(f"STK-{stamp}-{i},shopee,1,30.00,delivered,{sku},US,C{i},{recent}")
        client.post("/api/orders/import", headers=auth_headers,
                    json={"csv_text": "\n".join(lines)})
        from app.db import SessionLocal
        from app.models import Order

        db = SessionLocal()
        try:
            for o in db.query(Order).filter(Order.external_no.like(f"STK-{stamp}-%")).all():
                o.product_id = pid
            db.commit()
        finally:
            db.close()

        r = client.post("/api/alerts/scan", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["created"] >= 1, r.json()

        alerts = client.get("/api/alerts", headers=auth_headers,
                            params={"level": "high"}).json()["items"]
        stockout = [a for a in alerts if a["rule_key"] == "stockout_risk"
                    and a["subject_id"] == pid]
        assert stockout, "未产生断货告警"
        a = stockout[0]
        assert a["level"] == "high" and "周需求" in a["detail"], a

    def test_alert_dedupe(self, client, auth_headers):
        """同一告警 24h 内不重复产生（防疲劳）。"""
        client.post("/api/alerts/scan", headers=auth_headers)
        r2 = client.post("/api/alerts/scan", headers=auth_headers)
        assert r2.status_code == 200
        assert r2.json()["created"] == 0, f"重复巡检应无新告警: {r2.json()}"
        assert r2.json()["skipped"] >= 1

    def test_alert_ack_not_delete(self, client, auth_headers):
        """确认告警只标记状态，不删除（保留审计痕迹）。"""
        # 自建告警：原实现是「库里有告警才测，没有就 skip」，单跑时必然静默跳过，
        # 审计留痕校验形同不存在（规范 §8 T-2：不得依赖前序用例产出）。
        # 造一条必然触发断货告警的商品（周需求 > 0 且库存为 0）。
        stamp = int(time.time())
        recent = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        pid = client.post("/api/products", headers=auth_headers, json={
            "title": f"告警确认测试品{stamp}", "category": "家居",
            "attrs": {"supplier_price": 8, "sale_price": 30, "onhand": 0,
                      "weight_kg": 0.3}}).json()["id"]
        lines = ["external_no,platform,qty,amount,status,sku,country,buyer_name,created_at"]
        for i in range(12):
            lines.append(f"ACK-{stamp}-{i},shopee,1,30.00,delivered,,US,D{i},{recent}")
        client.post("/api/orders/import", headers=auth_headers,
                    json={"csv_text": "\n".join(lines)})
        from app.db import SessionLocal
        from app.models import Order

        with SessionLocal() as db:
            for o in db.query(Order).filter(Order.external_no.like(f"ACK-{stamp}-%")).all():
                o.product_id = pid
            db.commit()
        client.post("/api/alerts/scan", headers=auth_headers)

        alerts = client.get("/api/alerts", headers=auth_headers).json()["items"]
        mine = [a for a in alerts if a["subject_id"] == pid]
        assert mine, "自建断货商品未产生告警，无法验证确认语义"
        aid = mine[0]["id"]
        r = client.put(f"/api/alerts/{aid}/ack", headers=auth_headers)
        assert r.status_code == 200 and r.json()["status"] == "acked"
        assert r.json()["acked_at"], "确认时间应写入"
        # 仍能查到
        after = client.get("/api/alerts", headers=auth_headers,
                           params={"status": "acked"}).json()["items"]
        assert any(a["id"] == aid for a in after)

    def test_rule_toggle_and_threshold(self, client, auth_headers):
        """规则可停用、阈值可调（论证修正项）。"""
        rules = client.get("/api/alerts/rules", headers=auth_headers).json()["items"]
        rule = next(r for r in rules if r["key"] == "listing_stale")
        r = client.put(f"/api/alerts/rules/{rule['id']}", headers=auth_headers,
                       json={"enabled": False, "threshold": {"days": 60}})
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert r.json()["threshold"]["days"] == 60
        # 恢复
        client.put(f"/api/alerts/rules/{rule['id']}", headers=auth_headers,
                   json={"enabled": True, "threshold": {"days": 30}})

    def test_threshold_is_a_live_parameter(self, client, auth_headers):
        """缺陷回归：阈值必须是活参数（改配置要真的改变判定行为）。

        原用例只回读 PUT 响应，从不验证「改了阈值后扫描行为是否变化」——
        实现把行为常量写死（如备货周数硬编码 4）时用例照样通过。
        这里用 stockout_risk.weeks：调到 99 应不再告警，调回 1 应恢复告警。
        """
        from app.db import SessionLocal
        from app.models import AlertEvent, Order, User

        pid = client.post("/api/products", headers=auth_headers, json={
            "title": "回归-活参数探针", "category": "家居",
            "attrs": {"supplier_price": 10, "sale_price": 40,
                      "onhand": 20, "weight_kg": 0.3},
        }).json()["id"]
        db = SessionLocal()
        try:
            tenant_id = db.query(User).filter(User.username == "admin").first().tenant_id
            # 造出稳定周需求（近 28 天 28 件 => 周需求 7 件），在手 20 件。
            # 触发条件是 onhand < demand * weeks：
            #   weeks=1 -> 20 >= 7  不告警
            #   weeks=5 -> 20 < 35  告警
            for i in range(28):
                db.add(Order(tenant_id=tenant_id, external_no=f"TH-{i}",
                             platform="shopee", qty=1, amount=40.0, profit=20.0,
                             status="delivered", product_id=pid, source="import"))
            db.commit()
        finally:
            db.close()

        rule = next(r for r in client.get("/api/alerts/rules", headers=auth_headers)
                    .json()["items"] if r["key"] == "stockout_risk")

        def fired() -> bool:
            """跑一轮巡检，看**本轮**是否对该商品触发断货规则。

            两个坑都要绕开：
              1. 不能查告警列表——24h 去重窗口内上一轮的告警仍在列表里；
              2. 不能看 scan 的 by_rule——那是全租户计数，别的商品会污染。
            做法：先清掉该商品的既有告警，跑完再看它是否重新出现。
            """
            with SessionLocal() as s:
                s.query(AlertEvent).filter(
                    AlertEvent.rule_key == "stockout_risk",
                    AlertEvent.subject_type == "product",
                    AlertEvent.subject_id == pid).delete(synchronize_session=False)
                s.commit()
            client.post("/api/alerts/scan", headers=auth_headers)
            with SessionLocal() as s:
                return s.query(AlertEvent).filter(
                    AlertEvent.rule_key == "stockout_risk",
                    AlertEvent.subject_type == "product",
                    AlertEvent.subject_id == pid).count() > 0

        try:
            # 先把阈值调到 5 周：在手 20 件不够 35 件需求 -> 必须告警
            client.put(f"/api/alerts/rules/{rule['id']}", headers=auth_headers,
                       json={"threshold": {"weeks": 5}})
            assert fired(), "阈值 weeks=5 时 20 件库存不足 35 件需求，应告警"

            # 调回 1 周：在手 20 件够 1 周需求 -> 不应再告警（证明阈值真的生效）
            client.put(f"/api/alerts/rules/{rule['id']}", headers=auth_headers,
                       json={"threshold": {"weeks": 1}})
            assert not fired(), "阈值调回 weeks=1 后仍告警 -> 阈值是死参数"
        finally:
            client.put(f"/api/alerts/rules/{rule['id']}", headers=auth_headers,
                       json={"threshold": {"weeks": 1}})
            db = SessionLocal()
            from app.models import AlertEvent, ProductPerformance

            db.query(AlertEvent).filter(AlertEvent.subject_id == pid).delete(
                synchronize_session=False)
            db.query(Order).filter(Order.product_id == pid).delete(
                synchronize_session=False)
            db.query(ProductPerformance).filter(
                ProductPerformance.product_id == pid).delete(synchronize_session=False)
            db.commit()
            db.close()

    def test_no_auto_execution(self, client, auth_headers):
        """红线 1：巡检只写告警，不得改动商品/Listing 等业务数据。"""
        before = client.get("/api/products", headers=auth_headers,
                            params={"page_size": 1}).json()["total"]
        snap = client.get("/api/products", headers=auth_headers,
                          params={"page_size": 5}).json()["items"]
        client.post("/api/alerts/scan", headers=auth_headers)
        after = client.get("/api/products", headers=auth_headers,
                           params={"page_size": 5}).json()["items"]
        assert before == client.get("/api/products", headers=auth_headers,
                                    params={"page_size": 1}).json()["total"]
        # 商品属性未被巡检修改
        before_map = {p["id"]: p["attrs"] for p in snap}
        for p in after:
            if p["id"] in before_map:
                assert p["attrs"] == before_map[p["id"]], f"巡检改动了商品 {p['id']}"


class TestDecisionExplanation:
    """M6：AI 决策可追溯，只增不删（红线 4）。"""

    def test_score_records_decision(self, client, auth_headers):
        """评分后能查到决策记录及其依据链。"""
        pid = client.get("/api/products", headers=auth_headers,
                         params={"page_size": 1}).json()["items"][0]["id"]
        client.post(f"/api/discovery/score/{pid}", headers=auth_headers)
        r = client.get("/api/ai/decisions", headers=auth_headers,
                       params={"subject_type": "product", "subject_id": pid})
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert items, "未记录决策"
        d = items[0]
        assert d["action"] == "score_product" and d["agent"] == "discovery"
        assert set(d["decision"]) >= {"total", "demand", "competition"}
        assert "reasons" in d["evidence"], "依据链应含评分理由"

    def test_decision_evidence_traceable(self, client, auth_headers):
        """依据链中的引用必须能追溯到真实数据（趋势 id / 表现记录 id）。"""
        pid = client.get("/api/products", headers=auth_headers,
                         params={"page_size": 1}).json()["items"][0]["id"]
        client.post(f"/api/discovery/score/{pid}", headers=auth_headers)
        items = client.get("/api/ai/decisions", headers=auth_headers,
                           params={"subject_type": "product", "subject_id": pid}).json()["items"]
        ev = items[0]["evidence"]
        assert "category" in ev
        # 若引用了趋势，则该 id 必须真实存在
        if ev.get("trend_id"):
            trends = client.get("/api/discovery/trends", headers=auth_headers).json()["items"]
            assert ev["trend_id"] in {t["id"] for t in trends}, "依据链引用了不存在的趋势"

    def test_decision_filter_by_agent(self, client, auth_headers):
        """决策可按 agent 过滤。"""
        r = client.get("/api/ai/decisions", headers=auth_headers,
                       params={"agent": "discovery", "limit": 10})
        assert r.status_code == 200
        items = r.json()["items"]
        # 先断言非空：`all()` 在空列表上恒真，筛选逻辑回归成返回空也照样通过。
        assert items, "按 agent=discovery 过滤不应为空"
        assert all(i["agent"] == "discovery" for i in items)

    def test_decisions_append_only(self, client, auth_headers):
        """红线 4：决策记录只增不删（多次评分累积多条，旧记录仍在）。"""
        pid = client.get("/api/products", headers=auth_headers,
                         params={"page_size": 1}).json()["items"][0]["id"]
        for _ in range(2):
            client.post(f"/api/discovery/score/{pid}", headers=auth_headers)
        items = client.get("/api/ai/decisions", headers=auth_headers,
                           params={"subject_type": "product", "subject_id": pid}).json()["items"]
        assert len(items) >= 2, f"应有累积决策记录，实际 {len(items)}"


class TestRegressionGuards:
    """已修复缺陷的回归守卫（放在文件末尾：会造批量数据，避免影响其他用例）。"""

    def test_performance_cache_invalidates_on_order_change(self, client, auth_headers):
        """缺陷回归：窗口内订单数变化时表现分缓存必须失效重算。

        修复前只比较「有无订单」（``units_sold > 0``），实测 5 单变 25 单后仍
        返回旧值——AI 评分会长期吃陈旧经营数据。
        """
        from app.db import SessionLocal
        from app.models import Order, ProductPerformance, User
        from app.services.product_performance import get_performance

        pid = client.post("/api/products", headers=auth_headers, json={
            "title": "回归-缓存失效探针", "category": "家居",
            "attrs": {"supplier_price": 10, "sale_price": 40,
                      "onhand": 500, "weight_kg": 0.3},
        }).json()["id"]
        db = SessionLocal()
        try:
            tenant_id = db.query(User).filter(User.username == "admin").first().tenant_id

            def add_orders(n, tag):
                for i in range(n):
                    db.add(Order(tenant_id=tenant_id, external_no=f"REG-{tag}-{i}",
                                 platform="shopee", qty=1, amount=40.0, profit=20.0,
                                 status="delivered", product_id=pid, source="import"))
                db.commit()

            add_orders(5, "A")
            first = get_performance(db, tenant_id, pid)
            add_orders(20, "B")
            second = get_performance(db, tenant_id, pid)
        finally:
            db.query(Order).filter(Order.product_id == pid).delete(synchronize_session=False)
            db.query(ProductPerformance).filter(
                ProductPerformance.product_id == pid).delete(synchronize_session=False)
            db.commit()
            db.close()

        assert first["units_sold"] == 5, first
        assert second["units_sold"] == 25, (
            f"订单 5→25 后缓存未失效，仍返回 {second['units_sold']} 件")

    def test_performance_cache_invalidates_on_partial_refund(self, client, auth_headers):
        """缺陷回归：部分退款必须让表现分失效重算。

        部分退款（refund qty < order qty）**不改订单状态**，所以订单侧的
        销量/销售额/利润三项完全不变。若缓存指纹只看这三项，退款率会陈旧
        （实测：10 单里退 1 单，refund_rate 仍为 0.0）。
        """
        from app.db import SessionLocal
        from app.models import Order, ProductPerformance, RefundOrder, User
        from app.services.product_performance import get_performance

        pid = client.post("/api/products", headers=auth_headers, json={
            "title": "回归-部分退款探针", "category": "家居",
            "attrs": {"supplier_price": 10, "sale_price": 40,
                      "onhand": 500, "weight_kg": 0.3},
        }).json()["id"]
        db = SessionLocal()
        try:
            tenant_id = db.query(User).filter(User.username == "admin").first().tenant_id
            for i in range(10):
                db.add(Order(tenant_id=tenant_id, external_no=f"RF-{i}",
                             platform="shopee", qty=2, amount=80.0, profit=40.0,
                             status="delivered", product_id=pid, source="import"))
            db.commit()
            order_id = db.query(Order).filter(Order.product_id == pid).first().id

            before = get_performance(db, tenant_id, pid)
            # 部分退款：退 1 件，订单 qty=2 不变 -> 订单侧三项全不变
            db.add(RefundOrder(tenant_id=tenant_id, refund_no=f"RF-PR-{order_id}",
                               order_id=order_id, type="return_refund", qty=1,
                               amount=40.0, reason="size", status="refunded"))
            db.commit()
            after = get_performance(db, tenant_id, pid)
        finally:
            db.query(RefundOrder).filter(
                RefundOrder.refund_no.like("RF-PR-%")).delete(synchronize_session=False)
            db.query(Order).filter(Order.product_id == pid).delete(synchronize_session=False)
            db.query(ProductPerformance).filter(
                ProductPerformance.product_id == pid).delete(synchronize_session=False)
            db.commit()
            db.close()

        assert before["refund_rate"] == 0.0, before
        assert after["refund_rate"] == 0.1, (
            f"部分退款后退款率未更新，仍为 {after['refund_rate']}")
        assert after["performance_score"] < before["performance_score"], (
            "退款率上升后表现分应下降")

    def test_performance_cache_invalidates_on_stock_change(self, client, auth_headers):
        """缺陷回归：库存变化必须让表现分失效重算（售罄率依赖 onhand）。

        收货入库 / 退货入库只改商品 attrs.onhand，订单表完全不变。
        """
        from app.db import SessionLocal
        from app.models import Order, Product, ProductPerformance, User
        from app.services.product_performance import get_performance

        pid = client.post("/api/products", headers=auth_headers, json={
            "title": "回归-库存变化探针", "category": "家居",
            "attrs": {"supplier_price": 10, "sale_price": 40,
                      "onhand": 10, "weight_kg": 0.3},
        }).json()["id"]
        db = SessionLocal()
        try:
            tenant_id = db.query(User).filter(User.username == "admin").first().tenant_id
            for i in range(10):
                db.add(Order(tenant_id=tenant_id, external_no=f"ST-{i}",
                             platform="shopee", qty=1, amount=40.0, profit=20.0,
                             status="delivered", product_id=pid, source="import"))
            db.commit()
            before = get_performance(db, tenant_id, pid)

            p = db.get(Product, pid)
            attrs = dict(p.attrs or {})
            attrs["onhand"] = 490           # 收货入库 480 件
            p.attrs = attrs
            db.commit()
            after = get_performance(db, tenant_id, pid)
        finally:
            db.query(Order).filter(Order.product_id == pid).delete(synchronize_session=False)
            db.query(ProductPerformance).filter(
                ProductPerformance.product_id == pid).delete(synchronize_session=False)
            db.commit()
            db.close()

        assert before["sell_through"] != after["sell_through"], (
            f"库存变化后售罄率未更新，仍为 {after['sell_through']}")

    def test_high_risk_visible_beyond_limit(self, client, auth_headers):
        """缺陷回归：高风险告警不得被大量更新的低风险告警挤出 limit。

        修复前是「先按时间取 limit 条，再在内存按级别排序」：实测 120 条新低
        风险 + 1 条较早高风险时，高风险完全不可见——最该处理的反而漏报。
        """
        from datetime import timedelta

        from app.db import SessionLocal
        from app.models import AlertEvent, User, utcnow

        db = SessionLocal()
        try:
            tenant_id = db.query(User).filter(User.username == "admin").first().tenant_id
            db.add(AlertEvent(tenant_id=tenant_id, rule_key="_reg_high", level="high",
                              subject_type="product", subject_id=0,
                              title="回归-高风险可见性", detail="较早的高风险告警",
                              evidence={}, status="open",
                              created_at=utcnow() - timedelta(days=10)))
            for i in range(120):
                db.add(AlertEvent(tenant_id=tenant_id, rule_key="_reg_low", level="low",
                                  subject_type="listing", subject_id=1000 + i,
                                  title=f"回归-低风险-{i}", detail="较新的低风险告警",
                                  evidence={}, status="open",
                                  created_at=utcnow() - timedelta(minutes=i)))
            db.commit()
        finally:
            db.close()

        try:
            body = client.get("/api/alerts", headers=auth_headers,
                              params={"status": "open", "limit": 100}).json()
            items = body["items"]
            keys = [a["rule_key"] for a in items]
            assert "_reg_high" in keys, "高风险告警被 limit 挤出结果（漏报）"
            # 级别排序必须整体成立：high 全部排在 mid 之前、mid 排在 low 之前。
            # （不断言「高风险一定是第一条」——库里可能还有其它更高优先级的真实
            #  高风险告警，那是正确行为。）
            ranks = {"high": 0, "mid": 1, "low": 2}
            got = [ranks.get(a["level"], 9) for a in items]
            assert got == sorted(got), f"告警未按级别排序: {[(a['level'], a['rule_key']) for a in items[:5]]}"
            assert body["counts"]["high"] >= 1, body["counts"]
        finally:
            db = SessionLocal()
            db.query(AlertEvent).filter(
                AlertEvent.rule_key.in_(["_reg_high", "_reg_low"])
            ).delete(synchronize_session=False)
            db.commit()
            db.close()
