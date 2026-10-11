"""种子数据：开箱即用的演示环境（确定性 random.seed(42)）。"""
import random
from datetime import datetime, timedelta

from sqlalchemy import func

from .ai.llm import DEFAULT_LLM
from .auth import hash_password
from .db import SessionLocal
from .models import (
    AdCampaign,
    AiLog,
    ComplianceReport,
    Conversation,
    KnowledgeDoc,
    Listing,
    MarketTrend,
    Message,
    Order,
    PricingRecord,
    ProductScore,
    PurchaseOrder,
    RefundOrder,
    Schedule,
    Setting,
    Settlement,
    Shop,
    Supplier,
    SupplierOffer,
    Tenant,
    User,
    WorkflowRun,
    WorkflowTemplate,
)
from .services import mock_market

_KNOWLEDGE_DOCS = [
    ("平台违禁词与宣称规范", "各平台禁止使用绝对化用语与医疗宣称：如「最好的」「第一名」「No.1」「顶级」「cure（治愈）」"
     "「FDA approved」「杀菌」「防癌」「100% safe」等均属高危违禁表述。文案应使用客观功能描述，"
     "例如以「adopted by many families」替代「第一品牌」。违规将导致 Listing 下架、店铺扣分甚至封店。"
     "建议上架前逐条自查标题、五点描述、A+ 页面与关键词。", "平台规则", ["合规", "文案"]),
    ("商标黑名单清单", "高频侵权品牌词（Text 中出现即高危）：Apple、iPhone、iPad、Samsung、Xiaomi、Nike、Adidas、"
     "Puma、Disney、Marvel、LEGO、Barbie、Hello Kitty、Pokemon、Rolex、Louis Vuitton、Gucci、Chanel、"
     "Cartier、Dyson、Anker。标题、描述、关键词中一律不得出现上述品牌名，除非持有明确授权。"
     "图片中亦不得出现品牌 LOGO 与包装。", "合规知识库", ["合规", "商标"]),
    ("图片版权合规指引", "商品主图必须为自有拍摄或已授权素材；禁止直接搬运供应商带水印图片、同行图片与搜索引擎图片。"
     "文件名含 watermark/logo 字样的素材需人工复核。建议使用白底主图+场景图+尺寸图组合，"
     "并保留原始拍摄底稿以应对侵权申诉。", "合规知识库", ["合规", "图片"]),
    ("各平台佣金费率表", "常用跨境平台佣金参考（可按实际合同在系统设置中调整）：Shopee 6%，Amazon 15%，"
     "Shopify 2%（仅支付通道），eBay 12%，Temu 5%，TikTok Shop 8%。利润测算公式："
     "真实利润 = 售价 - (采购 + 物流 + 售价×佣金率×汇率 + 单件广告费)/汇率。", "运营手册", ["定价", "费率"]),
    ("选品评分标准说明", "机会分 = 0.35×需求 + 0.20×(100-竞争) + 0.30×利润 + 0.15×(100-风险)。"
     "需求分参考关键词搜索量与30天增长率；竞争分参考类目商品密度；利润分参考预估毛利率；"
     "风险分参考标题品牌词与违禁词命中。机会分 ≥ 80 强烈推荐，60-80 可测试，< 60 放弃。", "运营手册", ["选品"]),
    ("动态定价公式说明", "成本加成定价：目标价 = 成本×(1+目标利润率)/(汇率×(1-佣金率))，"
     "价格下限 = 成本×(1+最低利润率)/(汇率×(1-佣金率))。系统默认目标利润率 35%、最低利润率 15%。"
     "需求旺盛（需求分>70）可在 ±8% 内上浮，竞争激烈（竞争分>70）适当下调；"
     "调价后利润率不得跌破下限。", "运营手册", ["定价"]),
    ("客服回复规范", "客服响应要求：首次响应 < 2 小时；退换货诉求先安抚再走流程；"
     "物流类问题引导查看轨迹并给出 7-15 个工作日预期；严禁承诺退款时效之外的条件。"
     "常见意图：订单查询（order status）、物流跟踪（tracking）、退换货（refund/return）、商品咨询（product QA）。", "运营手册", ["客服"]),
    ("广告投放优化指南", "广告预算调整策略：ROI > 2 时预算上调 30%（上限 500 USD/天）；ROI < 0.8 时下调 40%；"
     "0.8-2 之间维持观察。选词优先使用长尾词与场景词，避免大词烧钱。"
     "CTR 健康区间 0.5%-3%，CVR 健康区间 1%-5%；连续 7 天无转化的广告组应暂停并更换素材。", "运营手册", ["广告"]),
]


def seed_if_empty() -> bool:
    """库为空时灌入演示数据，返回是否执行了种子。"""
    db = SessionLocal()
    try:
        if db.query(func.count(Tenant.id)).scalar():
            return False
        _seed(db)
        return True
    finally:
        db.close()


# 平台级默认配置（无租户维度，key 全局唯一）。
# 抽成常量是因为它同时被两处使用：_seed() 首次灌入、_ensure_default_settings() 补齐缺失项。
DEFAULT_SETTINGS: dict[str, dict] = {
    "llm": dict(DEFAULT_LLM),
    "platform_fees": {"shopee": 0.06, "amazon": 0.15, "shopify": 0.02,
                      "ebay": 0.12, "temu": 0.05, "tiktok": 0.08},
    "fx": {"USD": 7.12, "EUR": 7.8},
    "rules": {"min_margin": 0.15, "target_margin": 0.35,
              "logistics_base": 18.0, "logistics_per_kg": 8.0,
              "ads_default": 1.5},
}


def _ensure_default_settings(db) -> int:
    """补齐缺失的平台级默认配置，返回新增条数。

    为什么需要幂等：``settings.key`` 是**全局唯一**且无租户维度，但 ``_seed()``
    可能在「演示数据被清理、租户仍在」的情况下被再次调用（例如测试夹具重建种子）。
    此时无条件 ``db.add(Setting(...))`` 必然撞 ``UNIQUE constraint failed:
    settings.key``，整批用例在 setup 阶段报错。改为「缺什么补什么」后，重复调用
    是安全的，且不会覆盖用户已改过的配置值。
    """
    existing = {key for (key,) in db.query(Setting.key).all()}
    added = 0
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.add(Setting(key=key, value=dict(value)))
            added += 1
    return added


def ensure_listing_review_workflow(db) -> None:
    """为存量自动铺货模板补齐私域供给扫描和复核步骤。"""
    templates = db.query(WorkflowTemplate).filter(WorkflowTemplate.key == "auto_listing",
                                                WorkflowTemplate.flow_kind == "LEGACY_AUTOMATION").all()
    changed = False
    for template in templates:
        steps = list(template.steps or [])
        if not any(s.get("agent") == "factory_opportunity" for s in steps):
            supplier_index = next((i for i, s in enumerate(steps)
                                   if s.get("agent") == "supplier" and s.get("action") == "match_best_batch"),
                                  len(steps))
            steps.insert(supplier_index, {"agent": "factory_opportunity",
                         "action": "scan_private_supply_batch",
                         "params": {"min_match_score": 50, "min_margin": 0.15}})
            changed = True
        if not any(s.get("agent") == "listing_review" and s.get("action") == "review_batch"
                   for s in steps):
            publish_index = next((i for i, s in enumerate(steps)
                                  if s.get("agent") == "listing" and s.get("action") == "publish_batch"),
                                 len(steps))
            steps.insert(publish_index, {"agent": "listing_review", "action": "review_batch", "params": {}})
            changed = True
        template.steps = steps
        if "私域工厂" not in (template.description or ""):
            template.description = (template.description or "").replace("标准化 → 货源匹配", "标准化 → 私域工厂机会与收益门禁 → 货源匹配")
            changed = True
        if "上架复核" not in (template.description or ""):
            template.description = (template.description or "").replace("Listing生成 → 发布", "Listing生成 → 上架复核 → 发布")
    if changed:
        db.commit()


def _ensure_superadmin(db) -> None:
    """平台服务商账号：仅当设置了 ERP_SUPERADMIN_PASSWORD 环境变量时创建（不进演示种子）。"""
    import os

    pwd = os.getenv("ERP_SUPERADMIN_PASSWORD", "")
    if not pwd:
        return
    if not db.query(User).filter(User.role == "superadmin").first():
        # 平台服务商不属于任何租户：tenant_id 必须为 NULL。
        # 历史上这里写 0，而 tenants 表没有 id=0，导致：
        #   1) 开启 foreign_keys 后直接违反外键约束；
        #   2) 未开启时产生 tenant_id=0 的孤儿业务数据（曾清理 37 行）。
        db.add(User(tenant_id=None, username=os.getenv("ERP_SUPERADMIN_USERNAME", "root"),
                    password_hash=hash_password(pwd),
                    display_name="平台服务商", role="superadmin"))
        db.commit()


def _ensure_admin_password(db) -> None:
    """把演示租户的 admin 口令同步为 ERP_ADMIN_PASSWORD（若已配置且不同于默认值）。

    为什么需要：``auth.admin_bootstrap_password()`` 定义了却从未被调用，导致
    ``ERP_ADMIN_PASSWORD`` 只在生产校验时被检查、从未真正生效——种子永远写死
    ``admin123``。生产环境下这意味着：门禁要求配置强口令，但实际登录口令仍是
    默认值，形成"看起来合规、实际可被默认口令登录"的假安全。

    规则：
      - 仅在**非生产环境**且 ``ERP_ADMIN_PASSWORD`` 未配置/为 ``admin123`` 时跳过，
        保持演示默认体验；
      - 生产环境或已配置非默认值时，每次启动都对齐 admin 口令（改配置后重启即生效）；
      - 只作用于演示租户的 ``admin`` 账号，不触碰其他账号与租户。

    注意：生产环境下即使配置为 ``admin123`` 也不跳过——否则强口令改回默认值时
    无法生效。生产启动门禁（``config.validate_production_settings``）已在更早阶段
    拒绝 ``admin123``，此处再兜一层。
    """
    import os

    from . import config
    from .auth import hash_password

    pwd = os.getenv("ERP_ADMIN_PASSWORD", "")
    is_production = config.settings.environment == "production"
    if not pwd or (pwd == "admin123" and not is_production):
        return
    admin = db.query(User).filter(User.username == "admin",
                                  User.role == "admin").first()
    if admin is None:
        return
    from .auth import verify_password

    if verify_password(pwd, admin.password_hash):
        return  # 已对齐，避免每次启动无谓地重算散列并使旧 token 失效
    admin.password_hash = hash_password(pwd)
    admin.token_version = int(admin.token_version or 0) + 1
    db.commit()


def _seed(db) -> None:
    random.seed(42)
    tenant = Tenant(name="演示商家")
    db.add(tenant)
    db.flush()

    db.add_all([
        User(tenant_id=tenant.id, username="admin", password_hash=hash_password("admin123"),
             display_name="管理员", role="admin"),
        User(tenant_id=tenant.id, username="ops", password_hash=hash_password("ops123"),
             display_name="运营专员", role="operator"),
        User(tenant_id=tenant.id, username="viewer", password_hash=hash_password("viewer123"),
             display_name="观察者", role="viewer"),
    ])
    _ensure_default_settings(db)

    # 商品池：24 个模拟采集商品
    items = mock_market.gen_products(None, 24)
    products = mock_market.insert_products(db, tenant.id, items)

    # 供应商与报价：每个商品 2-3 条报价
    supplier_names = ["义乌市华晨日用品厂", "深圳蓝海电子科技", "广州优品家居有限公司",
                      "宁波瑞丽塑业", "汕头市宏发玩具厂", "东莞锦程五金制品",
                      "杭州云丝纺织", "青岛海诺工贸"]
    suppliers = [Supplier(tenant_id=tenant.id, name=n,
                          region=random.choice(["浙江", "广东", "江苏", "山东"]),
                          rating=round(random.uniform(3.8, 5.0), 1),
                          ship_days=random.choice([3, 5, 7, 10]),
                          settlement_days=random.choice([15, 30, 45]),
                          stability=round(random.uniform(65, 98), 1))
                 for n in supplier_names]
    db.add_all(suppliers)
    db.flush()
    for p in products:
        for s in random.sample(suppliers, random.randint(2, 3)):
            base_price = float((p.attrs or {}).get("supplier_price", 10))
            db.add(SupplierOffer(tenant_id=tenant.id, supplier_id=s.id, product_id=p.id,
                                 price=round(base_price * random.uniform(0.88, 1.18), 2),
                                 moq=random.choice([1, 2, 10, 50]),
                                 ship_days=s.ship_days + random.choice([0, 1, 2]),
                                 in_stock=random.random() > 0.1))

    # 趋势
    trend_rows = [
        ("led strip lights", "google", 32000, 85.2, 62), ("pet grooming gloves", "amazon", 18000, 120.5, 48),
        ("car phone holder", "amazon", 45000, 25.0, 88), ("yoga mat thick", "google", 26000, 45.8, 71),
        ("reusable makeup pads", "shopee", 12000, 160.0, 35), ("baby feeding bibs", "amazon", 21000, 38.4, 55),
        ("kitchen drawer organizer", "google", 19000, 66.7, 66), ("camping lantern rechargeable", "amazon", 15000, 92.3, 58),
        ("hair claw clips", "tiktok", 52000, 210.0, 77), ("smart water bottle", "google", 28000, 55.6, 80),
        ("dog cooling mat", "shopee", 9800, 74.9, 42), ("wireless earbuds case", "shopee", 17000, 30.2, 84),
    ]
    for kw, plat, vol, growth, comp in trend_rows:
        db.add(MarketTrend(tenant_id=tenant.id, keyword=kw, platform=plat,
                           search_volume=vol, growth_30d=growth, competition=comp,
                           note="增长率显著" if growth > 60 else "平稳"))

    # 选品评分（本地公式，与 DiscoveryAgent 同权重）
    for p in products:
        demand = random.uniform(45, 95)
        competition = random.uniform(25, 85)
        margin = 1 - (float(p.attrs["supplier_price"]) / 7.12) / float(p.attrs["sale_price"])
        profit = max(5, min(95, margin * 220))
        risk = random.choice([8, 10, 12, 38, 55])
        total = 0.35 * demand + 0.2 * (100 - competition) + 0.3 * profit + 0.15 * (100 - risk)
        db.add(ProductScore(tenant_id=tenant.id, product_id=p.id,
                            demand=round(demand, 1), competition=round(competition, 1),
                            profit=round(profit, 1), risk=risk, total=round(total, 1),
                            reasons=["基于模拟趋势与利润率的种子评分"], model="rule"))

    # Listing 草稿 6 条
    for i, p in enumerate(products[:6]):
        en = (p.attrs or {}).get("title_en") or p.title
        db.add(Listing(tenant_id=tenant.id, product_id=p.id,
                       platform=["shopee", "amazon", "shopify"][i % 3], language="en",
                       title=f"{en} {p.attrs.get('material', 'Premium').title()} for {p.attrs.get('scene', 'home')} | Hot Sale 2026",
                       description=f"{en}, made of durable {p.attrs.get('material', 'premium')} material. "
                                   "Factory direct with strict quality control. Ideal for daily use and gifting.",
                       bullets=["Factory direct quality", "Durable material", "Compact design",
                                "Great for gifting", "24/7 support"],
                       keywords=[en, f"{en} 2026", f"best {p.category}", f"{en} wholesale"],
                       status="draft"))

    # 合规报告 4 条（覆盖 low/mid/high）
    reports = [
        (products[0].id, "low", 100.0, []),
        (products[1].id, "mid", 85.0, [{"type": "image", "level": "mid",
                                        "detail": "图片疑似带水印，建议更换素材", "evidence": "img_2_detail.jpg"}]),
        (products[2].id, "mid", 70.0, [{"type": "claim", "level": "mid",
                                        "detail": "描述含绝对化用语「最好」，违反广告法", "evidence": "最好"}]),
        (products[3].id, "high", 40.0, [{"type": "brand", "level": "high",
                                         "detail": "标题命中品牌词「iPhone」，存在商标侵权风险",
                                         "evidence": "iphone"}]),
    ]
    for pid, level, score, issues in reports:
        db.add(ComplianceReport(tenant_id=tenant.id, target_type="product", product_id=pid,
                                risk_level=level, score=score, issues=issues,
                                suggestions=["更换素材/删除违禁词后复检"] if issues else []))

    # 定价记录 12 条
    for p in products[:12]:
        purchase = float(p.attrs["supplier_price"])
        logistics = 18 + 8 * float(p.attrs["weight_kg"])
        fee = 0.06
        fx = 7.12
        cost_cny = purchase + logistics + 1.5
        suggested = round(cost_cny * 1.35 / (fx * (1 - fee)), 2)
        price = float(p.attrs["sale_price"])
        profit = round(price - (cost_cny + fee * price * fx) / fx, 2)
        db.add(PricingRecord(tenant_id=tenant.id, product_id=p.id,
                             purchase_cost=purchase, logistics_cost=logistics,
                             platform_fee_rate=fee, ads_cost=1.5,
                             price=price, suggested_price=suggested,
                             profit=profit, margin=round(profit / price, 4),
                             currency="USD",
                             reason={"strategy": "成本加成+市场修正", "cost_cny": round(cost_cny, 2),
                                     "adjustments": ["种子演示数据"]}))

    # 广告活动 6 条
    campaigns = []
    for i in range(6):
        spend = round(random.uniform(80, 600), 2)
        roi_factor = random.uniform(0.4, 3.6)
        revenue = round(spend * roi_factor, 2)
        impressions = random.randint(8000, 60000)
        clicks = int(impressions * random.uniform(0.008, 0.03))
        campaigns.append(AdCampaign(
            tenant_id=tenant.id, name=f"{products[i].title[:16]}-广告",
            platform=random.choice(["facebook", "google", "tiktok"]),
            product_id=products[i].id,
            keywords=[products[i].title[:10], f"{products[i].category} hot", "2026 new"],
            budget=round(random.uniform(30, 120), 2), spend=spend, revenue=revenue,
            impressions=impressions, clicks=clicks,
            orders=int(clicks * random.uniform(0.01, 0.06)),
            status=["running", "running", "running", "draft", "draft", "paused"][i]))
    db.add_all(campaigns)

    # 订单 500 条（近60天）
    for _ in range(500):
        mock_market.gen_order(db, tenant.id, None)
    db.commit()

    # 客服会话 8 组
    buyer_questions = [
        ("我的订单什么时候发货？", "order_status"), ("Where is my order? It has been 10 days.", "order_status"),
        ("包裹到哪个物流了？能给我单号吗？", "logistics"), ("Tracking number please?", "logistics"),
        ("收到的东西有破损，我要退款！", "refund"), ("The item is broken, I want a refund.", "refund"),
        ("这个是什么材质的？尺寸多大？", "product_qa"), ("你好，可以便宜一点吗？", "other"),
    ]
    for i, (q, _intent) in enumerate(buyer_questions):
        order = (db.query(Order).filter(Order.tenant_id == tenant.id)
                 .order_by(Order.created_at.desc()).offset(i).first())
        c = Conversation(tenant_id=tenant.id, platform=random.choice(["shopee", "amazon", "ebay"]),
                         buyer_name=f"Buyer{i + 1:02d}",
                         order_id=order.id if i % 2 == 0 and order else None,
                         product_id=products[i % len(products)].id)
        db.add(c)
        db.flush()
        base = datetime.utcnow() - timedelta(hours=random.randint(2, 72))
        m1 = Message(tenant_id=tenant.id, conversation_id=c.id, role="buyer",
                     content=q, intent="", auto=False)
        m1.created_at = base
        db.add(m1)
        c.last_message_at = base
    db.commit()

    # 知识库 8 篇
    for title, content, source, tags in _KNOWLEDGE_DOCS:
        db.add(KnowledgeDoc(tenant_id=tenant.id, title=title, content=content,
                            source=source, tags=tags))

    # 工作流模板 3 个
    db.add_all([
        WorkflowTemplate(tenant_id=tenant.id, key="auto_listing", name="自动铺货全流程",
                         description="选品 → 标准化 → 私域工厂机会与收益门禁 → 货源匹配 → 合规检测 → Listing生成 → 上架复核 → 发布 → 广告草稿",
                         steps=[
                             {"agent": "discovery", "action": "pick_candidates", "params": {"limit": 3}},
                             {"agent": "product", "action": "standardize_batch", "params": {}},
                             {"agent": "factory_opportunity", "action": "scan_private_supply_batch",
                              "params": {"min_match_score": 50, "min_margin": 0.15}},
                             {"agent": "supplier", "action": "match_best_batch", "params": {}},
                             {"agent": "compliance", "action": "check_batch", "params": {}},
                             {"agent": "listing", "action": "generate_batch",
                              "params": {"platform": "shopee", "language": "en"}},
                             {"agent": "listing_review", "action": "review_batch", "params": {}},
                             {"agent": "listing", "action": "publish_batch", "params": {}},
                             {"agent": "ads", "action": "draft_batch", "params": {"platform": "facebook"}},
                         ]),
        WorkflowTemplate(tenant_id=tenant.id, key="reprice", name="全店动态定价",
                         description="对全店在售商品重新测算真实利润并给出建议价",
                         steps=[{"agent": "pricing", "action": "reprice_batch", "params": {}}]),
        WorkflowTemplate(tenant_id=tenant.id, key="restock", name="补货预警分析",
                         description="全店销量预测与缺货预警",
                         steps=[{"agent": "supplier", "action": "forecast_batch", "params": {}}]),
    ])

    # 演示店铺：一个货源（1688 代发）+ 一个销售（Shopee 模拟），角色分明不混用
    db.add(Shop(tenant_id=tenant.id, platform="1688", shop_name="演示 1688 货源店铺",
                role="source", status="pending",
                auth_message="未授权：请填写开放平台 App Key 后发起授权（一件代发需已授权）",
                is_demo=True))
    db.add(Shop(tenant_id=tenant.id, platform="shopee", shop_name="演示 Shopee 销售店铺",
                role="sales", status="pending",
                auth_message="未授权：销售上架/拉单前请完成授权",
                is_demo=True))

    # 采购单样例（覆盖 draft/submitted/received 三种状态）
    for i, (status, qty) in enumerate([("received", 100), ("submitted", 50), ("draft", 30)]):
        p, s = products[i], suppliers[i % len(suppliers)]
        price = float(p.attrs["supplier_price"])
        db.add(PurchaseOrder(tenant_id=tenant.id,
                             po_no=f"PO2026090{15 + i}0000{i}",
                             supplier_id=s.id, product_id=p.id, qty=qty,
                             unit_price=price, total=round(price * qty, 2),
                             status=status, note="种子演示采购单",
                             expected_date=(datetime.utcnow() + timedelta(days=s.ship_days)).strftime("%Y-%m-%d")))

    # 售后退款单样例（覆盖待审核/已退货两种状态）
    _ro = (db.query(Order).filter(Order.tenant_id == tenant.id, Order.status == "delivered")
           .order_by(Order.created_at.desc()).first())
    if _ro:
        db.add(RefundOrder(tenant_id=tenant.id, refund_no="RF20260918000001",
                           order_id=_ro.id, type="return_refund", qty=1,
                           amount=round(_ro.amount / _ro.qty, 2),
                           reason="种子演示：商品与描述不符，协商退货退款",
                           status="pending"))
    # 已结算采购单 + 结算单样例
    _po = (db.query(PurchaseOrder).filter(PurchaseOrder.tenant_id == tenant.id,
                                          PurchaseOrder.status == "received").first())
    if _po:
        s = Settlement(tenant_id=tenant.id, settle_no="ST20260917000001",
                       supplier_id=_po.supplier_id,
                       period_start=_po.created_at, period_end=_po.created_at,
                       po_count=1, total_amount=_po.total, status="paid",
                       paid_at=datetime.utcnow())
        db.add(s)
        db.flush()
        _po.settlement_id = s.id

    # 自主经营调度任务（演示：默认停用，避免演示环境自动写入）
    db.add_all([
        Schedule(tenant_id=tenant.id, name="每日市场趋势扫描", kind="trend_scan",
                 interval_minutes=1440, enabled=False, run_count=3,
                 last_status="success"),
        Schedule(tenant_id=tenant.id, name="每周全店动态定价", kind="workflow",
                 workflow_key="reprice", interval_minutes=10080, enabled=False,
                 run_count=1, last_status="success"),
        # M3 主动巡检：方案要求「默认每 6 小时自动巡检一次」。此处沿用演示环境
        # 的保守策略（enabled=False，避免演示环境自动写库），租户在
        # 「AI 工作流」页一键启用即可；不预置这条任务时，界面上根本看不到
        # 巡检调度入口（前端下拉此前也没有 alert_scan 选项）。
        Schedule(tenant_id=tenant.id, name="每 6 小时经营风险巡检", kind="alert_scan",
                 interval_minutes=360, enabled=False, run_count=2,
                 last_status="success"),
    ])

    # 一次历史工作流运行（展示用）
    run = WorkflowRun(tenant_id=tenant.id, template_key="reprice", name="全店动态定价",
                      status="success", context={"seeded": True},
                      created_at=datetime.utcnow() - timedelta(days=1),
                      finished_at=datetime.utcnow() - timedelta(days=1))
    db.add(run)

    db.add_all([AiLog(tenant_id=tenant.id, agent="orchestrator", action="seed", mode="rule",
                      model="system", prompt="seed", response="演示数据初始化完成", ok=True)])
    db.commit()
