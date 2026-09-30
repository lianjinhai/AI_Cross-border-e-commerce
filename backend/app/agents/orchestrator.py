"""总调度 Agent（Commerce Orchestrator，对应规划第四章 4.1）：

理解用户目标 → 意图路由 → 调度专业 Agent → 汇总结果。

读取纪律（§18.3 第 2 步 / D45）
    本模块所有业务读取都走 Tool 层（Conversation / Listing / Supply / Order /
    Finance / Product Tool）；`chat()` 末尾的 `AiLog` 写入是 §18.3 第 3 步
    （Action 层）欠账，迁移期间不得删除（否则对话不再留痕），见架构文档
    「Agent 与 Runtime 的边界」现状说明。
"""
from ..ai.llm import ModelRouter
from ..models import AiLog
from ..services.action_identity import require_action_permission
from ..services.action_publish import publish_targets
from ..services.agent_outputs import finalize_listing_output
from ..services.ai_actions import ActionError
from .base import BaseAgent
from .listing import ListingAgent
from .listing_review import ListingReviewAgent


def invoke_listing(db, ctx, method, *args, scope_key=None):
    """同步调度已迁移的 Listing 动作；Task/Trace 仍属后续阶段。"""
    if method not in {"generate", "generate_batch", "optimize", "publish", "publish_batch"}:
        raise ValueError("该 Listing 动作尚未迁移到提案调度入口")
    ctx = require_action_permission(db, ctx, "listing:write")
    if method == "publish":
        publish_targets(db, ctx.legacy_tenant_id, args[0], args[1] if len(args) > 1 else None)
        with ListingReviewAgent(ctx.legacy_tenant_id, context=ctx) as reviewer:
            review = reviewer.review(args[0])
        if review["decision"] != "approved":
            raise ActionError(400 if review["decision"] == "rejected" else 409,
                              "上架复核未通过：" + "；".join(review["reasons"]))
    with ListingAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        output = getattr(agent, method)(*args)
    return finalize_listing_output(db, ctx, output, scope_key or ctx.trace_id)


class OrchestratorAgent(BaseAgent):
    name = "orchestrator"

    # ---------- 意图路由 ----------
    def chat(self, message: str) -> dict:
        msg = (message or "").strip()
        try:
            reply, intent, actions, data = self._route(msg)
        except Exception as e:
            reply, intent, actions, data = f"处理请求时出现问题：{e}", "error", [], None
        # 写路径（§18.3 第 3 步欠账）：chat 审计落 AiLog 仍是 Agent 直写，
        # 待 Runtime/Action 层接管后收敛。迁移期间保留，删掉等于对话不留痕。
        self.db.add(AiLog(tenant_id=self.tenant_id, agent="orchestrator", action="chat",
                          mode="rule", model="router", prompt=msg[:2000],
                          response=reply[:4000], latency_ms=0, ok=True))
        self.db.commit()
        return {"reply": reply, "intent": intent, "actions": actions, "data": data}

    def _route(self, msg: str) -> tuple[str, str, list, object]:
        if any(w in msg for w in ["选品", "发现", "机会", "爆款", "pick"]):
            return self._do_pick()
        if any(w in msg for w in ["趋势", "市场", "热销", "trend"]):
            return self._do_trends()
        if any(w in msg for w in ["定价", "价格", "利润", "price", "margin"]):
            return self._do_reprice()
        if any(w in msg for w in ["铺货", "上架", "发布", "listing"]):
            return self._do_listing_guide()
        if any(w in msg for w in ["供应商", "货源", "采购", "supplier"]):
            return self._do_suppliers()
        if any(w in msg for w in ["客服", "消息", "会话", "售后", "support"]):
            return self._do_support()
        if any(w in msg for w in ["风险", "巡检", "告警", "预警", "断货", "亏损", "alert", "risk"]):
            return self._do_risk_scan()
        if any(w in msg for w in ["报告", "经营", "分析", "bi", "report", "gmv"]):
            return self._do_bi()
        return self._fallback_chat(msg)

    # ---------- 各意图执行 ----------
    def _do_pick(self) -> tuple[str, str, list, object]:
        from .discovery import DiscoveryAgent

        with DiscoveryAgent(self.tenant_id) as a:
            r = a.pick_candidates(3, min_total=0)
        items = r["items"]
        lines = [f"· {i['title'][:40]}（机会分 {i['total']}：需求{i['demand']:.0f}/竞争{i['competition']:.0f}/利润{i['profit']:.0f}）"
                 for i in items]
        reply = f"已为您完成选品分析，Top {len(items)} 机会商品：\n" + "\n".join(lines) + \
                "\n可到「商品发现」页查看评分依据，或运行「AI工作流-自动铺货」完成后续动作。"
        return reply, "pick", ["pick_candidates"], items

    def _do_trends(self) -> tuple[str, str, list, object]:
        from .discovery import DiscoveryAgent

        with DiscoveryAgent(self.tenant_id) as a:
            trends = a.scan_trends()
        hot = sorted(trends, key=lambda t: -t["growth_30d"])[:5]
        lines = [f"· {t['keyword']}（{t['platform']}）30天增长 {t['growth_30d']}%，月搜索 {t['search_volume']}"
                 for t in hot]
        return "最新市场趋势 Top5：\n" + "\n".join(lines), "trends", ["scan_trends"], hot

    def _do_reprice(self) -> tuple[str, str, list, object]:
        from .pricing import PricingAgent

        with PricingAgent(self.tenant_id) as a:
            r = a.reprice_batch()
        rows = r["repriced"][:5]
        lines = [f"· 商品#{x['product_id']} 建议价 ${x['suggested_price']}（利润率 {x['margin'] * 100:.0f}%）"
                 for x in rows]
        reply = (f"已完成全店 {len(r['repriced'])} 个商品的动态定价分析，示例：\n" + "\n".join(lines) +
                 "\n明细见「动态定价」页。")
        return reply, "pricing", ["reprice_batch"], r["repriced"]

    def _do_listing_guide(self) -> tuple[str, str, list, object]:
        got = self.tool("listing").call("count_listings", status="draft")
        n = got.data["count"] if got.ok and isinstance(got.data, dict) else 0
        reply = (f"当前有 {n} 条草稿 Listing。建议两种方式：\n"
                 "1)「Listing工作台」选择商品点击「AI生成」→「发布」；\n"
                 "2)「AI工作流」运行「自动铺货全流程」，系统将自动完成 "
                 "选品→标准化→货源匹配→合规检测→生成→发布→广告草稿 全链路。")
        return reply, "listing", [], {"draft_listings": n}

    def _do_suppliers(self) -> tuple[str, str, list, object]:
        from .supplier import SupplierAgent

        # 取候选供应商也走 Tool（Supply Tool）：排序由 Tool 定为评分倒序，
        # 不再依赖数据库的隐式行序；上限 10 由调用方显式声明。
        got = self.tool("supply").call("search_suppliers", limit=10)
        sups = got.data if got.ok and isinstance(got.data, list) else []
        results = []
        with SupplierAgent(self.tenant_id) as a:
            for s in sups:
                sc = a.score_supplier(s["id"])
                results.append({"supplier_id": s["id"], "name": s["name"], "total": sc["total"]})
        results.sort(key=lambda x: -x["total"])
        lines = [f"· {x['name']}（综合 {x['total']}）" for x in results[:3]]
        return "供应商综合评分 Top3：\n" + "\n".join(lines), "supplier", ["score_supplier"], results

    def _do_support(self) -> tuple[str, str, list, object]:
        got = self.tool("conversation").call("count_conversations", status="open")
        open_n = got.data["count"] if got.ok and isinstance(got.data, dict) else 0
        reply = (f"当前有 {open_n} 个待处理会话。可到「智能客服」页使用「AI 自动回复」批量处理常规咨询"
                 "（订单查询/物流/售后意图识别准确率随知识库完善持续提升）。")
        return reply, "support", [], {"open_conversations": open_n}

    def _do_risk_scan(self) -> tuple[str, str, list, object]:
        """M3 主动巡检：跑一轮并把高风险项汇总给用户。

        只告警不执行——巡检产出的是"需要人来决策"的风险清单，
        不自动改价/下架/补货（架构红线 1）。
        """
        from ..services import alerting

        result = alerting.scan(self.db, self.tenant_id)
        rows = alerting.list_alerts(self.db, self.tenant_id, status="open", limit=50)
        high = [r for r in rows if r.level == "high"]
        shown = (high or rows)[:5]
        if not shown:
            reply = (f"已执行一轮经营巡检：未发现风险（新增 {result['created']} 条告警）。"
                     "巡检覆盖库存断货、广告亏损、售价低于成本、平台政策、退款率、"
                     "供应商时效、汇率波动、物流时效、Listing 老化九项。")
        else:
            lines = [f"· [{r.level}] {r.title}：{r.detail}" for r in shown]
            reply = (f"已执行一轮经营巡检，发现 {len(high)} 条高风险、"
                     f"{len(rows)} 条待处理：\n" + "\n".join(lines) +
                     "\n\n请到「风险巡检」页确认处理（系统只告警，不自动执行经营动作）。")
        return reply, "risk_scan", ["alert_scan"], {
            "created": result["created"], "skipped": result["skipped"],
            "open": len(rows), "high": len(high)}

    def _do_bi(self) -> tuple[str, str, list, object]:
        sales_got = self.tool("order").call("get_sales_summary", days=30)
        sales = sales_got.data if sales_got.ok and isinstance(sales_got.data, dict) else {}
        gmv, orders, profit = (float(sales.get("gmv", 0)), int(sales.get("orders", 0)),
                               float(sales.get("profit", 0)))
        ads_got = self.tool("finance").call("get_campaign_totals")
        ads = ads_got.data if ads_got.ok and isinstance(ads_got.data, dict) else {}
        spend, revenue = float(ads.get("spend", 0)), float(ads.get("revenue", 0))
        roi = round((revenue - spend) / spend, 2) if spend else 0
        count_got = self.tool("product").call("count_products", status="active")
        products = (count_got.data.get("count", 0)
                    if count_got.ok and isinstance(count_got.data, dict) else 0)
        reply = (f"近30天经营概况：GMV ${gmv:.2f}｜订单 {orders} 单｜真实利润 ${profit:.2f}｜"
                 f"广告花费 ${spend:.2f}，广告 ROI {roi}｜在售商品 {products} 个。"
                 "详细图表与 AI 经营报告见「BI经营分析」页。")
        return reply, "bi", [], {"gmv": gmv, "orders": orders, "profit": profit, "ad_roi": roi}

    def _fallback_chat(self, msg: str) -> tuple[str, str, list, object]:
        router = ModelRouter(self.db)
        if router.available:
            try:
                r = router.chat([
                    {"role": "system", "content": "你是跨境电商智能运营助手，用中文简洁回答经营相关问题。"},
                    {"role": "user", "content": msg},
                ])
                return r["content"], "chat", [], None
            except Exception:
                pass
        return ("我是您的 AI 经营助手，可以直接对我说：\n"
                "· 「帮我选品」— 输出机会商品 Top3\n"
                "· 「看看市场趋势」— 刷新并解读趋势\n"
                "· 「重新定价」— 全店动态定价\n"
                "· 「供应商评分」— 货源综合排名\n"
                "· 「经营情况」— 近30天经营概况\n"
                "· 「铺货建议」— 上架与工作流指引", "help", [], None)
