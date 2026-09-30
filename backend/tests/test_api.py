"""端到端 API 测试：离线规则模式下全链路可运行（零 LLM 配置）。

共享夹具（``client`` / ``auth_headers`` / 会话级库清理）定义在 ``tests/conftest.py``，
由 pytest 自动注入，避免跨模块 import 引入的收集顺序依赖（规范 §8 T-2）。
"""
from datetime import datetime


def _wait_run(client, auth_headers, run_id: int, timeout: float = 15.0) -> dict:
    """轮询等待工作流运行结束（异步模式下 POST 返回时仍是 running）。

    避免测试依赖执行速度：单机同步模式立即返回，后台线程模式最多等 timeout 秒。
    """
    import time as _t

    deadline = _t.time() + timeout
    detail = {}
    while _t.time() < deadline:
        detail = client.get(f"/api/workflows/runs/{run_id}", headers=auth_headers).json()
        if detail.get("status") not in ("running", "queued", "pending"):
            return detail
        _t.sleep(0.2)
    return detail

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_auth_flow(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    r = client.get("/api/products")
    assert r.status_code == 401  # 未登录
    # 口令错误分支必须用一次性探针账号：对 admin 连续失败会累加 LoginAttempt
    # （窗口 900s、阈值 5），一旦其它文件再失败几次，后续用例会被锁成 15 分钟
    # 429，形成"谁先跑谁通过"的跨文件顺序依赖（规范 §8 T-2）。
    r = client.post("/api/auth/login",
                    json={"username": "probe_wrong_password", "password": "wrong"})
    assert r.status_code == 400


def test_products_and_collect(client, auth_headers):
    # 自建前置数据：本用例不依赖种子商品池——test_shop_archive_and_purge 会清空
    # 租户业务数据，靠种子断言会形成跨文件顺序依赖（规范 §8 T-2，实测反序 7 failed）。
    collected = client.post("/api/products/collect", headers=auth_headers,
                            json={"source_platform": "1688", "keyword": "pet",
                                  "count": 20})
    assert collected.status_code == 200 and collected.json()["collected"] == 20
    r = client.get("/api/products", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 20
    pid = collected.json()["items"][0]["id"]
    r = client.get(f"/api/products/{pid}", headers=auth_headers)
    assert r.status_code == 200
    assert "scores" in r.json() and "offers" in r.json()
    r = client.post("/api/products/collect", headers=auth_headers,
                    json={"source_platform": "1688", "keyword": "pet", "count": 3})
    assert r.status_code == 200 and r.json()["collected"] == 3


def test_discovery_flow(client, auth_headers):
    r = client.post("/api/discovery/trends/scan", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()["items"]) >= 10
    r = client.post("/api/discovery/expand", headers=auth_headers, json={"keyword": "yoga mat"})
    assert r.status_code == 200 and len(r.json()["keywords"]) >= 8
    # 自建候选：pick_candidates 只从 ProductScore 里选（门槛 60 分）。
    # 依赖种子评分会在清库用例之后拿不到任何候选（规范 §8 T-2，实测 assert 0 >= 1）。
    # 类目取唯一值：竞争分 = 20 + 同类目商品数×2.5，唯一类目才给得出高机会分。
    product = client.post("/api/products", headers=auth_headers, json={
        "title": "Discovery Probe Pet Grooming Glove", "category": "选品探针类目",
        "attrs": {"sale_price": 19.99, "supplier_price": 6.5, "weight_kg": 0.3,
                  "material": "silicone", "color": "blue", "scene": "home"}})
    assert product.status_code == 200, product.text
    pid = product.json()["id"]
    scored = client.post(f"/api/discovery/score/{pid}", headers=auth_headers)
    assert scored.status_code == 200 and "total" in scored.json()
    assert scored.json()["total"] >= 60, "唯一类目+高毛利商品的规则分应达选品门槛"
    r = client.post("/api/discovery/pick", headers=auth_headers, json={"limit": 20})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1, "自建评分商品后选品池不应为空"
    # 门槛是硬不变量：候选一律 >= 60 分。这条能抓住"门槛被改成 0/被删掉"的回归——
    # 实测把 min_total 默认值变异为 0 时，仅断言"结果非空"无法发现（低分商品本来
    # 也挤不进前 19 名），必须断言分数下界。
    assert all(i["total"] >= 60 for i in items), items
    # 每个候选都必须是本租户可见的有效商品（防越权泄漏 / 防僵尸 ID）
    for item in items:
        detail = client.get(f"/api/products/{item['product_id']}", headers=auth_headers)
        assert detail.status_code == 200, item


def test_supplier_flow(client, auth_headers):
    r = client.get("/api/suppliers", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()["items"]) >= 8
    sid = r.json()["items"][0]["id"]
    r = client.post(f"/api/suppliers/{sid}/score", headers=auth_headers)
    assert r.status_code == 200 and "total" in r.json()
    r = client.get("/api/suppliers/forecast", headers=auth_headers)
    assert r.status_code == 200 and "forecasts" in r.json()


def test_private_factory_portal_opportunity_loop(client, auth_headers):
    factory = client.post("/api/suppliers", headers=auth_headers, json={
        "name": "测试石狮源头针织厂", "region": "福建泉州石狮",
        "supplier_type": "factory", "capabilities": ["服装", "针织", "小单快反"],
        "ship_days": 5, "rating": 4.5, "stability": 80, "note": "用户私域工厂"
    })
    assert factory.status_code == 200
    sid = factory.json()["id"]
    account = client.post(f"/api/factory-network/suppliers/{sid}/portal-account",
                          headers=auth_headers, json={
        "username": "factory_portal_test", "password": "factory-pass-123",
        "display_name": "测试工厂运营"})
    assert account.status_code == 200
    login = client.post("/api/auth/login", json={"username": "factory_portal_test",
                                                  "password": "factory-pass-123"})
    factory_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert client.get("/api/suppliers", headers=factory_headers).status_code == 403
    # 自建市场机会商品：依赖种子商品池会在清库用例后越界（实测 IndexError，规范 §8 T-2）
    product = client.post("/api/products", headers=auth_headers, json={
        "title": "私域工厂探针针织衫", "category": "服装",
        "attrs": {"sale_price": 39.9, "supplier_price": 19.8, "weight_kg": 0.3}}).json()
    catalog = client.post("/api/factory-network/portal/products", headers=factory_headers,
                          json={"factory_sku": "SS-KNIT-001", "title": product["title"],
                                "category": product["category"],
                                "capabilities": ["服装", "针织", "小单快反"],
                                "unit_price": 19.8, "currency": "CNY", "moq": 20,
                                "lead_days": 5, "monthly_capacity": 10000,
                                "available_qty": 500,
                                "images": ["https://example.invalid/factory-product.jpg"],
                                "status": "active"})
    assert catalog.status_code == 200, catalog.text
    verified = client.put(f"/api/factory-network/suppliers/{sid}/verification",
                          headers=auth_headers,
                          json={"status": "verified", "note": "测试尽调通过"})
    assert verified.status_code == 200
    matched = client.post("/api/factory-network/opportunities/match", headers=auth_headers,
                          json={"product_id": product["id"]})
    assert matched.status_code == 200 and matched.json()["items"]
    best = matched.json()["items"][0]
    # 尚无真实平台销量形成的高可信预测时必须 fail-closed，不能以工厂产能
    # 冒充市场需求并推算营收。
    assert best["can_promote"] is False
    assert any("高可信真实销量预测" in gap for gap in best["gaps"])
    promoted = client.post(f"/api/factory-network/matches/{best['id']}/promote",
                           headers=auth_headers)
    assert promoted.status_code == 409


def test_compliance_and_listing(client, auth_headers):
    # 自建合规干净商品：依赖种子商品池会在清库用例后越界（实测 IndexError，规范 §8 T-2）
    r = client.post("/api/products", headers=auth_headers, json={
        "title": "Generic Desk Organizer", "category": "家居",
        "images": ["https://example.com/organizer.jpg"]})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post("/api/compliance/check", headers=auth_headers,
                    json={"target_type": "product", "ref_id": pid})
    assert r.status_code == 200, r.text
    report = r.json()
    # 原断言 `risk_level in ("low","mid","high")` 三值全覆盖，等于没断言。
    # 改为按 agents/compliance.py `_scan` 的实现契约复算：干净商品（无品牌词/
    # 违禁词、有图）必须零问题、满分、低风险——这是「合规误杀」的守护点。
    assert report["issues"] == [], report
    expected_score = max(0.0, 100 - sum(50 if i["level"] == "high" else 15
                                        for i in report["issues"]))
    assert report["score"] == expected_score, report
    expected_risk = "high" if report["score"] < 60 else ("mid" if report["score"] < 85 else "low")
    assert report["risk_level"] == expected_risk == "low", report
    # 生成 Listing -> 发布
    r = client.post("/api/listings/generate", headers=auth_headers,
                    json={"product_id": pid, "platform": "shopee", "language": "en"})
    assert r.status_code == 200
    lid = r.json()["id"]
    assert r.json()["status"] == "draft"
    r = client.post(f"/api/listings/{lid}/publish", headers=auth_headers)
    assert r.status_code == 200, r.text
    from .action_helpers import approve_and_execute
    published = approve_and_execute(client, auth_headers, r.json())
    assert published["status"] == "published"
    # 品牌侵权商品：检测 high → Listing 检测 high → 发布被拒
    r = client.post("/api/products", headers=auth_headers,
                    json={"title": "iPhone 15 case premium leather 保护壳", "category": "3C配件"})
    bad_pid = r.json()["id"]
    r = client.post("/api/compliance/check", headers=auth_headers,
                    json={"target_type": "product", "ref_id": bad_pid})
    assert r.status_code == 200 and r.json()["risk_level"] == "high", r.json()
    r = client.post("/api/listings/generate", headers=auth_headers,
                    json={"product_id": bad_pid, "platform": "shopee", "language": "en"})
    lid2 = r.json()["id"]
    r = client.post("/api/compliance/check", headers=auth_headers,
                    json={"target_type": "listing", "ref_id": lid2})
    assert r.status_code == 200 and r.json()["risk_level"] == "high"
    r = client.post(f"/api/listings/{lid2}/publish", headers=auth_headers)
    assert r.status_code == 400  # 合规风险高，禁止发布


def test_pricing(client, auth_headers):
    # 自建商品：定价必须用已知成本，靠种子商品会让断言随数据变化而失效，
    # 且清库用例后 items[0] 越界（实测 IndexError，规范 §8 T-2）。
    created = client.post("/api/products", headers=auth_headers, json={
        "title": "Pricing Probe Product", "category": "家居",
        "attrs": {"sale_price": 25.0, "supplier_price": 9.0, "weight_kg": 0.3}})
    assert created.status_code == 200, created.text
    pid = created.json()["id"]
    r = client.post("/api/pricing/calc", headers=auth_headers, json={"product_id": pid})
    assert r.status_code == 200 and "profit" in r.json() and "margin" in r.json()
    # 自建商品的成本已知，可以断言具体数值而不是"字段存在"（弱断言会让
    # 定价公式回归成恒返回 0 也通过）
    calc = r.json()
    assert calc["price"] == 25.0 and calc["purchase_cost"] == 9.0, calc
    assert calc["margin"] == round(calc["profit"] / 25.0, 4), calc
    r = client.post("/api/pricing/suggest", headers=auth_headers, json={"product_id": pid})
    assert r.status_code == 200 and r.json()["suggested_price"] > 0
    # 建议价的策略说明在 reason 结构里（不是顶层字段），且必须给出下限/目标价
    reason = r.json()["reason"]
    assert reason["strategy"], "定价建议必须给出策略说明"
    assert reason["floor"] > 0 and reason["target"] >= reason["floor"], reason
    assert r.json()["suggested_price"] >= reason["floor"] * 0.999, "建议价不得低于价格下限"


def test_ads(client, auth_headers):
    # 自建广告活动：靠 seed 的 campaigns[0] 会在清库用例后越界（实测 IndexError）
    created = client.post("/api/ads/campaigns", headers=auth_headers, json={
        "name": "广告探针活动", "platform": "facebook", "budget": 80})
    assert created.status_code == 200, created.text
    campaign_id = created.json()["id"]
    r = client.get("/api/ads/campaigns", headers=auth_headers)
    assert r.status_code == 200 and "summary" in r.json()
    mine = next((c for c in r.json()["campaigns"] if c["id"] == campaign_id), None)
    assert mine is not None and mine["budget"] == 80, "自建活动必须出现在活动列表中"
    # 写入真实投放数据后验证两条决策分支（比"字段存在"有判别力）：
    # ROI = (revenue - spend) / spend
    from app.db import SessionLocal
    from app.models import AdCampaign

    with SessionLocal() as db:
        c = db.get(AdCampaign, campaign_id)
        c.spend, c.revenue = 100.0, 350.0   # ROI 2.5 > 2 → 加预算 30%
        db.commit()
    r = client.post(f"/api/ads/campaigns/{campaign_id}/optimize", headers=auth_headers)
    assert r.status_code == 200 and "new_budget" in r.json()
    body = r.json()
    assert body["action"] == "加预算" and body["old_budget"] == 80.0, body
    assert body["new_budget"] == round(80.0 * 1.3, 2), body
    assert body["status"] == "PENDING_APPROVAL" and body["approval_required"]
    with SessionLocal() as db:
        assert db.get(AdCampaign, campaign_id).budget == 80.0, "提案不得直接改预算"
    action_id = body["action_id"]
    replay = client.post(f"/api/ads/campaigns/{campaign_id}/optimize",
                         headers=auth_headers).json()
    assert replay["action_id"] == action_id, "重复提案应复用待审批 Action"
    blocked = client.post(f"/api/actions/{action_id}/execute", headers=auth_headers)
    assert blocked.status_code == 409, "未审批不得执行"
    approved = client.post(f"/api/actions/{action_id}/approve", headers=auth_headers,
                           json={"note": "确认 ROI 与预算调整"})
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    executed = client.post(f"/api/actions/{action_id}/execute", headers=auth_headers)
    assert executed.status_code == 200 and executed.json()["status"] == "SUCCESS"
    raised = body["new_budget"]
    with SessionLocal() as db:
        assert db.get(AdCampaign, campaign_id).budget == raised
    replay = client.post(f"/api/actions/{action_id}/execute", headers=auth_headers)
    assert replay.status_code == 200 and replay.json()["status"] == "SUCCESS"

    with SessionLocal() as db:
        c = db.get(AdCampaign, campaign_id)
        c.spend, c.revenue = 100.0, 50.0    # ROI -0.5 < 0.8 → 降预算 40%
        db.commit()
    r = client.post(f"/api/ads/campaigns/{campaign_id}/optimize", headers=auth_headers)
    body = r.json()
    assert body["action"] == "降预算" and body["old_budget"] == raised, body
    assert body["new_budget"] == max(5.0, round(raised * 0.6, 2)), body
    with SessionLocal() as db:
        assert db.get(AdCampaign, campaign_id).budget == raised
    rejected = client.post(f"/api/actions/{body['action_id']}/reject", headers=auth_headers,
                           json={"note": "预算暂不调整"})
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    assert client.post(f"/api/actions/{body['action_id']}/execute",
                       headers=auth_headers).status_code == 409
    pending = client.post(f"/api/ads/campaigns/{campaign_id}/optimize",
                          headers=auth_headers).json()
    assert pending["action_id"] != body["action_id"], "拒绝后必须新建 Action"
    queued = client.get("/api/actions", headers=auth_headers).json()["items"]
    assert any(item["id"] == pending["action_id"] for item in queued)
    client.post(f"/api/actions/{pending['action_id']}/approve", headers=auth_headers,
                json={"note": "同意降预算"})
    with SessionLocal() as db:
        c = db.get(AdCampaign, campaign_id)
        c.revenue = 400.0  # 审批后 ROI 改变，旧建议必须失效
        db.commit()
    stale = client.post(f"/api/actions/{pending['action_id']}/execute",
                        headers=auth_headers).json()
    assert stale["status"] == "FAILED" and "变化" in stale["outcome"]["error"]
    with SessionLocal() as db:
        assert db.get(AdCampaign, campaign_id).budget == raised


def test_orders(client, auth_headers):
    # 无 demo: 前缀的同步请求必须被拒（防误生成演示数据）
    rejected = client.post("/api/orders/sync", headers=auth_headers,
                           json={"platform": "shopee", "count": 1})
    assert rejected.status_code == 409
    r = client.post("/api/orders/sync", headers=auth_headers,
                    json={"platform": "demo:shopee", "count": 3})
    assert r.status_code == 200 and r.json()["synced"] == 3
    client.post("/api/orders/import", headers=auth_headers, json={
        "csv_text": "external_no,platform,amount,status\nSTATE-ORDER-1,shopee,20,paid"})
    oid = next(x["id"] for x in client.get(
        "/api/orders", headers=auth_headers, params={"keyword": "STATE-ORDER-1"}).json()["items"])
    r = client.put(f"/api/orders/{oid}/status", headers=auth_headers, json={"status": "shipped"})
    assert r.status_code == 200 and r.json()["status"] == "shipped"


def test_support_auto_reply(client, auth_headers):
    # 自建会话：靠 seed 的 8 条会话会在清库用例后归零（实测 assert 0 >= 8）
    created_ids = []
    for i in range(8):
        made = client.post("/api/support/conversations", headers=auth_headers, json={
            "platform": "shopee", "buyer_name": f"探针买家{i + 1}",
            "content": "我的订单什么时候发货？"})
        assert made.status_code == 200, made.text
        created_ids.append(made.json()["id"])
    r = client.get("/api/support/conversations", headers=auth_headers)
    assert r.status_code == 200 and r.json()["total"] >= 8
    listed_ids = {c["id"] for c in r.json()["items"]}
    assert set(created_ids) <= listed_ids, "自建会话必须全部出现在会话列表中"
    cid = created_ids[0]
    r = client.post(f"/api/support/conversations/{cid}/auto_reply", headers=auth_headers)
    assert r.status_code == 200 and r.json()["auto"] is True
    assert r.json()["content"]
    assert r.json()["conversation_id"] == cid


def test_workflow_auto_listing(client, auth_headers):
    """全链路：选品→标准化→私域机会收益门禁→货源→合规→复核→发布→广告。

    复核门禁语义：只放行「规则校验 + 合规报告」双通过的 Listing。
    用无图片商品（amazon 规则要求至少 1 张图）确保门禁必被触发，
    验证「blocked → 人工审批 → resume 继续」的完整链路（不依赖种子数据巧合）。
    """
    # 造一个必然触发门禁的商品：无图片（amazon/shopee 规则均要求图片）
    r = client.post("/api/products", headers=auth_headers,
                    json={"title": "门禁验证商品 无图", "category": "家居",
                          "attrs": {"sale_price": 25, "supplier_price": 9,
                                    "onhand": 50, "weight_kg": 0.3},
                          "images": []})
    gate_pid = r.json()["id"]
    r = client.post("/api/workflows/run", headers=auth_headers,
                    json={"template_key": "auto_listing",
                          "context": {"product_ids": [gate_pid],
                                      "_action_requested_by": -999,
                                      "_action_impersonating": True}})
    assert r.status_code == 200, r.text
    run = _wait_run(client, auth_headers, r.json()["id"])
    assert run["context"]["_action_requested_by"] > 0
    assert run["context"]["_action_requested_by"] != -999
    assert run["context"]["_action_impersonating"] is False
    assert run["status"] == "blocked", run.get("error")
    steps = run["steps"]
    assert len(steps) == 9
    assert any(s["agent"] == "factory_opportunity" and
               s["action"] == "scan_private_supply_batch" for s in steps)
    assert any(s["agent"] == "listing_review" and s["action"] == "review_batch" for s in steps)
    # 步骤定位按语义（agent+action）而非硬编码下标：模板步骤顺序可能调整，
    # 下标断言会在顺序变化时给出误导性失败（规范 §8 T-3 语义定位优先）。
    review_step = next(s for s in steps if s["action"] == "review_batch")
    publish_step = next(s for s in steps if s["action"] == "publish_batch")
    ads_step = next(s for s in steps if s["action"] == "draft_batch")
    assert all(s["status"] == "success" for s in steps if s["seq"] < review_step["seq"]), \
        [s["error"] for s in steps]
    assert review_step["status"] == "blocked"
    assert publish_step["status"] == "skipped"
    assert ads_step["status"] == "skipped"
    # 上下文已产生商品与发布结果
    assert gate_pid in run["context"].get("product_ids", []), "指定的门禁商品未进入流程"
    assert "private_ready_product_ids" in run["context"] or not run["context"].get("factory_opportunity_matches")
    # 发布步骤被上游门禁跳过，因此没有产出（空 output 是「未执行」的正常形态）
    assert publish_step["output"] == {}
    # 被拦的 Listing 记录在 review_blocked（复核 Agent 的真实契约字段），
    # 且必须带有可审计的驳回理由——这是「门禁真的拦住了东西」的证据。
    review_blocked = run["context"].get("review_blocked") or []
    assert review_blocked, "复核门禁未产出任何拦截记录"
    assert all(item.get("reasons") for item in review_blocked), review_blocked
    # 已执行的步骤必须带协调元数据（skipped 步骤无 output，属正常）
    executed = [s for s in steps if s["status"] != "skipped"]
    assert all("_coordination" in s["output"] for s in executed), \
        [s["action"] for s in executed if "_coordination" not in s["output"]]
    published_products = set(run["context"].get("published_product_ids", []))
    assert not published_products
    # resume 语义：只重试被拦步骤，已成功步骤不得重跑（attempts 必须保持 1）。
    # 注意本用例的商品是**硬违规**（无图片），人工批准不可覆盖，因此 resume 后
    # 复核仍应为 blocked——这恰好固化「硬违规永不放行」这一红线。
    successful_attempts = [s["attempts"] for s in steps if s["seq"] < review_step["seq"]]
    resumed = client.post(f"/api/workflows/runs/{run['id']}/resume", headers=auth_headers)
    assert resumed.status_code == 200
    detail = client.get(f"/api/workflows/runs/{run['id']}", headers=auth_headers).json()
    resumed_review = next(s for s in detail["steps"] if s["action"] == "review_batch")
    assert [s["attempts"] for s in detail["steps"] if s["seq"] < resumed_review["seq"]] == successful_attempts
    assert resumed_review["attempts"] > review_step["attempts"], "被拦步骤应在 resume 时重试"
    assert resumed_review["status"] == "blocked", "硬违规（图片不足）不可被人工批准覆盖"
    assert detail["status"] == "blocked"


def test_listing_review_manual_approval_audit(client, auth_headers):
    client.post("/api/auth/users", headers=auth_headers, json={
        "username": "compliance_test", "password": "compliance-pass-123",
        "role": "compliance_approver", "display_name": "合规测试员"})
    login = client.post("/api/auth/login", json={
        "username": "compliance_test", "password": "compliance-pass-123"}).json()
    approver_headers = {"Authorization": f"Bearer {login['token']}"}
    product = client.post("/api/products", headers=auth_headers, json={
        "title": "Generic Desk Organizer", "sku": "REVIEW-001", "category": "家居",
        "images": ["https://example.com/organizer.jpg"]}).json()
    listing = client.post("/api/listings/generate", headers=auth_headers, json={
        "product_id": product["id"], "platform": "lazada", "language": "en"}).json()
    listing_id = listing["id"]

    review = client.post(f"/api/listings/{listing_id}/review", headers=auth_headers)
    assert review.status_code == 200
    assert review.json()["decision"] == "manual_required"

    self_approval = client.post(f"/api/listings/{listing_id}/review/approve",
                                headers=auth_headers, json={"note": "本人批准"})
    assert self_approval.status_code == 403
    empty_note = client.post(f"/api/listings/{listing_id}/review/approve",
                             headers=approver_headers, json={"note": ""})
    assert empty_note.status_code == 400
    approval = client.post(f"/api/listings/{listing_id}/review/approve",
                           headers=approver_headers,
                           json={"note": "已核对 Lazada 当前规则与商品资料，允许本次发布"})
    assert approval.status_code == 200
    assert approval.json()["human_override"] is True

    published = client.post(f"/api/listings/{listing_id}/publish", headers=auth_headers)
    assert published.status_code == 200, published.text
    from .action_helpers import approve_and_execute
    assert approve_and_execute(client, auth_headers, published.json())["status"] == "published"
    history = client.get(f"/api/listings/{listing_id}/reviews", headers=auth_headers)
    assert history.status_code == 200
    assert any(item["human_override"] and item["reviewer"].startswith("human:")
               for item in history.json())


def test_bi_dashboard(client, auth_headers):
    r = client.get("/api/bi/dashboard", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    # 原断言 `d["orders"] >= 0` 恒真（订单数不可能为负，实现恒返回 0 也通过）。
    # 改为「导入前后订单数增量」：既断言具体数值，又不依赖库中既有数据（§8 T-8）。
    import datetime as _dt

    stamp = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    before = d["orders"]
    csv_text = ("external_no,platform,qty,amount,status,country,buyer_name,created_at\n"
                f"BI-ORD-{stamp.replace(' ', 'T').replace(':', '')},shopee,1,12.5,paid,US,BI,{stamp}")
    imported = client.post("/api/orders/import", headers=auth_headers,
                           json={"csv_text": csv_text})
    assert imported.status_code == 200 and imported.json()["imported"] == 1, imported.text
    d = client.get("/api/bi/dashboard", headers=auth_headers).json()
    assert d["orders"] == before + 1, f"导入 1 单后订单数应 +1：{before} -> {d['orders']}"
    assert d["metric_scope"] == "real_only"
    assert len(d["sales_trend"]) == 30
    r = client.get("/api/bi/profit", headers=auth_headers, params={"days": 7})
    assert r.status_code == 200 and len(r.json()["series"]) == 7
    r = client.get("/api/bi/report", headers=auth_headers)
    assert r.status_code == 200 and "AI 经营报告" in r.json()["report"]


def test_multi_currency_finance_detail_and_fx_gate(client, auth_headers):
    # 订单时间取相对当前时间：写死日期会随统计窗口滑出而永久失败（规范 §8 T-8 同类
    # 定时炸弹）。同时保留窗口内唯一订单号，避免与其它文件重复。
    import datetime as _dt

    now = _dt.datetime.utcnow()
    order_at = (now - _dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    fx_at = (now - _dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    fee_at = (now - _dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    csv_text = ("external_no,platform,qty,amount,cost,currency,status,country,buyer_name,created_at\n"
                f"FX-CNY-001,shopee,1,700,400,CNY,paid,CN,FX Buyer,{order_at}")
    result = client.post("/api/orders/import", headers=auth_headers,
                         json={"csv_text": csv_text})
    assert result.status_code == 200 and result.json()["imported"] == 1
    order = client.get("/api/orders", headers=auth_headers,
                       params={"keyword": "FX-CNY-001"}).json()["items"][0]

    before = client.get("/api/bi/metrics", headers=auth_headers,
                        params={"days": 365}).json()
    assert any(x["order_id"] == order["id"] for x in before["excluded_orders_missing_fx"]), (order, before)

    fx = client.post("/api/finance/fx", headers=auth_headers, json={
        "base_currency": "CNY", "quote_currency": "USD", "rate": 0.14,
        "effective_at": fx_at, "source": "test"})
    assert fx.status_code == 200
    line = client.post(f"/api/finance/orders/{order['id']}/lines", headers=auth_headers,
                       json={"external_line_no": "1", "sku": "FX-SKU", "title": "FX item",
                             "qty": 1, "unit_price": 700, "product_cost": 400,
                             "currency": "CNY"})
    fee = client.post(f"/api/finance/orders/{order['id']}/fees", headers=auth_headers,
                      json={"fee_type": "platform_commission", "amount": 70,
                            "currency": "CNY", "source": "platform",
                            "occurred_at": fee_at})
    assert line.status_code == 200 and fee.status_code == 200
    detail = client.get(f"/api/finance/orders/{order['id']}/detail", headers=auth_headers).json()
    assert len(detail["lines"]) == 1 and len(detail["fees"]) == 1
    after = client.get("/api/bi/metrics", headers=auth_headers,
                       params={"days": 365}).json()
    assert not any(x["order_id"] == order["id"] for x in after["excluded_orders_missing_fx"])
    assert after["fee_breakdown"]["platform_commission"] >= 9.8

    settlement = {
        "platform": "Shopee", "external_settlement_no": "SET-FX-001",
        "gross_amount": 100, "fee_amount": 10, "refund_amount": 5,
        "net_amount": 84.5, "currency": "USD", "status": "paid"
    }
    created = client.post("/api/finance/platform-settlements", headers=auth_headers,
                          json=settlement)
    assert created.status_code == 200
    settlement["net_amount"] = 85
    repeated = client.post("/api/finance/platform-settlements", headers=auth_headers,
                           json=settlement)
    assert repeated.status_code == 200
    assert repeated.json()["item"]["id"] == created.json()["item"]["id"]
    reconciliation = client.get("/api/finance/settlement-reconciliation",
                                headers=auth_headers).json()
    item = next(x for x in reconciliation["items"]
                if x["external_settlement_no"] == "SET-FX-001")
    assert item["reconciled"] is True and item["variance"] == 0


def test_knowledge(client, auth_headers):
    r = client.post("/api/knowledge/docs", headers=auth_headers,
                    json={"title": "测试文档", "content": "退货流程说明",
                          "source": "test", "tags": []})
    assert r.status_code == 200
    metrics = client.get("/api/bi/metrics", headers=auth_headers).json()
    assert "gmv" in metrics and "net_revenue" in metrics
    assert "contribution_profit" in metrics and "definitions" in metrics
    quality = client.get("/api/bi/data-quality", headers=auth_headers).json()
    # 原断言 `grade in ("low","medium","high")` 同样三值全覆盖恒真。改为按
    # commercial_analytics.quality_report 的判定式复算（freshness 用 `or 999`
    # 与实现保持一致），并守护「演示数据不得标记为可商用」这条红线。
    assert "source_counts" in quality
    failures = sum(c["failed"] for c in quality["checks"])
    fresh = quality["freshness_hours"] or 999
    expected_grade = ("high" if failures == 0 and quality["real_order_count"] >= 100 and fresh <= 24
                      else "medium" if failures == 0 and quality["real_order_count"] >= 20 else "low")
    assert quality["grade"] == expected_grade, quality
    assert quality["commercial_ready"] == (quality["grade"] in ("high", "medium")), quality
    assert {"orders", "order_lines", "products", "ads", "purchases"} <= {
        c["dataset"] for c in quality["checks"]}, quality
    assert all(isinstance(c["failed"], int) and c["failed"] >= 0
               for c in quality["checks"]), quality
    monitoring = client.get("/api/bi/forecast-monitoring", headers=auth_headers).json()
    assert "commercial_gate" in monitoring and "forecast_coverage" in monitoring["summary"]
    r = client.get("/api/knowledge/search", headers=auth_headers, params={"q": "退货"})
    assert r.status_code == 200 and len(r.json()["items"]) >= 1


def test_schedules(client, auth_headers):
    """自主经营调度：创建/启停/立即执行/删除。"""
    r = client.post("/api/schedules", headers=auth_headers,
                    json={"name": "测试趋势扫描", "kind": "trend_scan",
                          "interval_minutes": 30, "enabled": False})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = client.put(f"/api/schedules/{sid}", headers=auth_headers, json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
    r = client.post(f"/api/schedules/{sid}/run", headers=auth_headers)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["schedule"]["run_count"] == 1
    r = client.post("/api/schedules", headers=auth_headers,
                    json={"name": "坏任务", "kind": "workflow", "workflow_key": "nope"})
    assert r.status_code == 404  # 模板不存在
    r = client.delete(f"/api/schedules/{sid}", headers=auth_headers)
    assert r.status_code == 200


def test_scraper_parsing():
    """真实采集解析器：OG 元数据 + 价格兜底 + SSRF 防护（离线纯函数测试）。"""
    from app.services import scraper

    html = """
    <html><head>
      <meta property="og:title" content="厂家直销 宠物梳毛手套 脱毛神器">
      <meta property="og:image" content="https://cbu01.alicdn.com/img/lead.gif">
      <meta property="og:price:amount" content="12.80">
      <meta property="og:description" content="一件代发 支持定制">
    </head><body>
      <img src="https://cbu01.alicdn.com/img/pcb.jpg">
      <img src="data:image/png;base64,xxx">
    </body></html>"""
    item = scraper.parse_product_html(html, "https://detail.1688.com/offer/123.html")
    assert item["title"] == "厂家直销 宠物梳毛手套 脱毛神器"
    assert item["price"] == 12.80
    assert item["images"][0] == "https://cbu01.alicdn.com/img/lead.gif"
    assert item["domain"] == "detail.1688.com"

    # SSRF：内网地址必须被拒绝
    for bad in ("http://127.0.0.1:8000/api", "http://192.168.1.1/x", "http://10.0.0.1/x",
                "ftp://example.com/x"):
        try:
            scraper._assert_public_host(bad)
            raise AssertionError(f"{bad} 未被拦截")
        except scraper.ScrapeError:
            pass


def test_csv_roundtrip(client, auth_headers):
    """订单 CSV 导入（去重/状态映射/SKU关联）+ 商品与订单导出。"""
    # 商品导出
    r = client.get("/api/products/export", headers=auth_headers)
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert r.content.startswith(b"\xef\xbb\xbf")  # utf-8-sig
    # 订单导入：2 条新 + 1 条重复
    sku = client.get("/api/products", headers=auth_headers,
                     params={"page_size": 1}).json()["items"][0]["sku"]
    csv_text = (
        "external_no,platform,qty,amount,status,sku,country,buyer_name,created_at\n"
        f"TEST-A,shopee,1,23.99,paid,{sku},US,Emma,2026-09-01 10:00:00\n"
        f"TEST-B,amazon,2,45.00,已发货,{sku},DE,Liam,2026/09/02 12:30\n"
        f"TEST-A,shopee,1,23.99,paid,{sku},US,Emma,2026-09-01 10:00:00\n"
        "BAD-C,shopee,1,abc,paid,US,X,2026-09-03\n"  # 金额非法 -> 记入 errors
    )
    r = client.post("/api/orders/import", headers=auth_headers, json={"csv_text": csv_text})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 2 and body["skipped"] == 1
    assert len(body["errors"]) == 1 and "BAD-C" in body["errors"][0]
    r = client.get("/api/orders", headers=auth_headers, params={"keyword": "TEST-B"})
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["status"] == "shipped"  # 中文状态已映射
    assert r.json()["items"][0]["product_id"] is not None  # SKU 关联成功
    # 订单导出
    r = client.get("/api/orders/export", headers=auth_headers)
    assert r.status_code == 200 and b"TEST-A" in r.content


def test_1688_api_sign_and_fallback(client, auth_headers):
    """1688 官方 API：签名协议正确性 + 无 Key 时采集管线自动降级。"""
    from app.services import open_1688, scraper

    # 签名纯函数：HMAC-SHA1(path+sorted_params, secret) 大写十六进制
    sig = open_1688.sign("/openapi/param2/1/com.alibaba.product/x/KEY",
                         {"b": "2", "a": "1"}, "SECRET")
    assert len(sig) == 40 and sig == sig.upper()
    import hashlib as _hl
    import hmac as _hmac
    expect = _hmac.new(b"SECRET", b"/openapi/param2/1/com.alibaba.product/x/KEYa1b2",
                       _hl.sha1).hexdigest().upper()
    assert sig == expect

    # offer 链接识别
    assert scraper._offer_id_1688("https://detail.1688.com/offer/749831465070.html") == "749831465070"
    assert scraper._offer_id_1688("https://example.com/x") is None

    # 无 Key 时 settings 返回 has_key=False，collect_url 不因 API 配置缺失而 500
    r = client.get("/api/ai/settings", headers=auth_headers)
    assert r.status_code == 200 and r.json()["open_1688"]["has_key"] is False
    # 1688 密钥是平台级配置：租户 admin 写入必须 403（防跨租户污染）
    r = client.put("/api/ai/settings", headers=auth_headers,
                   json={"open_1688": {"app_key": "test_key", "app_secret": "test_secret"}})
    assert r.status_code == 403 and "平台" in r.json()["detail"]
    # 平台服务商可写（脱敏回读：app_secret 空串回传）
    sa = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'root', 'password': 'root-test-123'}).json()['token']}"}
    r = client.put("/api/ai/settings", headers=sa,
                   json={"open_1688": {"app_key": "test_key", "app_secret": "test_secret"}})
    assert r.status_code == 200, r.text
    body = r.json()["open_1688"]
    assert body["app_key"] == "test_key" and body["has_key"] is True
    assert body["app_secret"] == ""  # 密钥不回显


def test_purchase_order_flow(client, auth_headers):
    """采购闭环：录入报价 → 生成采购单 → 提交 → 收货入库（库存增加）。"""
    # 商品（缺货）+ 供应商 + 报价单
    r = client.post("/api/products", headers=auth_headers,
                    json={"title": "测试缺货商品 采购流程", "category": "家居",
                          "attrs": {"supplier_price": 10, "sale_price": 20,
                                    "onhand": 0, "weight_kg": 0.3}})
    pid = r.json()["id"]
    sku = r.json()["sku"]
    ext_no = f"DROP-{pid}"
    imported = client.post("/api/orders/import", headers=auth_headers, json={
        "csv_text": ("external_no,platform,amount,qty,status,sku\n"
                     f"{ext_no},shopee,40,2,paid,{sku}")})
    assert imported.status_code == 200 and imported.json()["imported"] == 1
    sales_order = next(x for x in client.get("/api/orders", headers=auth_headers).json()["items"]
                       if x["external_no"] == ext_no)
    assert sales_order["id"]
    sid = client.get("/api/suppliers", headers=auth_headers).json()["items"][0]["id"]
    r = client.post("/api/suppliers/offers", headers=auth_headers,
                    json={"supplier_id": sid, "product_id": pid, "price": 9.9,
                          "moq": 1, "ship_days": 5})
    assert r.status_code == 200, r.text
    # 生成采购单（自动选最优货源）
    r = client.post("/api/purchases", headers=auth_headers,
                    json={"product_id": pid, "qty": 5, "note": "测试采购"})
    assert r.status_code == 200, r.text
    po = r.json()
    assert po["status"] == "draft" and po["qty"] == 5 and po["unit_price"] == 9.9
    assert po["supplier_name"] and po["total"] == 49.5
    po_id = po["id"]
    # 草稿可改数量，总额联动
    r = client.put(f"/api/purchases/{po_id}", headers=auth_headers, json={"qty": 8})
    assert r.status_code == 200 and r.json()["total"] == 79.2
    # 提交供应商
    r = client.put(f"/api/purchases/{po_id}", headers=auth_headers, json={"status": "submitted"})
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    # from_forecast 端点形状（新商品无销量 -> 视库存规则跳过或生成，均合法）
    r = client.post("/api/purchases/from_forecast", headers=auth_headers,
                    json={"product_ids": [pid], "qty_multiplier": 1.0})
    assert r.status_code == 200 and "created" in r.json() and "skipped" in r.json()
    # 收货入库
    r = client.post(f"/api/purchases/{po_id}/receive", headers=auth_headers, json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["in_stock_added"] == 8
    # 库存已反映到商品
    r = client.get(f"/api/products/{pid}", headers=auth_headers)
    assert r.json()["attrs"]["onhand"] == body["onhand_now"] == 8
    # 已收货不可取消、不可再收货
    r = client.delete(f"/api/purchases/{po_id}", headers=auth_headers)
    assert r.status_code == 400
    r = client.post(f"/api/purchases/{po_id}/receive", headers=auth_headers, json={})
    assert r.status_code == 400


def test_order_ship_flow(client, auth_headers):
    """发货流程：paid 订单 → 生成物流单号 → shipped；重复发货 400。"""
    r = client.post("/api/orders/sync", headers=auth_headers, json={"platform": "demo:shopee", "count": 5})
    assert r.status_code == 200
    client.post("/api/orders/import", headers=auth_headers, json={
        "csv_text": "external_no,platform,amount,status\nSHIP-ORDER-1,shopee,20,paid"})
    oid = next(x["id"] for x in client.get(
        "/api/orders", headers=auth_headers, params={"keyword": "SHIP-ORDER-1"}).json()["items"])
    r = client.post(f"/api/orders/{oid}/ship", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "shipped" and len(body["tracking_no"]) >= 10
    r = client.post(f"/api/orders/{oid}/ship", headers=auth_headers)
    assert r.status_code == 400  # 重复发货被拒


def test_listing_manual_edit(client, auth_headers):
    """Listing 人工编辑：修改标题/卖点/关键词并持久化。"""
    r = client.post("/api/products", headers=auth_headers,
                    json={"title": "Manual Edit Probe", "category": "家居"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post("/api/listings/generate", headers=auth_headers,
                    json={"product_id": pid, "platform": "shopee", "language": "en"})
    lid = r.json()["id"]
    r = client.put(f"/api/listings/{lid}", headers=auth_headers,
                   json={"title": "人工优化标题 Premium Edition",
                         "description": "人工编辑后的描述", "bullets": ["卖点一", "卖点二"],
                         "keywords": ["kw1", "kw2"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "人工优化标题 Premium Edition"
    assert body["bullets"] == ["卖点一", "卖点二"] and body["keywords"] == ["kw1", "kw2"]
    # 标题不能为空
    r = client.put(f"/api/listings/{lid}", headers=auth_headers,
                   json={"title": "  ", "description": "x", "bullets": [], "keywords": []})
    assert r.status_code == 400


def test_shop_oauth_flow(client, auth_headers, monkeypatch):
    """店铺授权：授权URL生成 / 授权码换token（协议解析）/ 未授权拦截 / 演示店铺拉单 / 清空演示数据。"""

    # 1. 添加店铺
    r = client.post("/api/shops", headers=auth_headers,
                    json={"platform": "1688", "shop_name": "测试授权店",
                          "app_key": "ak_123", "app_secret": "sk_456"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert r.json()["status"] == "pending"
    assert r.json().get("app_secret") is None  # 密钥不回显

    # 2. 授权 URL（真实 1688 OAuth 协议格式）
    r = client.get(f"/api/shops/{sid}/authorize_url", headers=auth_headers)
    assert r.status_code == 200
    url = r.json()["authorize_url"]
    assert url.startswith("https://auth.1688.com/oauth/authorize?")
    assert "client_id=ak_123" in url and "site=1688" in url

    # 3. 授权码换 token（monkeypatch 平台端点，验证协议解析与存储）
    from app.services import platform_adapters

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"access_token": "AT_001", "refresh_token": "RT_001", "expires_in": 86400}

    monkeypatch.setattr(platform_adapters.httpx, "post", lambda *a, **kw: FakeResp())
    r = client.post(f"/api/shops/{sid}/exchange_code", headers=auth_headers,
                    json={"code": "AUTH_CODE_XYZ"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["status"] == "authorized"

    # 4. 授权后拉单：1688 是货源平台（role=source），必须被明确拒绝而非静默假成功。
    # 原断言 `in (200, 400)` 连「明错误」和「静默成功」都区分不了（实测恒为 400）。
    r = client.post(f"/api/shops/{sid}/sync_orders", headers=auth_headers)
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "1688" in detail and "货源店铺" in detail, detail

    # 4b. 真实发布通道：sales 店铺 + Shopee 平台（规则校验/类目映射前置）
    r = client.post("/api/shops", headers=auth_headers,
                    json={"platform": "shopee", "shop_name": "Shopee 销售店",
                          "app_key": "pk1", "app_secret": "sk1"})
    shopee_id = r.json()["id"]
    # 未授权直接发布 -> 400
    r = client.get("/api/listings", headers=auth_headers, params={"status": "draft"})
    lid = r.json()["items"][0]["id"]
    r = client.post(f"/api/listings/{lid}/publish", headers=auth_headers,
                    json={"shop_id": shopee_id})
    assert r.status_code == 400 and "未授权" in r.json()["detail"]
    # 伪造授权态后发布 -> 卡在类目映射（Shopee 必填，平台不一致性的体现）
    client.put(f"/api/shops/{shopee_id}", headers=auth_headers,
               json={"shop_id": "123"})

    from app.db import SessionLocal as _SL
    from app.models import Shop as _Shop
    _db = _SL()
    _s = _db.get(_Shop, shopee_id)
    _s.status = "authorized"
    _s.token_expire_at = datetime.strptime("2099-01-01", "%Y-%m-%d")
    _db.commit()
    _db.close()
    r = client.post(f"/api/listings/{lid}/publish", headers=auth_headers,
                    json={"shop_id": shopee_id})
    d = r.json()["detail"]
    assert r.status_code == 400 and ("类目映射" in d or "图片" in d), r.json()
    # 配置类目映射后 -> 命中规则校验（本地占位图被 Shopee 图片规则之外，先过映射）
    r = client.post("/api/shops/category-mappings", headers=auth_headers,
                    json={"platform": "shopee", "system_category": "家居",
                          "platform_category_id": "100642"})
    assert r.status_code == 200
    # 平台不匹配即使是演示店也禁止，避免把 Shopee 文案误发到 TikTok。
    r = client.post("/api/shops", headers=auth_headers,
                    json={"platform": "tiktok", "shop_name": "演示销售店", "is_demo": True})
    demo_shop = r.json()["id"]
    r = client.post(f"/api/listings/{lid}/publish", headers=auth_headers,
                    json={"shop_id": demo_shop})
    assert r.status_code == 400 and "不能发布" in r.json()["detail"]
    # 创建内容和图片完整的 Shopee 商品，演示发布也必须先通过复核 Agent。
    r = client.post("/api/products", headers=auth_headers,
                    json={"title": "Safe Home Organizer", "category": "家居",
                          "sku": "SAFE-DEMO-001",
                          "images": ["https://example.com/product.jpg"],
                          "attrs": {"supplier_price": 10}})
    safe_pid = r.json()["id"]
    r = client.post("/api/listings/generate", headers=auth_headers,
                    json={"product_id": safe_pid, "platform": "shopee", "language": "en"})
    safe_lid = r.json()["id"]
    r = client.post("/api/shops", headers=auth_headers,
                    json={"platform": "shopee", "shop_name": "Shopee 演示销售店", "is_demo": True})
    safe_demo_shop = r.json()["id"]
    r = client.post(f"/api/listings/{safe_lid}/publish", headers=auth_headers,
                    json={"shop_id": safe_demo_shop})
    assert r.status_code == 200, r.text
    from .action_helpers import approve_and_execute
    published = approve_and_execute(client, auth_headers, r.json())
    assert published["source"] == "demo" and published["external_id"].startswith("demo-")
    client.delete(f"/api/shops/{shopee_id}", headers=auth_headers)
    client.delete(f"/api/shops/{demo_shop}", headers=auth_headers)
    client.delete(f"/api/shops/{safe_demo_shop}", headers=auth_headers)

    # 5. 未授权店铺同步 -> 400 引导授权
    r = client.post("/api/shops", headers=auth_headers, json={"platform": "shopee"})
    sid2 = r.json()["id"]
    r = client.post(f"/api/shops/{sid2}/sync_orders", headers=auth_headers)
    assert r.status_code == 400 and "授权" in r.json()["detail"]

    # 6. 演示店铺（is_demo）可模拟拉单，来源标记 demo
    r = client.post("/api/shops", headers=auth_headers,
                    json={"platform": "shopee", "shop_name": "演示店", "is_demo": True})
    sid3 = r.json()["id"]
    r = client.post(f"/api/shops/{sid3}/sync_orders", headers=auth_headers)
    assert r.status_code == 200 and r.json()["source"] == "demo" and r.json()["synced"] == 5

    # 7. 清空演示数据（管理员）：订单/商品/会话/广告删除，店铺与用户保留
    r = client.post("/api/shops/purge_demo_data", headers=auth_headers)
    assert r.status_code == 200
    deleted = r.json()["deleted"]
    assert deleted["orders"] > 0 and deleted["products"] > 0
    r = client.get("/api/products", headers=auth_headers)
    assert r.json()["total"] == 0
    r = client.get("/api/shops", headers=auth_headers)
    assert r.json()["total"] >= 3  # 店铺配置保留
    # 清理测试店铺
    for i in (sid, sid2, sid3):
        client.delete(f"/api/shops/{i}", headers=auth_headers)


def test_shopee_adapter_sign_and_publish_gate(client, auth_headers):
    """按官方文档核实的 Shopee v2 协议：签名格式 / 发布前置校验链。"""
    import hashlib
    import hmac as _hmac
    from types import SimpleNamespace

    from app.services.platform_adapters import ShopeeAdapter, platform_meta

    shop = SimpleNamespace(app_key="pk", app_secret="sk", shop_id="9",
                           access_token="AT", platform="shopee")
    ShopeeAdapter(None, shop)
    # Shop API 签名：HMAC-SHA256(partner_id+path+ts+access_token+shop_id) hex
    ts = 1700000000
    expect = _hmac.new(b"sk", f"pk/api/v2/x{ts}AT9".encode(), hashlib.sha256).hexdigest()
    a2 = ShopeeAdapter(None, shop)
    base = f"pk/api/v2/x{ts}AT9"
    assert a2._sign(base) == expect
    # 平台能力清单：发布/拉单差异可见
    meta = {m["platform"]: m for m in platform_meta()}
    assert meta["shopee"]["can_publish"] is True
    assert meta["1688"]["can_publish"] is False and meta["1688"]["role"] == "source"
    assert meta["amazon"]["can_publish"] is False

    # 业务侧：shopee 店铺发布 -> 未授权 400（自建商品/Listing，消除顺序依赖）
    r = client.post("/api/products", headers=auth_headers,
                    json={"title": "签名测试商品", "category": "家居",
                          "attrs": {"sale_price": 20, "onhand": 5, "weight_kg": 0.3,
                                    "supplier_price": 10}})
    pid2 = r.json()["id"]
    r = client.post("/api/listings/generate", headers=auth_headers,
                    json={"product_id": pid2, "platform": "shopee", "language": "en"})
    lid = r.json()["id"]
    r = client.post("/api/shops", headers=auth_headers,
                    json={"platform": "shopee", "shop_name": "S店", "app_key": "pk1",
                          "app_secret": "sk1", "shop_id": "9"})
    sid = r.json()["id"]
    r = client.post(f"/api/listings/{lid}/publish", headers=auth_headers,
                    json={"shop_id": sid})
    assert r.status_code == 400 and "未授权" in r.json()["detail"]
    client.delete(f"/api/shops/{sid}", headers=auth_headers)


def test_platform_rules_and_admin(client, auth_headers):
    """平台规则包 / 类目映射 / 平台服务商租户管理与代客访问审计。"""
    # 规则包概览：各平台差异可见（Amazon 禁促销语、Shopee 类目必填…）
    r = client.get("/api/shops/platform_rules", headers=auth_headers)
    assert r.status_code == 200
    rules = {x["platform"]: x for x in r.json()["items"]}
    assert rules["shopee"]["summary"]["title_max"] == 255
    assert "free shipping" in "".join(rules["amazon"]["summary"]["notes"]) or \
        rules["amazon"]["origin"]
    # 类目映射 CRUD
    r = client.post("/api/shops/category-mappings", headers=auth_headers,
                    json={"platform": "shopee", "system_category": "家居",
                          "platform_category_id": "100642"})
    mid = r.json()["id"]
    r = client.get("/api/shops/category-mappings", headers=auth_headers,
                   params={"platform": "shopee"})
    assert r.json()["total"] >= 1
    # ---- 平台服务商 ----
    r = client.post("/api/auth/login",
                    json={"username": "root", "password": "root-test-123"})
    assert r.status_code == 200, r.text
    sa = {"Authorization": f"Bearer {r.json()['token']}"}
    # 普通用户访问平台管理 -> 403
    r = client.get("/api/admin/tenants", headers=auth_headers)
    assert r.status_code == 403
    # 创建客户租户（一次性返回初始密码）
    r = client.post("/api/admin/tenants", headers=sa,
                    json={"name": "某某贸易有限公司", "plan": "pro",
                          "license_days": 30, "admin_username": "clientadmin"})
    assert r.status_code == 200, r.text
    body = r.json()
    tid = body["id"]
    assert body["admin_username"] == "clientadmin" and body["admin_password"]
    # 客户租户登录可用
    r = client.post("/api/auth/login",
                    json={"username": "clientadmin", "password": body["admin_password"]})
    assert r.status_code == 200
    client_token = r.json()["token"]
    r = client.get("/api/products", headers={"Authorization": f"Bearer {client_token}"})
    assert r.status_code == 200  # 新租户空数据可正常访问
    # 代客访问：签发租户上下文 token + 审计留痕
    entered_before = sum(x["tenant_id"] == tid for x in
                         client.get("/api/admin/access_logs", headers=sa).json()["items"])
    r = client.post(f"/api/admin/tenants/{tid}/enter", headers=sa)
    assert r.status_code == 200
    imp_token = r.json()["token"]
    r = client.get("/api/products", headers={"Authorization": f"Bearer {imp_token}"})
    assert r.status_code == 200
    r = client.get("/api/admin/access_logs", headers=sa)
    assert r.status_code == 200, r.text
    logs = r.json()
    # 原断言 `total >= 1 or len(items) >= 1` 两侧同值，是冗余的恒真式。
    # 改为：total 与 items 同源 + 本次 enter 恰好新增一条该租户审计。
    assert logs["total"] == len(logs["items"]) >= 1, logs
    assert sum(x["tenant_id"] == tid for x in logs["items"]) == entered_before + 1, logs
    latest = logs["items"][0]
    assert latest["tenant_id"] == tid and latest["action"] == "enter", latest
    assert latest["operator_name"], latest
    # 服务授权到期门禁：先进入租户拿代客 token（租户有效时），再把租户改为已过期
    r = client.post(f"/api/admin/tenants/{tid}/enter", headers=sa)
    assert r.status_code == 200
    imp_token = r.json()["token"]
    r = client.put(f"/api/admin/tenants/{tid}", headers=sa, json={"license_days": -31})
    assert r.status_code == 200
    r = client.get("/api/products", headers={"Authorization": f"Bearer {client_token}"})
    assert r.status_code == 403 and "到期" in r.json()["detail"]
    # 过期租户：代客 token 业务请求 403；再次 enter 直接 400 拒绝
    r = client.get("/api/products", headers={"Authorization": f"Bearer {imp_token}"})
    assert r.status_code == 403 and "到期" in r.json()["detail"]
    r = client.post(f"/api/admin/tenants/{tid}/enter", headers=sa)
    assert r.status_code == 400 and "到期" in r.json()["detail"]
    # 续期恢复
    client.put(f"/api/admin/tenants/{tid}", headers=sa, json={"license_days": 365})
    r = client.get("/api/products", headers={"Authorization": f"Bearer {client_token}"})
    assert r.status_code == 200
    # 停用 -> 403
    client.put(f"/api/admin/tenants/{tid}", headers=sa, json={"status": "suspended"})
    r = client.get("/api/products", headers={"Authorization": f"Bearer {client_token}"})
    assert r.status_code == 403
    # superadmin 跨租户 AI 调用日志端点
    r = client.get("/api/admin/ai_logs", headers=sa)
    assert r.status_code == 200 and "items" in r.json()
    # superadmin 本尊是平台身份，没有业务 Workspace：
    # 直接调用租户业务接口必须 403，避免以空 tenant 写入产生孤儿数据。
    r = client.get("/api/products", headers=sa)
    assert r.status_code == 403
    assert "进入租户" in r.json()["detail"]
    # 恢复启用 + 令授权过期：代客进入被「授权到期」门禁拒绝
    client.put(f"/api/admin/tenants/{tid}", headers=sa, json={"status": "active"})
    client.put(f"/api/admin/tenants/{tid}", headers=sa, json={"license_days": -400})
    r = client.post(f"/api/admin/tenants/{tid}/enter", headers=sa)
    assert r.status_code == 400 and "到期" in r.json()["detail"]  # 该租户已过期
    # 续期后代客进入即可正常访问该租户业务数据（带审计）
    client.put(f"/api/admin/tenants/{tid}", headers=sa, json={"license_days": 365})
    r = client.post(f"/api/admin/tenants/{tid}/enter", headers=sa)
    assert r.status_code == 200
    imp = {"Authorization": f"Bearer {r.json()['token']}"}
    r = client.get("/api/products", headers=imp)
    assert r.status_code == 200
    client.delete(f"/api/shops/category-mappings/{mid}", headers=auth_headers)


def test_refund_and_settlement_flow(client, auth_headers):
    """售后逆向闭环 + 供应商账期结算闭环。"""
    # ---- 售后：发货订单 -> 退货退款 -> 退货入库 -> 完成退款 -> 订单 refunded ----
    product = client.post("/api/products", headers=auth_headers, json={
        "title": "Refund Settlement Probe", "category": "家居",
        "attrs": {"onhand": 10, "supplier_price": 9.9, "sale_price": 25}})
    assert product.status_code == 200, product.text
    external_no = f"REFUND-SETTLEMENT-{product.json()['id']}"
    imported = client.post("/api/orders/import", headers=auth_headers, json={
        "csv_text": "external_no,platform,amount,qty,status,sku\n"
                    f"{external_no},shopee,50,2,paid,{product.json()['sku']}"})
    assert imported.status_code == 200 and imported.json()["imported"] == 1, imported.text
    order = client.get("/api/orders", headers=auth_headers,
                       params={"keyword": external_no}).json()["items"][0]
    oid = order["id"]
    for status in ("shipped", "delivered"):
        transition = client.put(f"/api/orders/{oid}/status", headers=auth_headers, json={"status": status})
        assert transition.status_code == 200, transition.text
    pid = order["product_id"]
    before = client.get(f"/api/products/{pid}", headers=auth_headers).json()["attrs"].get("onhand", 0)
    # 发起整单退货退款（qty=订单件数，验证订单状态联动）
    r = client.post("/api/refunds", headers=auth_headers,
                    json={"order_id": oid, "type": "return_refund", "qty": order["qty"],
                          "reason": "质量问题", "restock": True})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert r.json()["status"] == "pending" and r.json()["amount"] > 0
    # 重复发起 -> 拦截
    r = client.post("/api/refunds", headers=auth_headers,
                    json={"order_id": oid, "type": "return_refund", "qty": 1})
    assert r.status_code == 400 and "已有进行中" in r.json()["detail"]
    # 未审核直接退款 -> 400
    r = client.post(f"/api/refunds/{rid}/refund", headers=auth_headers)
    assert r.status_code == 400
    # 审核同意 -> 退货入库（库存回补）-> 完成退款
    r = client.put(f"/api/refunds/{rid}/status", headers=auth_headers,
                   json={"status": "approved", "note": "审核通过"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = client.post(f"/api/refunds/{rid}/return_receive", headers=auth_headers)
    assert r.status_code == 200 and r.json()["restocked"] == order["qty"]
    after = client.get(f"/api/products/{pid}", headers=auth_headers).json()["attrs"]["onhand"]
    assert after == before + order["qty"]
    r = client.post(f"/api/refunds/{rid}/refund", headers=auth_headers)
    assert r.status_code == 200 and r.json()["refund"]["status"] == "refunded"
    assert r.json()["order_status"] == "refunded"  # 订单联动
    # 金额超限拦截
    r = client.post("/api/refunds", headers=auth_headers,
                    json={"order_id": oid, "type": "refund_only", "qty": 1, "amount": 999999})
    assert r.status_code == 400

    # ---- 结算：已收货采购单 -> 生成对账 -> 确认 -> 付款 -> 不再重复结算 ----
    # 真实流程要求先有货源报价才能生成采购单；demo 拉单的商品未必已录入报价。
    # 独立已验证供应商：不能把其他用例待结算/待确认的 PO 计入本探针。
    from app.db import SessionLocal
    from app.models import Supplier, User
    with SessionLocal() as db:
        user = db.query(User).filter_by(username="admin").one()
        supplier = Supplier(tenant_id=user.tenant_id, name=f"Settlement Probe {pid}",
                            verification_status="verified")
        db.add(supplier)
        db.commit()
        sid = supplier.id
    r = client.post("/api/suppliers/offers", headers=auth_headers,
                    json={"supplier_id": sid, "product_id": pid, "price": 9.9,
                          "moq": 1, "ship_days": 5})
    assert r.status_code == 200, r.text
    r = client.post("/api/purchases", headers=auth_headers,
                    json={"product_id": pid, "supplier_id": sid, "qty": 10, "note": "结算测试"})
    assert r.status_code == 200, r.text
    po_id, supplier_id, po_total = r.json()["id"], r.json()["supplier_id"], r.json()["total"]
    client.put(f"/api/purchases/{po_id}", headers=auth_headers, json={"status": "submitted"})
    r = client.post(f"/api/purchases/{po_id}/receive", headers=auth_headers, json={})
    assert r.status_code == 200
    # 生成结算单
    r = client.post("/api/settlements/generate", headers=auth_headers,
                    json={"supplier_id": supplier_id})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["po_count"] == 1 and st["total_amount"] == po_total
    st_id = st["id"]
    # 未确认直接付款 -> 409（非法状态流转）
    r = client.put(f"/api/settlements/{st_id}", headers=auth_headers, json={"status": "paid"})
    assert r.status_code == 409
    client.put(f"/api/settlements/{st_id}", headers=auth_headers, json={"status": "confirmed"})
    r = client.put(f"/api/settlements/{st_id}", headers=auth_headers,
                   json={"status": "paid", "note": "银行转账"})
    assert r.status_code == 200 and r.json()["status"] == "paid"
    # 已结算 PO 不再出现在待结算汇总
    r = client.get("/api/settlements/summary", headers=auth_headers)
    row = next(x for x in r.json()["items"] if x["supplier_id"] == supplier_id)
    assert row["unsettled_amount"] == 0 and row["unsettled_count"] == 0


def test_dropship_flow(client, auth_headers):
    """一件代发：店铺角色防混校验 + 演示通道下单 → DS 采购单。"""
    # 建 1688 商品（带 offer 链接）+ 报价 + 授权演示货源店
    r = client.post("/api/products", headers=auth_headers,
                    json={"title": "代发测试商品", "category": "家居",
                          "attrs": {"supplier_price": 8, "sale_price": 20, "onhand": 0},
                          "source_platform": "1688",
                          "source_url": "https://detail.1688.com/offer/700111.html"})
    pid = r.json()["id"]
    sku = r.json()["sku"]
    ext_no = f"DROP-{pid}"
    imported = client.post("/api/orders/import", headers=auth_headers, json={
        "csv_text": ("external_no,platform,amount,qty,status,sku\n"
                     f"{ext_no},shopee,40,2,paid,{sku}")})
    assert imported.status_code == 200 and imported.json()["imported"] == 1
    order_id = next(x["id"] for x in client.get(
        "/api/orders", headers=auth_headers, params={"keyword": ext_no}).json()["items"]
                    if x["external_no"] == ext_no)
    sid = client.get("/api/suppliers", headers=auth_headers).json()["items"][0]["id"]
    client.post("/api/suppliers/offers", headers=auth_headers,
                json={"supplier_id": sid, "product_id": pid, "price": 8})
    # 演示货源店（1688, source, is_demo）
    r = client.post("/api/shops", headers=auth_headers,
                    json={"platform": "1688", "shop_name": "代发货源店", "role": "source", "is_demo": True})
    src_shop = r.json()["id"]
    # 销售店（sales）——用于防混校验
    r = client.post("/api/shops", headers=auth_headers,
                    json={"platform": "shopee", "shop_name": "销售店", "role": "sales", "is_demo": True})
    sales_shop = r.json()["id"]

    # 防混：用销售店铺代发 -> 400
    r = client.post("/api/purchases/dropship", headers=auth_headers,
                    json={"shop_id": sales_shop, "product_id": pid, "order_id": order_id, "qty": 1})
    assert r.status_code == 400 and "不可混用" in r.json()["detail"], r.json()

    # 正常：货源店铺代发（演示通道）
    r = client.post("/api/purchases/dropship", headers=auth_headers,
                    json={"shop_id": src_shop, "product_id": pid, "order_id": order_id, "qty": 2,
                          "consignee": "张三", "phone": "13800000000", "address": "深圳市南山区"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["mode"] == "demo"
    assert body["platform_trade_no"].startswith("DEMO") and body["offer_id"] == 700111
    assert body["purchase"]["po_no"].startswith("DS") and body["purchase"]["status"] == "submitted"
    assert "一件代发(demo)" in body["purchase"]["note"]

    # 未授权真实店铺（非 demo）-> 400 引导授权
    r = client.post("/api/shops", headers=auth_headers,
                    json={"platform": "1688", "shop_name": "真实货源店", "role": "source"})
    real_shop = r.json()["id"]
    r = client.post("/api/purchases/dropship", headers=auth_headers,
                    json={"shop_id": real_shop, "product_id": pid, "order_id": order_id, "qty": 1})
    assert r.status_code == 400 and "未授权" in r.json()["detail"]
    client.delete(f"/api/shops/{src_shop}", headers=auth_headers)
    client.delete(f"/api/shops/{sales_shop}", headers=auth_headers)
    client.delete(f"/api/shops/{real_shop}", headers=auth_headers)


def test_ai_chat(client, auth_headers):
    r = client.post("/api/ai/chat", headers=auth_headers, json={"message": "帮我选品"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] in ("pick", "chat", "help")
    assert body["reply"]
    r = client.get("/api/ai/logs", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)
