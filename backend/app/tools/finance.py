"""Finance Tool：利润、单位经济与汇率（§10.4 冻结清单）。

为什么一律转调 `services/costing.py` 而不在本层算
    成本/利润口径必须**唯一**：定价页显示的利润率、工厂机会门禁用的利润率、
    Agent 建议降价时引用的利润率，只要有一处算法不同，三个数就对不上，而且
    没人能判断哪个是对的。`services/costing.py` 已是该口径的唯一实现
    （D-? 见其模块 docstring），本 Tool 只做「加闸门 + 记审计 + 转格式」。

为什么汇率缺失要报 NOT_FOUND 而不是回退默认值
    `costing.to_cny` 的纪律是「缺汇率必须抛错，禁止用猜测汇率算利润」。
    在 Tool 层回退一个默认汇率，等于把这条纪律从唯一入口处废掉——所有 Agent
    都会拿到一个看起来正常的利润率。缺就是缺，让调用方知道。

为什么广告活动（AdCampaign）读取挂在 Finance Tool（D44）
    冻结权限目录里没有独立的 ads 域，新增权限 key 必须走迁移（D39 先例）。而
    AdCampaign 的字段（预算/花费/收入）全是金钱事实，Finance Intelligence 的
    ROI 分析正是它的消费方。跨域复用权限 key 已有先例（market→product:read、
    store→order:read）。若未来要独立 ads 域，按「只增不改」补 key + 迁移即可。
"""

from __future__ import annotations

from sqlalchemy import func

from ..models import AdCampaign, Product
from ..services.costing import calc_profit, cost_elements, latest_fx
from .base import BaseTool, Reading, as_int, clamp_limit, reading, ts
from .contract import ERR_BAD_PARAM, ERR_NOT_FOUND, ToolError, ToolSpec


def campaign_dict(c: AdCampaign) -> dict:
    """广告活动字段口径（唯一一份，避免各调用方各挑一套）。"""
    return {"id": c.id, "name": c.name, "platform": c.platform,
            "product_id": c.product_id, "keywords": c.keywords or [],
            "budget": c.budget, "spend": c.spend, "revenue": c.revenue,
            "impressions": c.impressions, "clicks": c.clicks, "orders": c.orders,
            "status": c.status, "created_at": ts(c.created_at),
            "updated_at": ts(c.updated_at)}


class FinanceTool(BaseTool):
    name = "finance"
    specs = (
        ToolSpec(tool="finance", method="calculate_profit", permission="finance:read",
                 writes=False, summary="按唯一成本口径计算单件真实利润与利润率"),
        ToolSpec(tool="finance", method="get_unit_economics", permission="finance:read",
                 writes=False, summary="拆出采购/物流/佣金/广告/汇率等成本要素"),
        ToolSpec(tool="finance", method="get_fx_rate", permission="finance:read",
                 writes=False, summary="读取最近一条生效汇率"),
        ToolSpec(tool="finance", method="get_campaigns", permission="finance:read",
                 writes=False, summary="读取广告活动（预算/花费/收入/点击），可按状态或商品过滤"),
        ToolSpec(tool="finance", method="get_campaign_totals", permission="finance:read",
                 writes=False, summary="广告总花费/总收入聚合（经营概况 ROI 的输入）"),
    )

    def _calculate_profit(self, product_id: int, price=None) -> Reading:
        pid = as_int(product_id, "product_id")
        self._require_product(pid)
        try:
            data = calc_profit(self.db, self.context.tenant_id, pid, price)
        except ValueError as exc:  # costing 对「缺汇率」等 fail-closed 场景抛 ValueError
            raise ToolError(ERR_NOT_FOUND, str(exc)) from exc
        return reading(data, table="products", product_id=pid)

    def _get_unit_economics(self, product_id: int, platform: str = "") -> Reading:
        pid = as_int(product_id, "product_id")
        product = self._require_product(pid)
        try:
            data = dict(cost_elements(self.db, self.context.tenant_id, product, platform))
        except ValueError as exc:
            raise ToolError(ERR_NOT_FOUND, str(exc)) from exc
        data["product_id"] = pid
        data["platform"] = platform or (product.attrs or {}).get("platform") or "shopee"
        return reading(data, table="products", product_id=pid,
                       offer_id=data.get("offer_id"))

    def _get_fx_rate(self, base: str = "USD", quote: str = "CNY") -> Reading:
        b = (base or "").strip().upper()
        q = (quote or "").strip().upper()
        if not b or not q:
            raise ToolError(ERR_BAD_PARAM, "base / quote 不能为空")
        rate = latest_fx(self.db, self.context.tenant_id, b, q)
        if rate is None:
            raise ToolError(ERR_NOT_FOUND, "缺少 %s→%s 的有效汇率" % (b, q))
        return reading({"base": b, "quote": q, "rate": float(rate)},
                       table="exchange_rates", base=b, quote=q)

    def _require_product(self, product_id: int) -> Product:
        product = self.db.get(Product, product_id)
        if not product or product.tenant_id != self.context.tenant_id:
            raise ToolError(ERR_NOT_FOUND, "商品 %s 不存在" % product_id)
        return product

    def _get_campaigns(self, status: str = "", product_id=None, limit=50) -> Reading:
        """广告活动读取。

        返回**原始字段**（预算/花费/收入/曝光/点击/订单），ROI/CTR/CVR 等比率留给
        调用方计算——比率是展示口径，写进 Tool 会与页面的算法漂移（T-53）。
        """
        n = clamp_limit(limit)
        pid = None if product_id in (None, "") else as_int(product_id, "product_id")
        state = (status or "").strip()
        query = self.db.query(AdCampaign).filter(
            AdCampaign.tenant_id == self.context.tenant_id)
        if pid is not None:
            query = query.filter(AdCampaign.product_id == pid)
        if state:
            query = query.filter(AdCampaign.status == state)
        rows = query.order_by(AdCampaign.id.desc()).limit(n).all()
        return reading([campaign_dict(c) for c in rows], table="ad_campaigns",
                       campaign_ids=[c.id for c in rows])

    def _get_campaign_totals(self) -> Reading:
        """广告总花费 / 总收入（经营概况 ROI 的输入）：在 SQL 侧聚合，不取回活动行。

        ROI = (revenue - spend) / spend 归调用方按自身场景计算：本 Tool 只保证
        两个总量的口径唯一；spend 为 0 的除法边界属于调用方的业务判断。
        """
        row = (self.db.query(func.sum(AdCampaign.spend), func.sum(AdCampaign.revenue))
               .filter(AdCampaign.tenant_id == self.context.tenant_id).first())
        spend, revenue = float(row[0] or 0), float(row[1] or 0)
        return reading({"spend": spend, "revenue": revenue}, table="ad_campaigns")
