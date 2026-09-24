"""商品发现 Agent（市场趋势/关键词扩展/选品评分）与商品标准化 Agent。"""
import hashlib
import random
import re
from datetime import datetime

from sqlalchemy import func

from ..models import MarketTrend, Product, ProductScore
from .base import BaseAgent

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

    def scan_trends(self) -> list[dict]:
        """刷新市场趋势：基于关键词池 + 本店类目 upsert 12 条。"""
        cats = [r[0] for r in self.db.query(Product.category).filter(
            Product.tenant_id == self.tenant_id, Product.status == "active").distinct().all()]
        pool = list(_TREND_POOL) + [(f"{c} wholesale", "1688") for c in cats[:4]]
        rng = random.Random(datetime.utcnow().strftime("%Y%m%d"))  # 当日确定性
        out = []
        for kw, plat in pool[:12]:
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

    def _rule_scores(self, p: Product) -> dict:
        """确定性评分（M1 数据飞轮版）：

        total = 0.30*需求 + 0.15*(100-竞争) + 0.25*利润 + 0.10*(100-风险) + 0.20*经营表现

        经营表现来自真实订单聚合（product_performance，real_only 口径）；
        无真实销售的新品取中性分 50，不惩罚新品。
        """
        from ..services.product_performance import get_performance

        title_l = (p.title + " " + str(p.attrs or {}).lower())
        trend = None
        if p.category:
            trend = (self.db.query(MarketTrend)
                     .filter(MarketTrend.tenant_id == self.tenant_id,
                             MarketTrend.keyword.contains(p.category))
                     .first())
        if not trend:
            trend = (self.db.query(MarketTrend).filter(MarketTrend.tenant_id == self.tenant_id)
                     .order_by(func.random()).first())
        demand = _clamp((40 + trend.growth_30d / 2 + min(trend.search_volume, 30000) / 1000) if trend else 50)
        cat_count = (self.db.query(func.count(Product.id))
                     .filter(Product.tenant_id == self.tenant_id, Product.category == p.category).scalar() or 1)
        competition = _clamp(20 + cat_count * 2.5)
        price = float((p.attrs or {}).get("sale_price") or 20)
        cost_cny = float((p.attrs or {}).get("supplier_price") or price * 22)
        margin = 1 - (cost_cny / 7.12) / price if price else 0
        profit = _clamp(margin * 220)
        hits = [b for b in _RISK_BRANDS if b in title_l] + [b for b in _BANNED if b in title_l]
        risk = _clamp(8 + len(hits) * 25)

        # M1：真实经营表现反哺（无数据 -> 50 中性分）
        try:
            perf = get_performance(self.db, self.tenant_id, p.id)
            perf_score = float(perf.get("performance_score", 50))
            has_perf = bool(perf.get("has_data"))
        except Exception:
            perf, perf_score, has_perf = {}, 50.0, False

        total = _clamp(0.30 * demand + 0.15 * (100 - competition) + 0.25 * profit
                       + 0.10 * (100 - risk) + 0.20 * perf_score)
        reasons = [
            f"趋势词「{trend.keyword}」30天增长{trend.growth_30d}%，需求分 {demand:.0f}" if trend else "无匹配趋势，按默认需求评估",
            f"类目「{p.category}」在池商品 {cat_count} 个，竞争分 {competition:.0f}",
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
        p = self.db.get(Product, product_id)
        if not p or p.tenant_id != self.tenant_id:
            raise ValueError(f"商品 {product_id} 不存在")

        def rule() -> dict:
            return self._rule_scores(p)

        data_hint = f"商品: {p.title}｜类目: {p.category}｜属性: {p.attrs}"
        system = "你是跨境电商选品分析专家。只返回 JSON。"
        prompt = (f"对以下商品做 0-100 选品评分（demand需求/competition竞争/profit利润/risk风险，"
                  f"total=0.35*demand+0.2*(100-competition)+0.3*profit+0.15*(100-risk)，reasons为2-4条中文依据）。"
                  f"返回 JSON: {{\"demand\":0,\"competition\":0,\"profit\":0,\"risk\":0,\"total\":0,\"reasons\":[\"\"]}}。\n{data_hint}")
        result, mode = self.ask_json("score_product", system, prompt, fallback=rule)
        if not all(k in result for k in ("demand", "competition", "profit", "risk", "total")):
            result, mode = rule(), "rule"
        row = ProductScore(
            tenant_id=self.tenant_id, product_id=product_id,
            demand=_clamp(result["demand"]), competition=_clamp(result["competition"]),
            profit=_clamp(result["profit"]), risk=_clamp(result["risk"]),
            total=_clamp(result["total"]),
            reasons=result.get("reasons") or [], model="llm" if mode == "llm" else "rule",
        )
        self.db.add(row)
        self.db.commit()
        # M6：记录决策依据链（可追溯用了哪些数据）
        from ..models import MarketTrend, ProductPerformance

        trend_ref = (self.db.query(MarketTrend)
                     .filter(MarketTrend.tenant_id == self.tenant_id,
                             MarketTrend.keyword.contains(p.category or ""))
                     .first())
        perf_row = (self.db.query(ProductPerformance)
                    .filter(ProductPerformance.tenant_id == self.tenant_id,
                            ProductPerformance.product_id == product_id)
                    .order_by(ProductPerformance.computed_at.desc()).first())
        self.record_decision(
            action="score_product", subject_type="product", subject_id=product_id,
            decision={"total": row.total, "demand": row.demand, "competition": row.competition,
                      "profit": row.profit, "risk": row.risk},
            evidence={"trend_id": trend_ref.id if trend_ref else None,
                      "performance_id": perf_row.id if perf_row else None,
                      "performance_score": result.get("performance_score"),
                      "has_performance_data": result.get("has_performance_data"),
                      "category": p.category,
                      "reasons": row.reasons},
            model=row.model)
        return {"product_id": product_id, "demand": row.demand, "competition": row.competition,
                "profit": row.profit, "risk": row.risk, "total": row.total,
                "reasons": row.reasons, "model": row.model, "score_id": row.id}

    def score_batch(self, product_ids: list[int]) -> dict:
        return {"results": [self.score_product(pid) for pid in product_ids]}

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
                p = self.db.get(Product, int(pid))
                if not p:
                    continue
                items.append({"product_id": int(pid), "title": p.title, "category": p.category,
                              "demand": s["demand"], "competition": s["competition"],
                              "profit": s["profit"], "risk": s["risk"], "total": s["total"],
                              "reasons": s["reasons"], "model": s["model"]})
            return {"items": items, "context_patch": {},
                    "picked_product_ids": [i["product_id"] for i in items]}

        latest = {}
        rows = (self.db.query(ProductScore)
                .filter(ProductScore.tenant_id == self.tenant_id)
                .order_by(ProductScore.product_id, ProductScore.created_at.desc()).all())
        for r in rows:
            latest.setdefault(r.product_id, r)
        # 已评分的商品按分数排序
        ranked = []
        for pid, s in sorted(latest.items(), key=lambda kv: -kv[1].total):
            if s.total < min_total:
                continue
            p = self.db.get(Product, pid)
            # 必须校验归属：ProductScore 行按 tenant 过滤，但 db.get(Product)
            # 是按主键直取，缺这一步会把其他租户的商品标题/类目带进结果
            # （实测可复现：给 tenant=999 的商品写一条 tenant=1 的评分即泄漏）。
            if not p or p.tenant_id != self.tenant_id or p.status != "active":
                continue
            ranked.append((pid, s, p))

        median = sorted(s.total for _, s, _ in ranked)[len(ranked) // 2] if ranked else 0
        explore_floor = median * 0.7

        items: list[dict] = []
        used: set[int] = set()

        def _item(pid, s, p, is_explore=False):
            d = {"product_id": pid, "title": p.title, "category": p.category,
                 "demand": s.demand, "competition": s.competition, "profit": s.profit,
                 "risk": s.risk, "total": s.total, "reasons": s.reasons, "model": s.model}
            if is_explore:
                d["explore_pick"] = True
                d["reasons"] = list(s.reasons) + ["探索配额：新品试销名额（避免只推老品）"]
            return d

        # 1) 优先填常规名额
        reserve = 1 if (explore and limit >= 2 and ranked) else 0
        for pid, s, p in ranked:
            if len(items) >= limit - reserve:
                break
            items.append(_item(pid, s, p))
            used.add(pid)

        # 2) 探索名额：无真实销售数据的新品中，取分数最高且达标者
        if reserve:
            from ..models import ProductPerformance
            perf_ids = {r[0] for r in self.db.query(ProductPerformance.product_id)
                        .filter(ProductPerformance.tenant_id == self.tenant_id,
                                ProductPerformance.units_sold > 0).all()}
            for pid, s, p in ranked:
                if pid in used or pid in perf_ids:
                    continue
                if s.total >= explore_floor:
                    items.append(_item(pid, s, p, is_explore=True))
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
            dup = (self.db.query(Product)
                   .filter(Product.tenant_id == self.tenant_id, Product.dedupe_hash == digest,
                           Product.id != product_id, Product.status != "deleted")
                   .first())
            return {"category": category, "attrs": attrs, "dedupe_hash": digest,
                    "is_duplicate": bool(dup), "duplicate_of": dup.id if dup else 0}

        system = "你是电商商品数据标准化引擎。只返回 JSON。"
        prompt = (f"标准化商品「{p.title}」，attrs 原文: {p.attrs}。"
                  "返回 JSON: {\"category\":\"八大类目之一\",\"attrs\":{...原字段并补全 weight_kg/material/color},"
                  "\"dedupe_hash\":\"16位指纹\"}。")
        result, _mode = self.ask_json("standardize", system, prompt, fallback=rule, small_task=True)
        if not result.get("category") or not result.get("dedupe_hash"):
            result = rule()
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
            ids = [r[0] for r in self.db.query(Product.id)
                   .filter(Product.tenant_id == self.tenant_id, Product.status == "active").all()]
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
