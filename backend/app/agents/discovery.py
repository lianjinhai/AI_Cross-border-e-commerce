"""商品发现 Agent（市场趋势/关键词扩展/选品评分）与商品标准化 Agent。

§18.3 第 2 步（D46）：读取全部经 Tool 层（Product / Market Tool）；写路径
（趋势刷新）仅输出提案，由中央 Action 执行器调用业务服务。
评分只输出分析产物，由 Orchestrator 保存评分和依据链。
商品标准化仅输出 UPDATE_PRODUCT_CONTENT 提案，由 Orchestrator 调度执行。
"""
import math
from datetime import datetime

from ..services.product_standardization import safe_fields, snapshot
from ..services.trend_candidates import builtin_candidates
from .base import BaseAgent
from .contracts import CONTRACTS

# ---- 读取：全部经 Tool 层（§18.3 第 2 步 / D46）----
# Discovery 与 Product 两个 Agent 共用同一组读取口径，收在模块级函数里（T-53）。

def _tool_product(agent, product_id) -> dict | None:
    """按 id 读商品（Tool 返回 dict；不存在或跨租户都返回 None，判定等价）。"""
    got = agent.tool("product").call("get_products", product_id=product_id)
    rows = got.data if got.ok and isinstance(got.data, list) else []
    return rows[0] if rows else None


def _tool_trend(agent, keyword: str) -> dict | None:
    """按关键词匹配一条趋势（LIKE 语义，取搜索量最高者）；无匹配返回 None。"""
    got = agent.tool("market").call("get_trends", keyword=keyword, limit=1)
    rows = got.data if got.ok and isinstance(got.data, list) else []
    return rows[0] if rows else None


def _tool_count(agent, **filters) -> int:
    got = agent.tool("product").call("count_products", **filters)
    data = got.data if got.ok and isinstance(got.data, dict) else {}
    return int(data.get("count", 0))


def _tool_list(agent, tool: str, method: str, **params) -> list:
    """Tool 返回的清单（id 或行 dict）；失败一律降级为空清单。"""
    got = agent.tool(tool).call(method, **params)
    return got.data if got.ok and isinstance(got.data, list) else []

# 风险词：品牌黑名单兜底 + 违禁宣称（合规细节由 ComplianceAgent 深查）
_RISK_BRANDS = ["apple", "iphone", "nike", "adidas", "disney", "lego", "rolex",
                "louis vuitton", "pokemon", "samsung", "hello kitty"]
_BANNED = ["最", "第一", "顶级", "no.1", "cure", "fda", "杀菌", "防癌", "100% safe"]


def _clamp(v: float, lo=0, hi=100) -> float:
    number = float(v)
    if isinstance(v, bool) or not math.isfinite(number):
        raise ValueError("评分数值必须有限")
    return max(lo, min(hi, round(number, 1)))


class DiscoveryAgent(BaseAgent):
    """市场发现与选品（对应规划第七章）：机会分 = 0.35*需求 + 0.20*(100-竞争) + 0.30*利润 + 0.15*(100-风险)。"""

    name = "discovery"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["market_intelligence"]

    def scan_trends(self) -> dict:
        """仅提出内置趋势刷新；日种子估算不冒充平台真实采集。"""
        cats = _tool_list(self, "product", "get_categories", status="active", limit=4)
        day = datetime.utcnow().strftime("%Y%m%d")
        items = []
        for candidate in builtin_candidates(day, cats):
            got = self.tool("market").call("get_trends", keyword=candidate["keyword"],
                                            platform=candidate["platform"], exact=True, limit=2)
            if not got.ok:
                raise ValueError("趋势依据读取失败")
            if len(got.data) > 1:
                raise ValueError("趋势自然键重复，请先人工整理")
            before = got.data[0] if got.data else None
            items.append({"before": before, "candidate": candidate})
        return {"action_type": "REFRESH_BUILTIN_TRENDS", "target_type": "tenant",
                "target_id": self.tenant_id, "reason": "确定性日种子内置估算，非真实平台采集",
                "payload": {"day": day, "items": items}}

    def expand_keywords(self, keyword: str) -> dict:
        """关键词扩展：规则组合 + LLM 增强。"""
        kw = (keyword or "").strip()

        def rule() -> dict:
            modifiers = ["for women", "for men", "portable", "mini", "2026 new",
                         "wholesale", "hot sale", "premium", "with hook", "travel size"]
            combos = [f"{kw} {m}" for m in modifiers]
            combos += [f"{kw} {c}" for c in ["跨境专供", "工厂直销", "一件代发"]]
            return {"keywords": combos[:12]}

        def prompt() -> str:
            return (f"请为跨境电商关键词「{kw}」扩展 10 个选品搜索关键词。"
                    "返回 JSON: {\"keywords\": [\"...\"]}，覆盖长尾词、场景词、人群词。")

        result, _mode = self.ask_json("expand_keywords", "你是跨境电商选品专家。", prompt(),
                                      fallback=rule, small_task=True)
        return result if result.get("keywords") else rule()

    def _rule_scores(self, p: dict) -> dict:
        """确定性评分（M1 数据飞轮版）；`p` 是 Product Tool 返回的 dict。

        total = 0.30*需求 + 0.15*(100-竞争) + 0.25*利润 + 0.10*(100-风险) + 0.20*经营表现

        经营表现来自真实订单聚合（product_performance，real_only 口径）；
        无真实销售的新品取中性分 50，不惩罚新品。
        """
        attrs = p.get("attrs") or {}
        title_l = (p["title"] + " " + str(attrs).lower())
        trend = _tool_trend(self, p["category"]) if p["category"] else None
        if not trend:
            got = self.tool("market").call("pick_trend")
            trend = got.data if got.ok and isinstance(got.data, dict) else None
        demand = _clamp((40 + trend["growth_30d"] / 2
                         + min(trend["search_volume"], 30000) / 1000) if trend else 50)
        cat_count = _tool_count(self, category=p["category"]) or 1
        competition = _clamp(20 + cat_count * 2.5)
        price = float(attrs.get("sale_price") or 20)
        cost_cny = float(attrs.get("supplier_price") or price * 22)
        margin = 1 - (cost_cny / 7.12) / price if price else 0
        profit = _clamp(margin * 220)
        hits = [b for b in _RISK_BRANDS if b in title_l] + [b for b in _BANNED if b in title_l]
        risk = _clamp(8 + len(hits) * 25)

        # M1：真实经营表现反哺（无数据 -> 50 中性分）
        got = self.tool("product").call("calculate_performance", product_id=p["id"])
        if not got.ok:
            raise ValueError("真实经营表现读取失败")
        perf = got.data
        perf_score = _clamp(perf["performance_score"])
        has_perf = bool(perf["has_data"])

        total = _clamp(0.30 * demand + 0.15 * (100 - competition) + 0.25 * profit
                       + 0.10 * (100 - risk) + 0.20 * perf_score)
        reasons = [
            f"趋势词「{trend['keyword']}」30天增长{trend['growth_30d']}%，需求分 {demand:.0f}" if trend else "无匹配趋势，按默认需求评估",
            f"类目「{p['category']}」在池商品 {cat_count} 个，竞争分 {competition:.0f}",
            f"预估毛利率 {margin * 100:.0f}%，利润分 {profit:.0f}",
            (f"近{perf.get('window_days', 30)}天售出 {perf.get('units_sold', 0)} 件，"
             f"毛利率 {float(perf.get('margin', 0)) * 100:.0f}%，"
             f"退款率 {float(perf.get('refund_rate', 0)) * 100:.0f}%，表现分 {perf_score:.0f}")
            if has_perf else "暂无真实销售数据（新品按中性分 50 评估）",
            ("标题命中风险词: " + ", ".join(hits)) if hits else "标题未命中品牌/违禁词",
        ]
        return {"demand": demand, "competition": competition, "profit": profit,
                "risk": risk, "total": total, "reasons": reasons,
                "performance_score": perf_score, "has_performance_data": has_perf,
                "_evidence": {"trend_id": trend["id"] if trend else None,
                              "category": p["category"], "performance_source": "real_orders",
                              "performance_score": perf_score, "has_performance_data": has_perf,
                              "window_days": perf["window_days"]}}

    def score_product(self, product_id: int) -> dict:
        """仅输出选品分析，由同步调度层保存产物。"""
        p = _tool_product(self, product_id)
        if not p:
            raise ValueError(f"商品 {product_id} 不存在")

        def rule() -> dict:
            return self._rule_scores(p)

        data_hint = f"商品: {p['title']}｜类目: {p['category']}｜属性: {p['attrs']}"
        system = "你是跨境电商选品分析专家。只返回 JSON。"
        prompt = (f"对以下商品做 0-100 选品评分（demand需求/competition竞争/profit利润/risk风险，"
                  f"total=0.35*demand+0.2*(100-competition)+0.3*profit+0.15*(100-risk)，reasons为2-4条中文依据）。"
                  f"返回 JSON: {{\"demand\":0,\"competition\":0,\"profit\":0,\"risk\":0,\"total\":0,\"reasons\":[\"\"]}}。\n{data_hint}")
        result, mode = self.ask_json("score_product", system, prompt, fallback=rule)
        keys = ("demand", "competition", "profit", "risk", "total")
        try:
            valid = (isinstance(result, dict) and all(
                not isinstance(result[k], bool) and isinstance(result[k], (int, float))
                and math.isfinite(result[k]) and 0 <= result[k] <= 100 for k in keys)
                and isinstance(result.get("reasons"), list)
                and all(isinstance(reason, str) for reason in result["reasons"]))
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            result, mode = rule(), "rule"
        record = {"product_id": product_id, **{k: _clamp(result[k]) for k in keys},
                  "reasons": result.get("reasons") or [],
                  "model": "llm" if mode == "llm" else "rule"}
        return {**record, "_score_analysis": record,
                "_score_evidence": result.get("_evidence", {}) if mode != "llm" else {
                    "trend_id": None, "category": p["category"], "performance_source": "not_used"}}

    def score_batch(self, product_ids: list[int]) -> dict:
        results, errors = [], []
        for pid in product_ids:
            try:
                results.append(self.score_product(pid))
            except (ValueError, TypeError) as exc:
                errors.append({"product_id": pid, "error": str(exc)})
        return {"results": results, "errors": errors,
                "business_status": "blocked" if errors else "success"}

    def _candidate_item(self, score: dict, is_explore: bool = False) -> dict | None:
        """只在候选入选时读取商品详情并组装返回行。"""
        product = _tool_product(self, score["product_id"])
        if not product:
            return None
        item = {"product_id": score["product_id"], "title": product["title"],
                "category": product["category"], "demand": score["demand"],
                "competition": score["competition"], "profit": score["profit"],
                "risk": score["risk"], "total": score["total"],
                "reasons": list(score["reasons"] or []), "model": score["model"]}
        if is_explore:
            item["explore_pick"] = True
            item["reasons"].append("探索配额：新品试销名额（避免只推老品）")
        return item

    def pick_candidates(self, limit: int = 3, min_total: float = 60,
                        explore: bool = True, explicit_ids: list[int] | None = None) -> dict:
        """按每个商品最新评分挑选机会商品。

        M1 探索配额（论证修正项）：当 limit >= 2 且存在合格新品时，强制保留 1 个
        新品名额，避免数据飞轮形成"只推卖过的品"的马太效应。配额只给
        「分数 >= 当前中位值 × 0.7」的新品，防止推垃圾新品。
        """
        if explicit_ids is not None:
            # 调用方显式指定商品：直接对这些商品评分并返回，不做全池挑选
            batch = self.score_batch(explicit_ids)
            items = []
            for score in batch["results"]:
                item = self._candidate_item(score)
                if item is None:
                    batch["errors"].append({"product_id": score["product_id"], "error": "商品已失效"})
                else:
                    items.append(item)
            return {"items": items, "context_patch": {},
                    "picked_product_ids": [i["product_id"] for i in items],
                    "_score_batch": batch}

        scores = _tool_list(self, "market", "get_latest_scores", limit=500)
        # 必须校验商品归属与在售状态：评分行按 tenant 过滤，但商品可能属于其他
        # 租户或已停用——缺这一步会把别家商品的标题/类目带进结果（旧实现里的
        # db.get(Product) 正是这个泄漏面）。在售 id 集合走 Product Tool。
        active_ids = set(_tool_list(self, "product", "get_product_ids",
                                    status="active", limit=500))
        # 已评分的商品按分数排序（同分按商品 id，保证顺序可复现）
        ranked = [s for s in sorted(scores, key=lambda r: (-r["total"], r["product_id"]))
                  if s["total"] >= min_total and s["product_id"] in active_ids]

        median = sorted(s["total"] for s in ranked)[len(ranked) // 2] if ranked else 0
        explore_floor = median * 0.7

        items: list[dict] = []
        used: set[int] = set()

        # 1) 优先填常规名额
        reserve = 1 if (explore and limit >= 2 and ranked) else 0
        for s in ranked:
            if len(items) >= limit - reserve:
                break
            item = self._candidate_item(s)
            if item is None:
                continue
            items.append(item)
            used.add(s["product_id"])

        # 2) 探索名额：无真实销售数据的新品中，取分数最高且达标者
        if reserve:
            perf_ids = set(_tool_list(self, "product", "get_sold_product_ids",
                                      min_units=0, limit=500))
            for s in ranked:
                pid = s["product_id"]
                if pid in used or pid in perf_ids:
                    continue
                if s["total"] >= explore_floor:
                    item = self._candidate_item(s, is_explore=True)
                    if item is None:
                        continue
                    items.append(item)
                    used.add(pid)
                    break

        # 注意：不覆盖调用方已指定的 product_ids——用户显式传入时以用户为准，
        # 否则工作流的后续步骤会被"重新选品"结果劫持（本次修复的真实缺陷）。
        patch: dict = {}
        if not explicit_ids:
            patch["product_ids"] = [i["product_id"] for i in items]
        return {"items": items, "context_patch": patch,
                "explore_floor": round(explore_floor, 1) if reserve else None,
                "picked_product_ids": [i["product_id"] for i in items]}


class ProductAgent(BaseAgent):
    """商品标准化（对应规划第八章）：类目映射 / 属性抽取 / 去重指纹。"""

    name = "product"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["product_intelligence"]

    _CATEGORY_MAP = [
        ("家居", ["home", "storage", "organizer", "lamp", "light", "cushion", "收纳", "置物"]),
        ("3C配件", ["phone", "charger", "cable", "earbud", "case", "holder", "手机", "充电", "耳机"]),
        ("宠物用品", ["pet", "dog", "cat", "grooming", "狗", "猫", "宠物"]),
        ("户外运动", ["camping", "yoga", "outdoor", "fitness", "sport", "露营", "瑜伽", "户外"]),
        ("美妆工具", ["makeup", "beauty", "nail", "hair clip", "美容", "化妆", "美妆"]),
        ("母婴用品", ["baby", "infant", "bib", "feeding", "婴儿", "宝宝", "母婴"]),
        ("厨房用品", ["kitchen", "cook", "bottle", "cutlery", "厨房", "餐具"]),
        ("服饰配件", ["bag", "hat", "scarf", "belt", "socks", "包", "帽", "围巾"]),
    ]

    @classmethod
    def map_category(cls, title: str) -> str:
        t = title.lower()
        for cat, words in cls._CATEGORY_MAP:
            if any(w in t for w in words):
                return cat
        return "家居"

    def standardize(self, product_id: int) -> dict:
        p = _tool_product(self, product_id)
        if not p:
            raise ValueError(f"商品 {product_id} 不存在")
        category = self.map_category(p["title"])
        system = "你是电商商品数据标准化引擎。只返回 JSON。"
        prompt = (f"标准化商品「{p['title']}」，返回 JSON attrs 仅补全 weight_kg/material/color。")
        result, mode = self.ask_json("standardize", system, prompt,
                                     fallback=lambda: {"attrs": {}}, small_task=True)
        fields = safe_fields(p, category, result.get("attrs") if isinstance(result, dict) else None)
        got = self.tool("product").call("find_duplicate", dedupe_hash=fields["dedupe_hash"],
                                        exclude_id=product_id)
        if not got.ok:
            raise ValueError("商品查重读取失败")
        return {"product_id": product_id, "dedupe_hash": fields["dedupe_hash"],
                "_action_proposal": {
            "action_type": "UPDATE_PRODUCT_CONTENT", "target_type": "product",
            "target_id": product_id, "reason": "安全标准化商品类目、重量、材质和颜色",
            "payload": {"before": snapshot(p), **fields}},
                # 建议来源如实落进 Action 证据：离线/故障降级时是 rule，不是「AI 生成」。
                "_action_proposal_evidence": {"source": "llm" if mode == "llm" else "rule",
                                              "model_mode": mode}}

    def standardize_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        ids = params.get("product_ids", context.get("product_ids"))
        if ids is None:
            ids = _tool_list(self, "product", "get_product_ids",
                             status="active", limit=200)
        proposals, errors = [], []
        for pid in ids[:200]:
            try:
                proposals.append(self.standardize(int(pid)))
            except (ValueError, TypeError) as exc:
                errors.append({"product_id": pid, "error": str(exc)})
        return {"proposals": proposals, "errors": errors}
