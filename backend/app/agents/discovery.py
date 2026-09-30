"""商品发现 Agent（市场趋势/关键词扩展/选品评分）与商品标准化 Agent。

§18.3 第 2 步（D46）：读取全部经 Tool 层（Product / Market Tool）；写路径
（趋势 upsert、评分落库、标准化回写）保留 ORM 访问并集中标注，属第 3 步
（Action 层）欠账。
"""
import hashlib
import random
import re
from datetime import datetime

from ..models import MarketTrend, Product, ProductScore
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

_TREND_POOL = [
    ("led strip lights", "google"), ("pet grooming gloves", "amazon"), ("car phone holder", "amazon"),
    ("yoga mat thick", "google"), ("reusable makeup pads", "shopee"), ("baby feeding bibs", "amazon"),
    ("kitchen drawer organizer", "google"), (" camping lantern rechargeable", "amazon"),
    ("hair claw clips", "tiktok"), ("smart water bottle", "google"), ("dog cooling mat", "shopee"),
    ("wireless earbuds case", "shopee"),
]


def _clamp(v: float, lo=0, hi=100) -> float:
    return max(lo, min(hi, round(float(v), 1)))


class DiscoveryAgent(BaseAgent):
    """市场发现与选品（对应规划第七章）：机会分 = 0.35*需求 + 0.20*(100-竞争) + 0.30*利润 + 0.15*(100-风险)。"""

    name = "discovery"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["market_intelligence"]

    def scan_trends(self) -> list[dict]:
        """刷新市场趋势：基于关键词池 + 本店类目 upsert 12 条。"""
        cats = _tool_list(self, "product", "get_categories", status="active", limit=4)
        pool = list(_TREND_POOL) + [(f"{c} wholesale", "1688") for c in cats]
        rng = random.Random(datetime.utcnow().strftime("%Y%m%d"))  # 当日确定性
        out = []
        for kw, plat in pool[:12]:
            # 写路径（§18.3 第 3 步欠账）：upsert 需要 ORM 行对象做「有则更新、
            # 无则新建」，保留这 1 处直连查询并标注；读侧（类目）已走 Tool。
            row = (self.db.query(MarketTrend)
                   .filter(MarketTrend.tenant_id == self.tenant_id,
                           MarketTrend.keyword == kw.strip(), MarketTrend.platform == plat)
                   .first())
            vol = rng.randint(800, 50000)
            growth = round(rng.uniform(-15, 180), 1)
            comp = rng.randint(20, 90)
            if not row:
                row = MarketTrend(tenant_id=self.tenant_id, keyword=kw.strip(), platform=plat)
                self.db.add(row)
            # 不覆盖真实来源数据（api/csv）：内置池只补空缺，避免污染真实趋势（红线 3）
            if getattr(row, "source", "builtin") in ("api", "csv"):
                out.append(row)
                continue
            row.search_volume, row.growth_30d, row.competition = vol, growth, comp
            row.note = "增长率显著" if growth > 60 else ("竞争激烈" if comp > 75 else "平稳")
            row.source = "builtin"
            out.append(row)
        self.db.commit()
        return [{"id": t.id, "keyword": t.keyword, "platform": t.platform,
                 "search_volume": t.search_volume, "growth_30d": t.growth_30d,
                 "competition": t.competition, "note": t.note,
                 "source": getattr(t, "source", "builtin")} for t in out]

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
        from ..services.product_performance import get_performance

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
        try:
            perf = get_performance(self.db, self.tenant_id, p["id"])
            perf_score = float(perf.get("performance_score", 50))
            has_perf = bool(perf.get("has_data"))
        except Exception:
            perf, perf_score, has_perf = {}, 50.0, False

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
                "performance_score": perf_score, "has_performance_data": has_perf}

    def score_product(self, product_id: int) -> dict:
        """选品评分并落库 ProductScore。"""
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
        if not all(k in result for k in ("demand", "competition", "profit", "risk", "total")):
            result, mode = rule(), "rule"
        # 写路径（§18.3 第 3 步欠账）：评分落库仍需 ORM 写入，保留并标注。
        row = ProductScore(
            tenant_id=self.tenant_id, product_id=product_id,
            demand=_clamp(result["demand"]), competition=_clamp(result["competition"]),
            profit=_clamp(result["profit"]), risk=_clamp(result["risk"]),
            total=_clamp(result["total"]),
            reasons=result.get("reasons") or [], model="llm" if mode == "llm" else "rule",
        )
        self.db.add(row)
        self.db.commit()
        # M6：记录决策依据链（可追溯用了哪些数据）——引用 id 走 Tool 读取。
        trend_ref = _tool_trend(self, p["category"] or "")
        perf_got = self.tool("product").call("get_latest_performance", product_id=product_id)
        perf_id = (perf_got.data.get("id")
                   if perf_got.ok and isinstance(perf_got.data, dict) else None)
        self.record_decision(
            action="score_product", subject_type="product", subject_id=product_id,
            decision={"total": row.total, "demand": row.demand, "competition": row.competition,
                      "profit": row.profit, "risk": row.risk},
            evidence={"trend_id": trend_ref["id"] if trend_ref else None,
                      "performance_id": perf_id,
                      "performance_score": result.get("performance_score"),
                      "has_performance_data": result.get("has_performance_data"),
                      "category": p["category"],
                      "reasons": row.reasons},
            model=row.model)
        return {"product_id": product_id, "demand": row.demand, "competition": row.competition,
                "profit": row.profit, "risk": row.risk, "total": row.total,
                "reasons": row.reasons, "model": row.model, "score_id": row.id}

    def score_batch(self, product_ids: list[int]) -> dict:
        return {"results": [self.score_product(pid) for pid in product_ids]}

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
        if explicit_ids:
            # 调用方显式指定商品：直接对这些商品评分并返回，不做全池挑选
            items = []
            for pid in explicit_ids[:50]:
                try:
                    s = self.score_product(int(pid))
                except Exception:
                    continue
                p = _tool_product(self, int(pid))
                if not p:
                    continue
                items.append({"product_id": int(pid), "title": p["title"], "category": p["category"],
                              "demand": s["demand"], "competition": s["competition"],
                              "profit": s["profit"], "risk": s["risk"], "total": s["total"],
                              "reasons": s["reasons"], "model": s["model"]})
            return {"items": items, "context_patch": {},
                    "picked_product_ids": [i["product_id"] for i in items]}

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
        # 写路径（§18.3 第 3 步欠账）：标准化要回写 category / attrs / dedupe_hash，
        # 需要 ORM 行对象，因此保留这 1 处 get 并标注；查重读取走 Tool。
        p = self.db.get(Product, product_id)
        if not p or p.tenant_id != self.tenant_id:
            raise ValueError(f"商品 {product_id} 不存在")

        def rule() -> dict:
            title = p.title
            attrs = dict(p.attrs or {})
            category = self.map_category(title) or attrs.get("category", "")
            weight = attrs.get("weight_kg")
            if not weight:
                m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|千克)", title.lower())
                weight = float(m.group(1)) if m else 0.3
            attrs.update({"weight_kg": float(weight),
                          "material": attrs.get("material", "PP"),
                          "color": attrs.get("color", "多色")})
            norm = re.sub(r"\s+", "", title.lower())[:20]
            digest = hashlib.sha256(f"{category}|{norm}|{attrs['material']}|{attrs['color']}"
                                    .encode()).hexdigest()[:16]
            got = self.tool("product").call("find_duplicate", dedupe_hash=digest,
                                            exclude_id=product_id)
            dup_id = (got.data.get("duplicate_id")
                      if got.ok and isinstance(got.data, dict) else None)
            return {"category": category, "attrs": attrs, "dedupe_hash": digest,
                    "is_duplicate": bool(dup_id), "duplicate_of": dup_id or 0}

        system = "你是电商商品数据标准化引擎。只返回 JSON。"
        prompt = (f"标准化商品「{p.title}」，attrs 原文: {p.attrs}。"
                  "返回 JSON: {\"category\":\"八大类目之一\",\"attrs\":{...原字段并补全 weight_kg/material/color},"
                  "\"dedupe_hash\":\"16位指纹\"}。")
        result, _mode = self.ask_json("standardize", system, prompt, fallback=rule, small_task=True)
        if not result.get("category") or not result.get("dedupe_hash"):
            result = rule()
        # 写路径（§18.3 第 3 步欠账）：标准化结果回写落库。
        p.category = result["category"]
        p.attrs = result.get("attrs") or p.attrs
        p.dedupe_hash = result["dedupe_hash"]
        p.updated_at = datetime.utcnow()
        self.db.commit()
        return {"product_id": product_id, "category": p.category, "attrs": p.attrs,
                "dedupe_hash": p.dedupe_hash, "is_duplicate": result.get("is_duplicate", False),
                "duplicate_of": result.get("duplicate_of", 0)}

    def standardize_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        ids = params.get("product_ids") or context.get("product_ids") or []
        if not ids:
            ids = _tool_list(self, "product", "get_product_ids",
                             status="active", limit=200)
        standardized, duplicates = [], []
        for pid in ids[:200]:
            try:
                r = self.standardize(int(pid))
                (duplicates if r.get("is_duplicate") else standardized).append(pid)
            except Exception:
                continue
        return {"standardized": standardized, "duplicates": duplicates,
                "context_patch": {"product_ids": standardized,
                                  "duplicate_product_ids": duplicates}}
