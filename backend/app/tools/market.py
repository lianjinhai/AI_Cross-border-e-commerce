"""Market Tool：市场趋势与机会评分（§10.4 冻结清单）。

为什么机会分不在本 Tool 里「重算」而是读 `ProductScore`
    评分口径属于业务算法，唯一实现在 `DiscoveryAgent` 侧（评分依据、权重、
    LLM/规则双模都在那里）。Tool 层重算一遍必然与之漂移，而且会造出第二份
    真相：页面上显示 78 分、Agent 拿到 81 分，没人说得清哪个对（T-53）。
    本 Tool 只负责「把已落库的评分读出来」，算法归位留待后续批次。
"""

from __future__ import annotations

from sqlalchemy import func

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
        ToolSpec(tool="market", method="get_latest_scores", permission="product:read",
                 writes=False, summary="每个商品的最新机会评分（批量选品排名用）"),
        ToolSpec(tool="market", method="pick_trend", permission="product:read",
                 writes=False, summary="随机取一条市场趋势（无类目匹配时的需求兜底）"),
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

    def _get_latest_scores(self, limit=500) -> Reading:
        """每个商品的最新一条机会评分（批量排名用，按商品 id 升序）。

        为什么用 `max(id)` 取「最新」而不是 `created_at`：同一批写入的多条评分
        时间戳可能相同（秒级精度），id 才是唯一单调的次序（与 D42 复核结论同款
        口径）。上限 500 个商品；超出时应分批处理，而不是抬高上限（D44 同款边界）。
        """
        n = clamp_limit(limit, default=500, maximum=500)
        newest = (self.db.query(func.max(ProductScore.id).label("score_id"))
                  .filter(ProductScore.tenant_id == self.context.tenant_id)
                  .group_by(ProductScore.product_id).subquery())
        rows = (self.db.query(ProductScore)
                .join(newest, ProductScore.id == newest.c.score_id)
                .order_by(ProductScore.product_id).limit(n).all())
        return reading([{"product_id": s.product_id, "demand": s.demand,
                         "competition": s.competition, "profit": s.profit,
                         "risk": s.risk, "total": s.total,
                         "reasons": s.reasons or [], "model": s.model}
                        for s in rows],
                       table="product_scores", count=len(rows))

    def _pick_trend(self) -> Reading:
        """随机取一条趋势：类目无匹配趋势时的需求兜底（保留原 DiscoveryAgent 语义）。

        为什么保留随机而不是「取搜索量最高的一条」：兜底的原意是让无类目匹配的
        商品拿到分布多样的需求分，而不是全体同一个最高分（那会把兜底变成新的
        单点偏差）。
        """
        row = (self.db.query(MarketTrend)
               .filter(MarketTrend.tenant_id == self.context.tenant_id)
               .order_by(func.random()).first())
        if row is None:
            raise ToolError(ERR_NOT_FOUND, "本租户暂无市场趋势数据")
        return reading(trend_dict(row), table="market_trends", trend_id=row.id)
