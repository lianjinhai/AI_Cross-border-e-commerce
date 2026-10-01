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
from ..services.agent_outputs import finalize_ad_drafts, finalize_listing_output
from ..services.ai_actions import ActionError
from ..services.compliance_facts import targets as compliance_targets
from ..services.compliance_outputs import (
    compliance_batch_result,
    compliance_scope_items,
    finalize_compliance,
    recover_compliance,
    validate_items,
)
from ..services.discovery_outputs import finalize_discovery_scores, recover_discovery_score
from ..services.pricing_outputs import finalize_pricing_output
from ..services.product_outputs import (
    batch_result,
    finalize_product,
    recover_product,
    recover_range,
)
from ..services.review_outputs import finalize_reviews, review_targets, synchronize_review_rules
from .base import BaseAgent
from .compliance import ComplianceAgent
from .discovery import DiscoveryAgent, ProductAgent
from .listing import ListingAgent
from .listing_review import ListingReviewAgent
from .pricing import AdsAgent, PricingAgent


def invoke_compliance(db, ctx, method, *args, scope_key=None):
    """真实身份发起检测，先恢复原范围，再原子保存报告与风险 Action。"""
    ctx = require_action_permission(db, ctx, "compliance:check")
    scope = scope_key or ctx.trace_id
    if method in {"check", "check_product", "check_listing"}:
        items = [{"target_type": args[0], "ref_id": args[1]}] if method == "check" else [
            {"target_type": "product" if method == "check_product" else "listing", "ref_id": args[0]}]
    elif method == "check_batch":
        params, context = args
        items = compliance_scope_items(params, context)
        manifest = context.get("_action_compliance_manifest")
        if manifest is not None and manifest != {"scope": scope, "items": items}:
            raise ActionError(409, "同一工作流合规目标范围已变化")
    else:
        raise ActionError(400, "未迁移的合规动作")
    validate_items(items)
    for item in items:
        # 提前验证不存在/跨租户，HTTP 保留明确 404，不依赖 Agent 模糊失败。
        compliance_targets(db, ctx.legacy_tenant_id, item["target_type"], item["ref_id"])
    reports = recover_compliance(db, ctx, scope, items)
    if reports is None:
        try:
            with ComplianceAgent(ctx.legacy_tenant_id, context=ctx) as agent:
                outputs = [agent.check(item["target_type"], item["ref_id"]) for item in items]
        except ValueError as exc:
            raise ActionError(409, str(exc)) from exc
        reports = finalize_compliance(db, ctx, outputs, scope, items)
    return compliance_batch_result(reports, scope, items) if method == "check_batch" else reports[0]


def invoke_product(db, ctx, method, *args, scope_key=None):
    """绑定可信身份，先恢复原 Action，再生成安全标准化提案。"""
    if method not in {"standardize", "standardize_batch"}:
        raise ValueError("未迁移的商品动作")
    ctx = require_action_permission(db, ctx, "product:write")
    scope = scope_key or ctx.trace_id
    results, errors = [], []
    with ProductAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        if method == "standardize":
            return (recover_product(db, ctx, args[0], scope)
                    or finalize_product(db, ctx, agent.standardize(args[0]), scope))
        params, context = args
        saved = context.get("_action_product_manifest")
        supplied = params.get("product_ids", context.get("product_ids"))
        if saved is not None:
            if saved.get("scope") != scope:
                raise ActionError(409, "商品标准化恢复范围无效")
            ids = saved["product_ids"]
            if supplied is not None and list(dict.fromkeys(supplied[:200])) != ids:
                raise ActionError(409, "同一工作流范围的商品清单已变化")
        else:
            ids = recover_range(db, ctx, scope, supplied)
        if ids is None:
            got = agent.tool("product").call("get_product_ids", status="active", limit=200)
            if not got.ok:
                raise ActionError(403, "标准化商品范围读取失败")
            ids = got.data
        ids = list(dict.fromkeys(ids[:200]))
        manifest = {"scope": scope, "product_ids": ids}
        for pid in ids:
            slot_scope = f"{scope}:product:{pid}"
            try:
                result = (recover_product(db, ctx, int(pid), slot_scope)
                          or finalize_product(db, ctx, agent.standardize(int(pid)), slot_scope, manifest))
                results.append(result)
            except (ActionError, ValueError, TypeError) as exc:
                db.rollback()
                errors.append({"product_id": pid, "error": str(exc)})
    return batch_result(results, errors, manifest)


def invoke_review(db, ctx, method, *args, scope_key=None, approval=False):
    """调度复核分析并保存产物；审批身份仍只需既有合规审批权限。"""
    permission = "compliance:approve" if approval else "listing:write"
    ctx = require_action_permission(db, ctx, permission)
    if method not in {"review", "review_batch"}:
        raise ActionError(400, "未迁移的复核分析")
    scope = scope_key or ctx.trace_id
    if method == "review":
        ids = [args[0]]
    else:
        params, context = args
        ids = params.get("listing_ids", context.get("listing_ids", []))
        manifest = context.get("_action_review_manifest")
        if manifest and (manifest.get("scope") != scope or manifest.get("listing_ids") != ids):
            raise ActionError(409, "同一工作流复核范围已变化")
    if not isinstance(ids, list) or len(ids) > 50 or any(type(lid) is not int or lid <= 0 for lid in ids):
        raise ActionError(400, "复核 Listing 范围无效")
    ids = list(dict.fromkeys(ids))
    syncs = synchronize_review_rules(db, ctx, ids, permission)
    ctx = require_action_permission(db, ctx, permission)
    items = []
    try:
        with ListingReviewAgent(ctx.legacy_tenant_id, context=ctx) as agent:
            for lid in ids:
                platform = review_targets(db, ctx, lid)[0].platform
                items.append(agent.review(lid, rule_sync=syncs.get(platform)))
    except ValueError as exc:
        raise ActionError(409, str(exc)) from exc
    results = finalize_reviews(db, ctx, items, scope, ids, permission, syncs)
    if method == "review":
        return results[0]
    approved, blocked = [], []
    for lid, result in zip(ids, results, strict=True):
        (approved if result["decision"] == "approved" else blocked).append({"listing_id": lid, **result})
    return {"approved": approved, "blocked": blocked,
            "business_status": "partial" if approved and blocked else ("blocked" if blocked else "success"),
            "context_patch": {"approved_listing_ids": [item["listing_id"] for item in approved],
                              "review_blocked": blocked, "_action_review_manifest": {"scope": scope, "listing_ids": ids}}}


def invoke_listing(db, ctx, method, *args, scope_key=None):
    """同步调度已迁移的 Listing 动作；Task/Trace 仍属后续阶段。"""
    if method not in {"generate", "generate_batch", "optimize", "publish", "publish_batch"}:
        raise ValueError("该 Listing 动作尚未迁移到提案调度入口")
    ctx = require_action_permission(db, ctx, "listing:write")
    if method == "publish":
        publish_targets(db, ctx.legacy_tenant_id, args[0], args[1] if len(args) > 1 else None)
        review = invoke_review(db, ctx, "review", args[0], scope_key=f"{scope_key or ctx.trace_id}:review")
        if review["decision"] != "approved":
            raise ActionError(400 if review["decision"] == "rejected" else 409,
                              "上架复核未通过：" + "；".join(review["reasons"]))
    if method == "publish_batch":
        return _publish_reviewed_batch(db, ctx, args[0], args[1], scope_key or ctx.trace_id)
    with ListingAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        output = getattr(agent, method)(*args)
    return finalize_listing_output(db, ctx, output, scope_key or ctx.trace_id)


def _publish_reviewed_batch(db, ctx, params, context, scope):
    ids = params.get("listing_ids", context.get("approved_listing_ids", context.get("listing_ids", [])))
    if not isinstance(ids, list) or len(ids) > 50 or any(type(lid) is not int or lid <= 0 for lid in ids):
        raise ActionError(400, "发布 Listing 范围无效")
    approved, blocked = [], []
    for lid in dict.fromkeys(ids):
        try:
            publish_targets(db, ctx.legacy_tenant_id, lid, params.get("shop_id"))
            review = invoke_review(db, ctx, "review", lid, scope_key=f"{scope}:review:{lid}")
            if review["decision"] == "approved":
                approved.append(lid)
            else:
                blocked.append({"listing_id": lid, "reason": "；".join(review["reasons"])})
        except ActionError as exc:
            blocked.append({"listing_id": lid, "reason": str(exc)})
    with ListingAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        output = agent.publish_batch({**params, "listing_ids": approved}, context)
    output["blocked"] += blocked
    return finalize_listing_output(db, ctx, output, scope)


def invoke_ad_drafts(db, ctx, params, context, *, scope_key=None):
    """广告 Agent 只产出草稿提案；此入口绑定当前身份并调度执行器。"""
    ctx = require_action_permission(db, ctx, "finance:write")
    with AdsAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        output = agent.draft_batch(params, context)
    return finalize_ad_drafts(db, ctx, output, scope_key or ctx.trace_id)


def invoke_pricing(db, ctx, method, *args, scope_key=None):
    """定价只生成分析，调度层持久化分析产物；禁止提交财务 Action。"""
    if method not in {"suggest_price", "reprice_batch"}:
        raise ValueError("未迁移的定价分析动作")
    ctx = require_action_permission(db, ctx, "finance:write")
    with PricingAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        output = getattr(agent, method)(*args)
    return finalize_pricing_output(db, ctx, output, scope_key or ctx.trace_id)


def invoke_discovery(db, ctx, method, *args, scope_key=None):
    """同步调度评分分析并保存既有产物；原服务端范围重放原评分。"""
    if method not in {"score_product", "score_batch", "pick_candidates"}:
        raise ValueError("未迁移的选品分析")
    ctx = require_action_permission(db, ctx, "product:write")
    scope = scope_key or ctx.trace_id
    explicit = args[3] if method == "pick_candidates" and len(args) > 3 else None
    if method == "pick_candidates" and explicit is None:
        with DiscoveryAgent(ctx.legacy_tenant_id, context=ctx) as agent:
            return agent.pick_candidates(*args)
    ids = [args[0]] if method == "score_product" else (explicit if method == "pick_candidates" else args[0])
    if not isinstance(ids, list) or len(ids) > 200:
        raise ActionError(400, "评分商品范围无效")
    if any(type(pid) is not int or pid <= 0 for pid in ids):
        raise ActionError(400, "评分商品 ID 必须为正整数")
    if method == "pick_candidates" and len(ids) > 50:
        raise ActionError(400, "显式选品最多 50 个商品")
    ids = list(dict.fromkeys(ids))
    results, pending, errors = [], [], []
    with DiscoveryAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        for pid in ids:
            try:
                saved = recover_discovery_score(db, ctx, pid, scope)
                if saved is None:
                    pending.append(agent.score_product(pid))
                else:
                    results.append(saved)
            except (ActionError, ValueError, TypeError) as exc:
                db.rollback()
                if method == "score_product":
                    raise
                errors.append({"product_id": pid, "error": str(exc)})
        if not errors:
            results.extend(finalize_discovery_scores(db, ctx, pending, scope))
        order = {pid: index for index, pid in enumerate(ids) if isinstance(pid, int)}
        results.sort(key=lambda row: order[row["product_id"]])
        if method == "score_product":
            return results[0]
        status = "blocked" if errors else "success"
        if method == "score_batch":
            return {"results": results, "errors": errors, "business_status": status, "context_patch": {}}
        items = [agent._candidate_item(row) for row in results]
        if any(item is None for item in items):
            raise ActionError(409, "选品商品归属已变化")
        return {"items": items, "picked_product_ids": [row["product_id"] for row in results],
                "context_patch": {}, "errors": errors, "business_status": status}


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
        if self.context is None:
            raise ActionError(403, "选品分析需要可信 Workspace 身份")
        r = invoke_discovery(self.db, self.context, "pick_candidates", 3, 0)
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
        if self.context is None:
            raise ActionError(403, "定价分析持久化需要可信 Workspace 身份")
        r = invoke_pricing(self.db, self.context, "reprice_batch")
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
