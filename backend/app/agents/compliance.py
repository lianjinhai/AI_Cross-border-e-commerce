"""合规 Agent：品牌侵权 / 违禁宣称 / 图片风险 / 平台规则四维检测（对应规划第十章）。"""
import re

from ..models import ComplianceReport, Listing
from .base import BaseAgent
from .contracts import CONTRACTS

_BUILTIN_BRANDS = ["apple", "iphone", "ipad", "samsung", "xiaomi", "nike", "adidas", "puma",
                   "disney", "marvel", "lego", "barbie", "hello kitty", "pokemon", "rolex",
                   "louis vuitton", "gucci", "chanel", "cartier", "dyson", "anker"]
_BUILTIN_CLAIMS = ["最好", "第一品牌", "顶级", "no.1", "#1", "cure", "fda approved",
                   "杀菌", "防癌", "治疗", "100% safe", "100% safe", "medical"]
_WATERMARK_HINTS = ["watermark", "logo_", "_logo", "shuiyin"]


class ComplianceAgent(BaseAgent):
    name = "compliance"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["risk_compliance"]

    def _knowledge(self, query: str, top_k: int) -> list[dict]:
        """知识检索统一走 Knowledge Tool（§18.3 第 2 步）——每次读取可审计、可限流。

        为什么不像以前那样直接调 `ai.knowledge.retrieve`：检索结果会进入 Agent 的
        推理依据，属于「读了什么数据」的一部分；绕开 Tool 层则 Trace 里查不到依据
        （§19 验收项 5）。检索失败不抛异常，降级为空列表（与旧实现一致）。
        """
        result = self.tool("knowledge").call("search", query=query, top_k=top_k)
        return result.data if result.ok and isinstance(result.data, list) else []

    def _brand_words(self) -> list[str]:
        docs = self._knowledge("商标黑名单 品牌 侵权", top_k=2)
        words = set(w.lower() for w in _BUILTIN_BRANDS)
        for d in docs:
            words |= set(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9 ]{1,20}", d["content"])
                         if w.strip().lower() in _BUILTIN_BRANDS or len(w.strip()) > 3)
        return sorted(words)

    def _scan(self, text: str, images: list[str]) -> dict:
        t = (text or "").lower()
        issues: list[dict] = []
        for brand in self._brand_words():
            if brand in t:
                issues.append({"type": "brand", "level": "high",
                               "detail": f"文本命中品牌词「{brand}」，存在商标侵权风险",
                               "evidence": brand})
        for claim in _BUILTIN_CLAIMS:
            if claim in t:
                issues.append({"type": "claim", "level": "mid",
                               "detail": f"命中违禁宣称「{claim}」，违反广告法/平台规则",
                               "evidence": claim})
        if not images:
            issues.append({"type": "image", "level": "mid",
                           "detail": "缺少商品图片，无法核验素材合规", "evidence": "images=[]"})
        else:
            for url in images:
                if any(h in url.lower() for h in _WATERMARK_HINTS):
                    issues.append({"type": "image", "level": "mid",
                                   "detail": f"图片疑似带水印/第三方LOGO: {url[:80]}", "evidence": url[:120]})
        deduction = sum(50 if i["level"] == "high" else 15 for i in issues)
        score = max(0.0, 100 - deduction)
        risk = "high" if score < 60 else ("mid" if score < 85 else "low")
        suggestions = {
            "brand": "删除该品牌词，改用通用描述（如 smartphone case 而非 iPhone case）",
            "claim": "删除绝对化/违禁宣称，改为客观功能描述",
            "image": "更换为自有拍摄或已授权图片，避免水印与第三方LOGO",
        }
        return {"issues": issues, "score": score, "risk_level": risk,
                "suggestions": sorted({suggestions[i["type"]] for i in issues})}

    def check(self, target_type: str, ref_id: int) -> dict:
        """检测并生成报告。target_type: product / listing。"""
        if target_type == "product":
            # 读取走 Product Tool（§18.3 第 2 步）。跨租户与不存在都返回空列表，
            # 与旧实现「取不到 或 tenant_id 不符」的判定等价，且不泄露他家数据。
            got = self.tool("product").call("get_products", product_id=ref_id)
            rows = got.data if got.ok and isinstance(got.data, list) else []
            if not rows:
                raise ValueError(f"商品 {ref_id} 不存在")
            obj = rows[0]
            text = obj["title"] + " " + str(obj["attrs"] or {})
            images = obj["images"] or []
            product_id, listing_id = obj["id"], None
        elif target_type == "listing":
            got = self.tool("listing").call("get_listings", listing_id=ref_id)
            rows = got.data if got.ok and isinstance(got.data, list) else []
            if not rows:
                raise ValueError(f"Listing {ref_id} 不存在")
            obj = rows[0]
            text = " ".join([obj["title"], obj["description"]] + list(obj["bullets"] or []) + list(obj["keywords"] or []))
            images = []
            product_id, listing_id = None, obj["id"]
        else:
            raise ValueError("target_type 必须是 product 或 listing")

        def rule() -> dict:
            return self._scan(text, images)

        system = "你是跨境电商合规审核引擎（广告法/知识产权/平台规则）。只返回 JSON。"
        rules_ctx = self._knowledge("违禁词 商标 图片 平台规则", top_k=3)
        prompt = (f"审核以下{target_type}内容，输出问题列表与合规分。"
                  f"参考平台规则: {[d['title'] for d in rules_ctx]}。"
                  "返回 JSON: {\"issues\":[{\"type\":\"brand|claim|image|platform\",\"level\":\"high|mid|low\","
                  "\"detail\":\"中文\",\"evidence\":\"\"}],\"score\":0,\"risk_level\":\"low|mid|high\","
                  "\"suggestions\":[\"中文建议\"]}。\n内容: " + text[:1500])
        result, mode = self.ask_json("check", system, prompt, fallback=rule)
        if not isinstance(result.get("issues"), list) or "risk_level" not in result:
            result, mode = rule(), "rule"
        row = ComplianceReport(
            tenant_id=self.tenant_id, target_type=target_type,
            product_id=product_id, listing_id=listing_id,
            risk_level=result["risk_level"], score=float(result.get("score", 100)),
            issues=result["issues"], suggestions=result.get("suggestions") or [],
            model="llm" if mode == "llm" else "rule",
        )
        self.db.add(row)
        if target_type == "listing":
            self._sync_listing_risk(listing_id, row.risk_level)
        self.db.commit()
        out = {"id": row.id, "target_type": target_type, "product_id": product_id,
               "listing_id": listing_id, "risk_level": row.risk_level, "score": row.score,
               "issues": row.issues, "suggestions": row.suggestions, "model": row.model,
               "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S")}
        return out

    def _sync_listing_risk(self, listing_id: int, risk_level: str) -> None:
        """把合规结论回写到 `Listing.risk_level`（冗余副本，发布门禁读的是它）。

        §18.3 第 3 步（Action 层）的欠账：这仍是一次 Agent 直改业务数据（§9.1），
        不在本步（读取路径迁移）范围内。保留的理由：发布门禁当前读
        `Listing.risk_level` 而非最新 ComplianceReport，直接删掉会让「高风险
        Listing 可发布」。集中在这一处，是为了第 3 步改由 Action 执行时只有一处要动。
        """
        obj = self.db.get(Listing, listing_id)
        if obj and obj.tenant_id == self.tenant_id:
            obj.risk_level = risk_level

    def check_product(self, product_id: int) -> dict:
        return self.check("product", product_id)

    def check_listing(self, listing_id: int) -> dict:
        return self.check("listing", listing_id)

    def check_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        items = params.get("items")
        if not items:
            items = ([{"target_type": "product", "ref_id": pid}
                      for pid in (params.get("product_ids") or context.get("product_ids") or [])] +
                     [{"target_type": "listing", "ref_id": lid}
                      for lid in (params.get("listing_ids") or context.get("listing_ids") or [])])
        reports, risk_high, blocked_products, blocked_listings = [], [], [], []
        for it in items[:100]:
            try:
                r = self.check(it["target_type"], int(it["ref_id"]))
                reports.append(r)
                if r["risk_level"] == "high":
                    risk_high.append(it["ref_id"])
                    (blocked_products if it["target_type"] == "product" else blocked_listings).append(it["ref_id"])
            except Exception:
                continue
        return {"reports": reports, "context_patch": {"risk_high": risk_high,
                "blocked_product_ids": blocked_products,
                "blocked_listing_ids": blocked_listings}}
