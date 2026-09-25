"""合规 Agent：品牌侵权 / 违禁宣称 / 图片风险 / 平台规则四维检测（对应规划第十章）。"""
import re

from ..ai.knowledge import retrieve
from ..models import ComplianceReport, Listing, Product
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

    def _brand_words(self) -> list[str]:
        docs = retrieve(self.db, self.tenant_id, "商标黑名单 品牌 侵权", top_k=2)
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
            obj = self.db.get(Product, ref_id)
            if not obj or obj.tenant_id != self.tenant_id:
                raise ValueError(f"商品 {ref_id} 不存在")
            text = obj.title + " " + str(obj.attrs or {})
            images = obj.images or []
            product_id, listing_id = obj.id, None
        elif target_type == "listing":
            obj = self.db.get(Listing, ref_id)
            if not obj or obj.tenant_id != self.tenant_id:
                raise ValueError(f"Listing {ref_id} 不存在")
            text = " ".join([obj.title, obj.description] + list(obj.bullets or []) + list(obj.keywords or []))
            images = []
            product_id, listing_id = None, obj.id
        else:
            raise ValueError("target_type 必须是 product 或 listing")

        def rule() -> dict:
            return self._scan(text, images)

        system = "你是跨境电商合规审核引擎（广告法/知识产权/平台规则）。只返回 JSON。"
        rules_ctx = retrieve(self.db, self.tenant_id, "违禁词 商标 图片 平台规则", top_k=3)
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
            obj.risk_level = row.risk_level
        self.db.commit()
        out = {"id": row.id, "target_type": target_type, "product_id": product_id,
               "listing_id": listing_id, "risk_level": row.risk_level, "score": row.score,
               "issues": row.issues, "suggestions": row.suggestions, "model": row.model,
               "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S")}
        return out

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
