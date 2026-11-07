"""核价报价轮次（M2-A）：只增不改的报价历史 + 成本来源快照 + 低价门禁。

为什么单独建表而不是复用 ``pricing_records``：
    ``PricingRecord`` 是 PricingAgent 的**成本拆解快照**——记录「某一刻算过一次利润」，
    同一次报价会被算很多遍（改售价、换店铺、换目的国各算一次）。核价要回答的是另一组
    问题：**报过几个价、谁批的、依据哪份成本、门槛是多少**。把这两件事塞进一张表，
    迟早出现「利润算过 = 价格已核」的错位，把试算当成已核价。

三条不可让步的口径：
1. **只增不改**：本模块不提供 update/delete；每次报价/还价/接受都是新行，
   ``round_no`` 按 ``(tenant_id, product_id)`` 递增，唯一约束兜底并发。
2. **币种必带**：金额离开币种就是错数。``currency`` 为空直接拒绝，绝不默认 USD；
   非 USD 报价按「先折人民币、再折 USD」进利润口径，缺汇率时 fail-closed（不猜汇率）。
3. **成本快照要能对账**：每轮存 ``cost_fingerprint``，采购价/报价来源/汇率/佣金率/
   成本合计/门槛任一变化即失配——旧轮次当场不再「当前」，核价必须重走。
   这是「到期/变价必须重新阻断」的机制，不靠人去记。

本模块只做计算与写入，不抛 HTTP 错误、不提交事务：调用方（Launch handler 或路由）
负责把领域结论翻成对应状态码。
"""

import hashlib
import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import PriceRound
from . import costing

# 参与指纹的成本字段：变了就说明「同一份成本」不再成立。
FINGERPRINT_KEYS = ("purchase_cny", "offer_id", "fx", "platform_fee_rate",
                    "cost_total_cny", "min_margin", "target_margin")
REVIEW_ACTIONS = frozenset({"REPORT", "COUNTER"})
ROUND_ACTIONS = frozenset({"REPORT", "ACCEPT", "COUNTER"})
CURRENCY_LENGTH = 3


class PriceRoundError(ValueError):
    """领域校验失败（币种不合法 / 缺汇率 / 无可接受轮次）；调用方负责映射状态码。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_currency(currency: str | None) -> str:
    """校验并归一化币种：必须是 3 位字母代码；空值一律拒绝（不默认 USD）。

    «无币种显「—」，禁默认 `$`» 的前置条件——后端先不许出现「没有币种的金额」，
    前端才不需要替它猜。
    """
    value = (currency or "").strip().upper()
    if len(value) != CURRENCY_LENGTH or not value.isalpha():
        raise PriceRoundError("CURRENCY_REQUIRED", "报价必须带 3 位币种代码（如 USD/CNY/EUR）")
    return value


def _usd_price(db: Session, tenant_id: int, price: float, currency: str) -> float:
    """把任意币种售价折成「USD 口径」，用于复用唯一一份利润计算。

    利润口径以 USD 售价为基准（``costing.calc_profit``）。其他币种先折人民币再折 USD，
    缺任一段汇率即抛错——**不用猜测汇率凑一个能通过门禁的毛利**。
    """
    if currency == "USD":
        return price
    fx = float(costing.setting_for(db, tenant_id, "fx", costing.DEFAULT_FX).get("USD", 7.12))
    try:
        cny = costing.to_cny(db, tenant_id, price, currency)
    except ValueError as exc:
        raise PriceRoundError("FX_MISSING", str(exc)) from exc
    return cny / fx


def _fingerprint(snapshot: dict) -> str:
    payload = {key: snapshot.get(key) for key in FINGERPRINT_KEYS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def quote(db: Session, tenant_id: int, product_id: int, price: float, currency: str,
          shop_id: int | None = None) -> dict:
    """算一轮报价的毛利与成本快照（不写库）：低价门禁与轮次落库共用同一份结果。

    返回 ``{price, currency, price_usd, margin, min_margin, margin_ok, target_margin,
    snapshot, fingerprint}``。``margin_ok`` 只是事实，不是决定——阻断由调用方给出。
    """
    currency = normalize_currency(currency)
    try:
        price = float(price)
    except (TypeError, ValueError) as exc:
        raise PriceRoundError("PRICE_INVALID", "报价必须是数字") from exc
    if not price > 0:
        raise PriceRoundError("PRICE_INVALID", "报价必须大于 0")
    price_usd = _usd_price(db, tenant_id, price, currency)
    try:
        result = costing.calc_profit(db, tenant_id, product_id, price=price_usd, shop_id=shop_id)
    except ValueError as exc:
        # 商品不存在 / 缺汇率：都属「算不出可信毛利」，不放行也不当成 0。
        raise PriceRoundError("COST_UNAVAILABLE", str(exc)) from exc
    rules = costing.setting_for(db, tenant_id, "rules", costing.DEFAULT_RULES)
    margin = result["margin"]
    min_margin = float(rules["min_margin"])
    if not isinstance(margin, (int, float)) or not isinstance(min_margin, (int, float)):
        raise PriceRoundError("COST_UNAVAILABLE", "毛利口径不可用，禁止核价")
    snapshot = {
        "price_usd": round(price_usd, 4), "purchase_cny": result["cost_breakdown"]["purchase_cny"],
        "offer_id": result.get("offer_id"), "fx": result["fx"],
        "platform_fee_rate": result["platform_fee_rate"],
        "cost_total_cny": result["cost_total_cny"],
        "cost_breakdown": result["cost_breakdown"],
        "margin": margin, "currency": currency, "price": price,
        "min_margin": min_margin, "target_margin": float(rules["target_margin"]),
        "offer_state": result.get("offer_state"),
        "offer_limits": list(result.get("offer_limits") or []),
        "snapshot_at": datetime.utcnow().isoformat(),
    }
    return {"price": price, "currency": currency, "price_usd": round(price_usd, 4),
            "margin": margin, "min_margin": min_margin, "margin_ok": margin >= min_margin,
            "target_margin": float(rules["target_margin"]),
            "snapshot": snapshot, "fingerprint": _fingerprint(snapshot)}


def latest(db: Session, tenant_id: int, product_id: int, run_id: int | None = None) -> PriceRound | None:
    """取最新一轮；给 ``run_id`` 时只在该流程内取（跨流程历史不参与本轮判定）。"""
    query = db.query(PriceRound).filter(PriceRound.tenant_id == tenant_id,
                                        PriceRound.product_id == product_id)
    if run_id is not None:
        query = query.filter(PriceRound.run_id == run_id)
    return query.order_by(PriceRound.id.desc()).first()


def latest_review(db: Session, tenant_id: int, product_id: int, run_id: int | None = None) -> PriceRound | None:
    """取最新一个「报价轮次」（REPORT/COUNTER）；ACCEPT 轮是决策，不是评审记录。"""
    query = db.query(PriceRound).filter(PriceRound.tenant_id == tenant_id,
                                        PriceRound.product_id == product_id,
                                        PriceRound.action.in_(sorted(REVIEW_ACTIONS)))
    if run_id is not None:
        query = query.filter(PriceRound.run_id == run_id)
    return query.order_by(PriceRound.id.desc()).first()


def history(db: Session, tenant_id: int, product_id: int, limit: int = 50) -> list[PriceRound]:
    """报价历史（新→旧，只读）；``limit`` 有上界，防止一次拉全表。"""
    limit = max(1, min(int(limit or 50), 200))
    return (db.query(PriceRound)
            .filter(PriceRound.tenant_id == tenant_id, PriceRound.product_id == product_id)
            .order_by(PriceRound.id.desc()).limit(limit).all())


def next_round_no(db: Session, tenant_id: int, product_id: int) -> int:
    """下一轮号 = 当前最大值 + 1；唯一约束兜底并发（冲突由调用方回 409 重试）。"""
    current = (db.query(func.max(PriceRound.round_no))
               .filter(PriceRound.tenant_id == tenant_id, PriceRound.product_id == product_id)
               .scalar())
    return int(current or 0) + 1


def append(db: Session, *, tenant_id: int, product_id: int, action: str, quote_result: dict,
           run_id: int | None = None, step_code: str = "", decision: dict | None = None,
           created_by: int | None = None) -> PriceRound:
    """追加一轮（只增不改）；``decision`` 是人工决定留痕，ACCEPT/COUNTER 必填。"""
    if action not in ROUND_ACTIONS:
        raise PriceRoundError("ROUND_ACTION_INVALID", "未知的轮次动作：" + str(action)[:16])
    row = PriceRound(tenant_id=tenant_id, product_id=product_id, run_id=run_id,
                     step_code=step_code or "", round_no=next_round_no(db, tenant_id, product_id),
                     action=action, price=quote_result["price"], currency=quote_result["currency"],
                     margin=quote_result["margin"], min_margin=quote_result["min_margin"],
                     margin_ok=bool(quote_result["margin_ok"]),
                     cost_snapshot=quote_result["snapshot"],
                     cost_fingerprint=quote_result["fingerprint"],
                     decision=dict(decision or {}), created_by=created_by)
    db.add(row)
    db.flush()
    return row


def decision_of(db: Session, tenant_id: int, product_id: int, run_id: int | None = None) -> str | None:
    """当前决策：最新一轮是 ACCEPT 才算「已接受」，COUNTER 表示还在还价。"""
    row = latest(db, tenant_id, product_id, run_id)
    if row is None:
        return None
    value = (row.decision or {}).get("decision")
    return value if value in {"ACCEPT", "COUNTER"} else None


def snapshot_current(db: Session, tenant_id: int, product_id: int,
                     run_id: int | None = None, shop_id: int | None = None) -> bool | None:
    """最新评审轮次的成本快照是否仍是当前成本；无轮次或算不出成本时返回 None（UNKNOWN）。

    返回 None 而不是 False：条件 DSL 里 UNKNOWN 与「明确不通过」不同，前者是「还判断不了」，
    不能让步骤因为算不出成本就被静默放行，也不该谎称它「已失效」。
    """
    row = latest_review(db, tenant_id, product_id, run_id)
    if row is None or not row.cost_fingerprint:
        return None
    try:
        current = quote(db, tenant_id, product_id, row.price, row.currency or "", shop_id=shop_id)
    except PriceRoundError:
        return None
    return current["fingerprint"] == row.cost_fingerprint


def pricing_facts(db: Session, tenant_id: int, product_id: int, run_id: int | None = None,
                  shop_id: int | None = None) -> dict:
    """供 Launch 条件求值的定价事实（``pricing.*``）。

    只给**已存在的事实**：没有报价轮次就不放 ``review_id``，条件求值为 UNKNOWN，
    ``PRICE_REVIEW`` 保持未完成——绝不凭空造一个 review_id 让步骤「看起来完成了」。
    """
    review = latest_review(db, tenant_id, product_id, run_id)
    facts: dict = {}
    if review is not None:
        facts.update({"review_id": review.id, "review_round_no": review.round_no,
                      "price": review.price, "currency": review.currency or None,
                      "margin": review.margin, "min_margin": review.min_margin,
                      "margin_ok": bool(review.margin_ok),
                      "quote_action": review.action})
    decision = decision_of(db, tenant_id, product_id, run_id)
    if decision is not None:
        facts["decision"] = decision
    return facts
