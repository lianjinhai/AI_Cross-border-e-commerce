"""Market Tool：市场趋势与机会评分（§10.4 冻结清单）。

为什么机会分不在本 Tool 里「重算」而是读 `ProductScore`
    评分口径属于业务算法，唯一实现在 `DiscoveryAgent` 侧（评分依据、权重、
    LLM/规则双模都在那里）。Tool 层重算一遍必然与之漂移，而且会造出第二份
    真相：页面上显示 78 分、Agent 拿到 81 分，没人说得清哪个对（T-53）。
    本 Tool 只负责「把已落库的评分读出来」，算法归位留待后续批次。
"""

from __future__ import annotations

from ..models import MarketTrend, Product, ProductPerformance, ProductScore
from .base import BaseTool, Reading, as_int, clamp_limit, reading, ts
from .contract import ERR_NOT_FOUND, ToolError, ToolSpec


def trend_dict(t: MarketTrend) -> dict:
    return {"id": t.id, "keyword": t.keyword, "platform": t.platform,
            "search_volume": t.search_volume, "growth_30d": t.growth_30d,
            "competition": t.competition, "note": t.note, "source": t.source,
            "updated_at": ts(t.updated_at)}


class MarketTool(BaseTool):
    name = "market"
    specs = (
        ToolSpec(tool="market", method="get_trends", permission="product:read",
                 writes=False, summary="读取市场趋势/关键词，按搜索量倒序"),
        ToolSpec(tool="market", method="score_opportunity", permission="product:read",
                 writes=False, summary="读取指定商品的最新机会评分与经营表现"),
    )

    def _get_trends(self, limit=20, keyword: str = "") -> Reading:
        n = clamp_limit(limit, default=20)
        query = self.db.query(MarketTrend).filter(
            MarketTrend.tenant_id == self.context.tenant_id)
        text = (keyword or "").strip()
        if text:
            query = query.filter(MarketTrend.keyword.like("%" + text + "%"))
        rows = (query.order_by(MarketTrend.search_volume.desc(), MarketTrend.id.desc())
                .limit(n).all())
        return reading([trend_dict(t) for t in rows], table="market_trends",
                       trend_ids=[t.id for t in rows])

    def _score_opportunity(self, product_id: int) -> Reading:
        pid = as_int(product_id, "product_id")
        product = self.db.get(Product, pid)
        if not product or product.tenant_id != self.context.tenant_id:
            raise ToolError(ERR_NOT_FOUND, "商品 %s 不存在" % pid)
        score = (self.db.query(ProductScore)
                 .filter(ProductScore.tenant_id == self.context.tenant_id,
                         ProductScore.product_id == pid)
                 .order_by(ProductScore.id.desc()).first())
        if score is None:
            # 「还没评过分」与「评了 0 分」是两件事。返回 0 分会让 Agent 把
            # 「尚未评估」当成「机会极差」并据此淘汰商品。
            raise ToolError(ERR_NOT_FOUND, "商品 %s 尚无机会评分记录" % pid)
        perf = (self.db.query(ProductPerformance)
                .filter(ProductPerformance.tenant_id == self.context.tenant_id,
                        ProductPerformance.product_id == pid)
                .order_by(ProductPerformance.computed_at.desc(),
                          ProductPerformance.id.desc()).first())
        return reading(
            {"product_id": pid, "score": {"demand": score.demand,
                                          "competition": score.competition,
                                          "profit": score.profit, "risk": score.risk,
                                          "total": score.total,
                                          "reasons": score.reasons or [],
                                          "model": score.model,
                                          "created_at": ts(score.created_at)},
             "performance": None if perf is None else {
                 "window_days": perf.window_days, "units_sold": perf.units_sold,
                 "revenue": perf.revenue, "margin": perf.margin,
                 "performance_score": perf.performance_score,
                 "computed_at": ts(perf.computed_at)}},
            table="product_scores", product_id=pid, score_id=score.id,
            performance_id=perf.id if perf else None)
