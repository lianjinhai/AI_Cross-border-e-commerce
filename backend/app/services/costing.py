"""成本与利润计算（Agent 共享的领域计算，不依赖任何 Agent）。

为什么必须独立成 service（而不是留在 ``agents/pricing.py``）：
    ``FactoryOpportunityAgent`` 需要真实利润率做门禁，原实现直接
    ``from .pricing import PricingAgent`` 再 ``PricingAgent(...).calc_profit()``
    ——这是 **Agent 之间 P2P 调用**，违反 Agent OS 架构冻结文档 §3 与规范 L-3
    （所有 Agent 协作只能由 Orchestrator 编排）。P2P 会让权限、审计、数据范围
    三道闸全部失效：被调 Agent 用自己的会话/租户上下文执行，调用方无从控制，
    Trace 也串不起来。

    修法遵循分层 ``agents/ -> tools/ -> services/``：把「成本要素 + 利润」这类
    纯领域计算下沉到 ``services/``，两个 Agent 各自调用同一份实现。
    这样既消除 P2P，又保证口径**唯一**——两处各写一遍迟早漂移（一处改了
    汇率取法、另一处没改，门禁用的利润率与定价页展示的就不是同一个数）。

调用方必须自己持有 Session 并传入 ``tenant_id``：本模块不建会话、不猜租户，
避免出现「无上下文计算」。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import ExchangeRate, Product, SupplierOffer
from . import duty as duty_service
from . import inventory_service, platform_fees, settings_service
from . import logistics as logistics_service

DEFAULT_RULES = {
    "min_margin": 0.15, "target_margin": 0.35,
    "logistics_base": 18.0, "logistics_per_kg": 8.0, "ads_default": 1.5,
    # 新增跨境成本项：默认 0（未配置=不计入），避免在未配置时改变既有利润口径；
    # 租户在 tenant_settings.rules 中开启后生效（见 docs/CONTRACT.md 与 D58）。
    "payment_fee_rate": 0.0,     # 支付/收款通道费（连连/PingPong/PayPal 等）
    "refund_rate": 0.0,          # 退货/退款成本率（服饰类常达 15%~30%）
    "tax_rebate_rate": 0.0,      # 出口退税税率（有票采购常用 13%）
    "vat_in_rate": 0.13,         # 采购取得增值税发票的进项税率（用于退税基数）
    "clearance_fee_cny": duty_service.DEFAULT_CLEARANCE_FEE_CNY,  # 清关代理费（元/票）
    "landed_cost_include_vat": True,  # 到岸成本是否含进口 VAT（IOSS 代收场景可关闭）
    # 目的国准入是否阻断上架（P1-4）：默认 False，避免证据未录入时误伤上架流程。
    "destination_compliance_enforce": False,
}
DEFAULT_FEES = {"shopee": 0.06, "amazon": 0.15, "shopify": 0.02,
                "ebay": 0.12, "temu": 0.05, "tiktok": 0.08}
DEFAULT_FX = {"USD": 7.12}


def setting_for(db: Session, tenant_id: int | None, key: str, default: dict) -> dict:
    """按租户读取配置（租户覆盖 → 平台默认 → 代码默认）。"""
    value = dict(default)
    value.update(settings_service.get_setting(db, tenant_id, key))
    return value


def latest_fx(db: Session, tenant_id: int, base: str, quote: str) -> float | None:
    """取最近一条生效汇率；同币种直接返回 1.0。"""
    if base == quote:
        return 1.0
    row = (db.query(ExchangeRate).filter(
        ExchangeRate.tenant_id == tenant_id,
        ExchangeRate.base_currency == base,
        ExchangeRate.quote_currency == quote,
        ExchangeRate.effective_at <= datetime.utcnow())
        .order_by(ExchangeRate.effective_at.desc()).first())
    return float(row.rate) if row else None


def to_cny(db: Session, tenant_id: int, amount: float, currency: str) -> float:
    """折算成人民币。缺汇率必须抛错（fail closed），禁止用猜测汇率算利润。"""
    currency = (currency or "CNY").upper()
    direct = latest_fx(db, tenant_id, currency, "CNY")
    if direct is not None:
        return amount * direct
    # 财务主口径通常维护兑 USD 汇率，允许通过 USD 安全交叉换算。
    base_usd = latest_fx(db, tenant_id, currency, "USD")
    cny_usd = latest_fx(db, tenant_id, "CNY", "USD")
    if base_usd is not None and cny_usd:
        return amount * base_usd / cny_usd
    raise ValueError(f"缺少 {currency}→CNY 的有效汇率，禁止计算利润")


def offer_state(db: Session, tenant_id: int, product: Product) -> tuple[str | None, list[str]]:
    """选定报价的业务状态与对外承诺限制（B3 契约：失效规则唯一实现）。

    三档语义（前端禁止自行推断，只用本函数结果）：
      - ``MISSING``（删除/跨租户/非本商品）：选择失效，成本回退最低在库价；
      - ``EXPIRED`` / ``OUT_OF_STOCK`` / ``UNVERIFIED``：**保留用户偏好且可试算**，
        但阻断据此对外报价、采购下单与上线承诺（需先恢复有效事实）；
      - ``OK``：无限制。未选定时返回 ``(None, [])``。

    返回 ``(state, limits)``；``limits`` 是可直接展示的中文阻断原因。
    """
    sel_id = product.selected_offer_id
    if sel_id is None:
        return None, []
    sel = db.get(SupplierOffer, sel_id)
    if (sel is None or sel.tenant_id != tenant_id or sel.product_id != product.id):
        return "MISSING", ["选定报价已不存在或无权访问：成本已回退最低在库价，请重新比选"]
    limits: list[str] = []
    state = "OK"
    if sel.valid_until is not None and sel.valid_until < datetime.utcnow():
        state = "EXPIRED"
        limits.append("报价已过期：可保留偏好与试算，不得据此对外报价或采购")
    elif not sel.in_stock:
        state = "OUT_OF_STOCK"
        limits.append("报价缺货：可保留偏好与试算，不得据此对外报价或采购")
    elif not _offer_verified(sel):
        state = "UNVERIFIED"
        limits.append("报价来源待核实：可保留偏好与试算，不得据此对外报价或采购")
    return state, limits


def _offer_verified(sel: SupplierOffer) -> bool:
    """报价是否已核实。口径与 models.SupplierOffer 注释一致：

    ``manual`` 来源视为人工已核实（可追责）；其余来源须 ``verification_status``
    为 ``manual`` / ``verified`` 才视为已核实，``unverified`` / ``scraped`` 均待核实。
    """
    verification = (sel.verification_status or "").lower()
    source_kind = (sel.source_kind or "").lower()
    if source_kind == "manual":
        return True
    return verification in {"manual", "verified"}


def best_purchase(db: Session, tenant_id: int, product: Product,
                  honor_selection: bool = True) -> tuple[float, int | None]:
    """取采购价（已折算人民币）与所用报价 id。

    选中报价优先（``honor_selection=True``，成本引擎默认）：若
    ``product.selected_offer_id`` 已设置且该报价行存在、匹配本租户与商品，
    则直接采用（**即使缺货也尊重用户显式选择**）——缺货状态由下游渲染层
    处理，不在这里降级为「最低在库价」。否则退回「在库最低价」逻辑。
    ``honor_selection=False`` 仅用于 overview 的 ``min_offer_price_cny``：
    那个字段的语义是「真正的最低在库价」，供与选定价对比，绝不能被选定覆盖。
    返回签名不变：(price_cny, offer_id)，offer_id 为 None 表示用了 attrs 占位价。
    """
    sel_id = product.selected_offer_id
    if honor_selection and sel_id is not None:
        sel = db.get(SupplierOffer, sel_id)
        if (sel is not None and sel.tenant_id == tenant_id
                and sel.product_id == product.id):
            return to_cny(db, tenant_id, float(sel.price), sel.currency), sel.id
    offers = (db.query(SupplierOffer)
              .filter(SupplierOffer.tenant_id == tenant_id,
                      SupplierOffer.product_id == product.id,
                      SupplierOffer.in_stock.is_(True))
              .all())
    converted = [(to_cny(db, tenant_id, float(o.price), o.currency), o.id) for o in offers]
    if converted:
        return min(converted, key=lambda x: x[0])
    return float((product.attrs or {}).get("supplier_price") or 10.0), None


def cost_completeness(db: Session, tenant_id: int, product: Product) -> tuple[list[str], bool]:
    """回报真实成本所需的必填输入是否齐备。

    返回 ``(missing, complete)``。``missing`` 列出当前确实缺失或被退化的成本输入
    （字段名用于 ``overview.supply.cost_missing``）：
      - ``purchase``：无在库报价且 ``product.attrs.supplier_price`` 缺失——
        costing 会退化为 10.0 占位价，并非真实采购价；
      - ``fx``：存在非 CNY 报价币种却缺少该币种→CNY 的折算汇率（to_cny 会 fail-closed 拒绝）；
      - ``hs_code``：商品无 HS 编码，关税引擎按兜底税率估算（非真实申报值）。
    """
    missing: list[str] = []
    attrs = product.attrs or {}
    offers = (db.query(SupplierOffer)
              .filter(SupplierOffer.tenant_id == tenant_id,
                      SupplierOffer.product_id == product.id,
                      SupplierOffer.in_stock.is_(True))
              .all())
    if not offers and not attrs.get("supplier_price"):
        missing.append("purchase")
    non_cny = {o.currency for o in offers if (o.currency or "CNY").upper() != "CNY"}
    for cur in non_cny:
        if latest_fx(db, tenant_id, cur, "CNY") is None:
            missing.append("fx")
            break
    if not (product.hs_code or attrs.get("hs_code")):
        missing.append("hs_code")
    return missing, (len(missing) == 0)


def cost_elements(db: Session, tenant_id: int, product: Product, platform: str = "",
                  destination_country: str = "", channel_type: str = "",
                  site: str = "", qty: int = 1,
                  declared_value_cny: float | None = None,
                  warehouse_id: int | None = None) -> dict:
    """拆出利润计算所需的全部成本要素（采购/物流/佣金/广告/关税/汇率）。

    跨境扩展（D58）：给出 ``destination_country`` 时按目的国 + HS 计算关税、进口
    VAT 与清关费；未给出时到岸成本三项为 0 并显式标记 ``landed_cost_applied=False``。
    物流在有匹配路由时按费率表计费，否则回退旧线性公式（口径不变）。
    海外仓持有成本（D59）：给出 ``warehouse_id`` 时按库龄 × 日费率 + 入库费叠加；
    未给出时持有成本 0，口径不变。
    """
    rules = setting_for(db, tenant_id, "rules", DEFAULT_RULES)
    fx_map = setting_for(db, tenant_id, "fx", DEFAULT_FX)
    attrs = product.attrs or {}
    platform = platform or attrs.get("platform") or "shopee"
    purchase_cny, offer_id = best_purchase(db, tenant_id, product)
    fx = float(fx_map.get("USD", 7.12))
    ship = logistics_service.quote(db, tenant_id, attrs, destination_country=destination_country,
                                   channel_type=channel_type, qty=qty, rules=rules)
    fee = platform_fees.resolve(db, tenant_id, platform, product.category or "", site)
    hs_code = (product.hs_code or attrs.get("hs_code") or "").strip()
    landed = duty_service.compute_landed_cost(
        db, tenant_id, country=destination_country, hs_code=hs_code,
        declared_value_cny=declared_value_cny if declared_value_cny is not None else purchase_cny,
        qty=qty, with_import_vat=bool(rules.get("landed_cost_include_vat", True)))
    # 海外仓持有成本（D59）：未配 warehouse_id 时 holding_cost=0，不改既有口径
    holding = inventory_service.holding_cost(
        db, tenant_id, warehouse_id=warehouse_id, product_id=product.id) \
        if warehouse_id else {"holding_cost_cny": 0.0, "long_term_surcharge_cny": 0.0,
                               "days_in_stock": 0, "qty": 0,
                               "holding_cost_applied": False, "reason": "no_warehouse"}
    inbound_fee = 0.0
    wh = None
    if holding.get("holding_cost_applied") and warehouse_id is not None:
        from ..models import Warehouse
        wh = db.get(Warehouse, warehouse_id)
        inbound_fee = float(wh.inbound_fee_per_unit or 0) * qty
    return {
        "purchase_cny": purchase_cny, "offer_id": offer_id,
        "logistics_cny": ship["total_cny"], "logistics_detail": ship,
        "fee_rate": fee["total_rate"], "fee_detail": fee,
        "ads_cny": float(rules["ads_default"]),
        "fx": fx,
        "hs_code": hs_code, "destination_country": landed["country"],
        "duty_cny": landed["duty_cny"], "import_vat_cny": landed["import_vat_cny"],
        "clearance_cny": landed["clearance_cny"], "landed_cost_cny": landed["total_cny"],
        "landed_cost_detail": landed,
        "landed_cost_applied": bool(landed["country"]),
        "payment_fee_rate": float(rules.get("payment_fee_rate", 0.0)),
        "refund_rate": float(rules.get("refund_rate", 0.0)),
        "tax_rebate_rate": float(rules.get("tax_rebate_rate", 0.0)),
        "vat_in_rate": float(rules.get("vat_in_rate", 0.13)),
        # ---- 海外仓持有成本（D59）----
        "warehouse_id": warehouse_id,
        "holding_cost_cny": float(holding.get("holding_cost_cny", 0.0)) + round(inbound_fee, 2),
        "holding_cost_detail": holding,
        "holding_cost_applied": bool(holding.get("holding_cost_applied")),
        "inbound_fee_cny": round(inbound_fee, 2),
    }


def _quantize(amount: float) -> float:
    return round(float(amount or 0), 2)


def calc_profit(db: Session, tenant_id: int, product_id: int, price: float | None = None,
                destination_country: str = "", channel_type: str = "",
                site: str = "", qty: int = 1, warehouse_id: int | None = None,
                shop_id: int | None = None) -> dict:
    """真实利润 = 售价 - 全部成本 / 汇率。

    成本明细（8+ 项，D58）：
        采购 + 物流 + 关税 + 进口 VAT + 清关费 + 平台费 + 支付通道费 + 广告 + 退货成本
        - 出口退税
    海外仓持有成本（D59）：给出 ``warehouse_id`` 时叠加
        ``holding_cost_cny``（库龄 × 日费率 + 入库操作费）。
    海关申报货值取成交价（transaction value），故关税在拿到 ``price`` 后按
    ``price × fx`` 复算；未给出目的国时关税/进口 VAT/清关费为 0。
    """
    product = db.get(Product, product_id)
    if not product or product.tenant_id != tenant_id:
        raise ValueError(f"商品 {product_id} 不存在")
    price = float(price or (product.attrs or {}).get("sale_price") or 19.99)
    fx = float(setting_for(db, tenant_id, "fx", DEFAULT_FX).get("USD", 7.12))
    ce = cost_elements(db, tenant_id, product, destination_country=destination_country,
                       channel_type=channel_type, site=site, qty=qty,
                       declared_value_cny=price * fx, warehouse_id=warehouse_id)
    purchase = ce["purchase_cny"]
    logistics = ce["logistics_cny"]
    duty_cny = ce["duty_cny"]
    import_vat = ce["import_vat_cny"]
    clearance = ce["clearance_cny"]
    platform_fee = ce["fee_rate"] * price * fx
    payment_fee = ce["payment_fee_rate"] * price * fx
    # 退货成本：退货商品通常无法二次销售，按 (采购 + 物流 + 关税) × 退货率计损失。
    refund_cost = ce["refund_rate"] * (purchase + logistics + duty_cny)
    # 出口退税（减项）：退税额 = 采购含税价 / (1 + 进项税率) × 退税率；无票采购率为 0。
    tax_rebate = ce["tax_rebate_rate"] * purchase / (1 + ce["vat_in_rate"])
    # 海外仓持有成本（D59）：holding_cost_cny 已含入库操作费
    holding_cost = ce["holding_cost_cny"]
    cost_total_cny = (purchase + logistics + ce["ads_cny"] + duty_cny + import_vat + clearance
                      + platform_fee + payment_fee + refund_cost - tax_rebate
                      + holding_cost)
    profit = round(price - cost_total_cny / fx, 2)
    margin = round(profit / price, 4) if price else 0
    breakdown = {
        "purchase_cny": _quantize(purchase), "logistics_cny": _quantize(logistics),
        "duty_cny": _quantize(duty_cny), "import_vat_cny": _quantize(import_vat),
        "clearance_cny": _quantize(clearance), "platform_fee_cny": _quantize(platform_fee),
        "payment_fee_cny": _quantize(payment_fee), "ads_cny": _quantize(ce["ads_cny"]),
        "refund_cost_cny": _quantize(refund_cost), "tax_rebate_cny": _quantize(tax_rebate),
        "holding_cost_cny": _quantize(holding_cost),
    }
    sel_state, sel_limits = offer_state(db, tenant_id, product)
    return {
        "product_id": product_id,
        "purchase_cost": ce["purchase_cny"], "logistics_cost": ce["logistics_cny"],
        "platform_fee_rate": ce["fee_rate"], "ads_cost": ce["ads_cny"],
        "price": price, "profit": profit, "margin": margin, "currency": "USD", "fx": fx,
        # ---- 跨境到岸成本明细（D58）----
        "hs_code": ce["hs_code"], "destination_country": ce["destination_country"],
        "duty_cost": ce["duty_cny"], "import_vat_cost": ce["import_vat_cny"],
        "clearance_cost": ce["clearance_cny"], "payment_fee_rate": ce["payment_fee_rate"],
        "refund_rate": ce["refund_rate"], "tax_rebate_rate": ce["tax_rebate_rate"],
        "landed_cost_applied": ce["landed_cost_applied"],
        "landed_cost_detail": ce["landed_cost_detail"],
        "logistics_detail": ce["logistics_detail"], "fee_detail": ce["fee_detail"],
        # ---- 海外仓持有成本明细（D59）----
        "warehouse_id": ce.get("warehouse_id"),
        "holding_cost": ce["holding_cost_cny"],
        "holding_cost_applied": ce.get("holding_cost_applied", False),
        "holding_cost_detail": ce.get("holding_cost_detail", {}),
        "cost_total_cny": _quantize(cost_total_cny), "cost_breakdown": breakdown,
        # 成本依据报价：costing 实际采用的 offer（选定优先，否则最低在库价），
        # 供前端展示「成本依据报价 offer_id=X」并在选定失效时诚实标注回退，绝不前端本地派生。
        "offer_id": ce.get("offer_id"),
        # 选定报价状态与对外承诺限制（B3 契约唯一实现，见 offer_state）。
        "offer_state": sel_state,
        "offer_limits": sel_limits,
        # 成本上下文回显：shop_id 为空表示通用试算（不含店铺专属费用口径）。
        "shop_id": shop_id,
        "market": destination_country or None,
        "qty": qty,
        "is_generic_estimate": shop_id is None,
    }
