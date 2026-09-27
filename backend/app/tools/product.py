"""Product Tool：商品读取（§10.4 冻结清单）。

为什么返回 dict 而不是 ORM 对象
    Tool 层是 Agent 与数据库之间的边界。返回 ORM 对象等于把边界开成门洞：
    Agent 可以继续顺着关系属性做懒加载、继续 `obj.status = x` 改数据，
    红线 3「禁止 Agent 直接操作数据库」就只剩一句口号。dict 强制 Agent 只拿
    到显式声明的字段。
"""

from __future__ import annotations

import logging

from sqlalchemy import or_

from ..models import Product, ProductPerformance, ProductScore
from ..services.costing import best_purchase
from .base import BaseTool, Reading, as_int, clamp_limit, reading, ts
from .contract import ERR_NOT_FOUND, ToolError, ToolSpec

logger = logging.getLogger(__name__)


def product_dict(p: Product) -> dict:
    """商品的对外字段集（唯一一份，避免各 Tool 各挑一套字段）。"""
    return {"id": p.id, "sku": p.sku, "title": p.title, "category": p.category,
            "brand": p.brand, "status": p.status,
            "source_platform": p.source_platform, "attrs": p.attrs or {},
            "images": p.images or [], "created_at": ts(p.created_at)}


class ProductTool(BaseTool):
    name = "product"
    specs = (
        ToolSpec(tool="product", method="get_products", permission="product:read",
                 writes=False, summary="列出本租户商品，可按关键词过滤"),
        ToolSpec(tool="product", method="get_product_ids", permission="product:read",
                 writes=False, summary="列出本租户商品 id（批量任务用，按状态过滤）"),
        ToolSpec(tool="product", method="analyze_product", permission="product:read",
                 writes=False, summary="单商品的评分/经营表现/采购成本综合分析"),
        ToolSpec(tool="product", method="create_listing_draft", permission="listing:write",
                 writes=True, summary="由商品生成上架草稿（须经 Action System）"),
    )

    # ---------------------------------------------------------------- 只读实现
    def _get_products(self, limit=50, keyword: str = "", product_id=None) -> Reading:
        n = clamp_limit(limit)
        pid = None if product_id is None else as_int(product_id, "product_id")
        query = self.db.query(Product).filter(
            Product.tenant_id == self.context.tenant_id)
        if pid is not None:
            query = query.filter(Product.id == pid)
        text = (keyword or "").strip()
        if text:
            like = "%" + text + "%"
            query = query.filter(or_(Product.title.like(like), Product.sku.like(like)))
        rows = query.order_by(Product.id.desc()).limit(n).all()
        return reading([product_dict(p) for p in rows], table="products",
                       product_ids=[p.id for p in rows])

    def _get_product_ids(self, status: str = "", limit=300) -> Reading:
        """只返回商品 id。

        为什么单开一个方法而不是让调用方 `get_products(limit=500)` 再取 id
            批量任务（如全量需求预测）只需要 id 清单；拉全量商品行会把整个商品库
            灌进 Agent 上下文与审计（§10.2 的 data_scope 纪律）。`order_by(id)`
            让「取前 N 个」有确定顺序，不依赖数据库的隐式行序。
        """
        n = clamp_limit(limit, default=300, maximum=500)
        query = self.db.query(Product.id).filter(
            Product.tenant_id == self.context.tenant_id)
        state = (status or "").strip()
        if state:
            query = query.filter(Product.status == state)
        rows = query.order_by(Product.id).limit(n).all()
        return reading([r[0] for r in rows], table="products",
                       status=state, count=len(rows))

    def _analyze_product(self, product_id: int) -> Reading:
        product = self._owned(product_id)
        score = (self.db.query(ProductScore)
                 .filter(ProductScore.tenant_id == self.context.tenant_id,
                         ProductScore.product_id == product.id)
                 .order_by(ProductScore.id.desc()).first())
        perf = (self.db.query(ProductPerformance)
                .filter(ProductPerformance.tenant_id == self.context.tenant_id,
                        ProductPerformance.product_id == product.id)
                .order_by(ProductPerformance.computed_at.desc(),
                          ProductPerformance.id.desc()).first())
        cost: dict = {"purchase_cny": None, "offer_id": None, "error": ""}
        try:
            purchase_cny, offer_id = best_purchase(self.db, self.context.tenant_id, product)
            cost = {"purchase_cny": purchase_cny, "offer_id": offer_id, "error": ""}
        except Exception as exc:
            # 缺汇率时成本算不出来，但这不该让「评分 + 经营表现」一起失败。
            # 降级必须可见：把原因写进返回体，而不是悄悄给个 0（§15.4）。
            logger.warning("analyze_product 采购成本不可得 product_id=%s: %s",
                           product.id, exc)
            cost["error"] = "%s: %s" % (type(exc).__name__, exc)
        return reading(
            {"product": product_dict(product),
             "score": self._score_dict(score),
             "performance": self._perf_dict(perf),
             "purchase_cost": cost},
            table="products", product_id=product.id,
            score_id=score.id if score else None,
            performance_id=perf.id if perf else None)

    # ---------------------------------------------------------------- 内部
    def _owned(self, product_id: int) -> Product:
        pid = as_int(product_id, "product_id")
        product = self.db.get(Product, pid)
        if not product or product.tenant_id != self.context.tenant_id:
            # 跨租户与不存在返回同一个错误码：区分开会让调用方探测到别家商品是否存在。
            raise ToolError(ERR_NOT_FOUND, "商品 %s 不存在" % pid)
        return product

    @staticmethod
    def _score_dict(score: ProductScore | None) -> dict | None:
        if score is None:
            return None
        return {"id": score.id, "demand": score.demand, "competition": score.competition,
                "profit": score.profit, "risk": score.risk, "total": score.total,
                "reasons": score.reasons or [], "model": score.model,
                "created_at": ts(score.created_at)}

    @staticmethod
    def _perf_dict(perf: ProductPerformance | None) -> dict | None:
        if perf is None:
            return None
        return {"id": perf.id, "window_days": perf.window_days,
                "units_sold": perf.units_sold, "revenue": perf.revenue,
                "profit": perf.profit, "margin": perf.margin,
                "refund_rate": perf.refund_rate, "sell_through": perf.sell_through,
                "performance_score": perf.performance_score,
                "computed_at": ts(perf.computed_at)}
