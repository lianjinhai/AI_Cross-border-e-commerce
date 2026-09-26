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
"""

from __future__ import annotations

from ..models import Product
from ..services.costing import calc_profit, cost_elements, latest_fx
from .base import BaseTool, Reading, as_int, reading
from .contract import ERR_BAD_PARAM, ERR_NOT_FOUND, ToolError, ToolSpec


class FinanceTool(BaseTool):
    name = "finance"
    specs = (
        ToolSpec(tool="finance", method="calculate_profit", permission="finance:read",
                 writes=False, summary="按唯一成本口径计算单件真实利润与利润率"),
        ToolSpec(tool="finance", method="get_unit_economics", permission="finance:read",
                 writes=False, summary="拆出采购/物流/佣金/广告/汇率等成本要素"),
        ToolSpec(tool="finance", method="get_fx_rate", permission="finance:read",
                 writes=False, summary="读取最近一条生效汇率"),
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
