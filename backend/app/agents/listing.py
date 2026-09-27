"""Listing Agent：AI 生成多语言商品文案 / 优化 / 一键发布（对应规划第五章 4.5 节、第九章）。

M2 知识增强：生成前注入知识库检索结果与平台规则包约束；生成后规则引擎自检，
违禁词/超长时带修正提示重试一次（上限 1 次）；仍违规则降级模板并标记待复核。

§18.3 第 2 步：读取全部经 Tool 层；写路径集中标注，属第 3 步（Action 层）欠账。
"""
from datetime import datetime

from ..models import Listing
from ..services.platform_rules import validate_listing_fields
from .base import BaseAgent
from .contracts import CONTRACTS

_PLATFORM_SUFFIX = {"shopee": "Shopee Choice", "amazon": "Amazon Prime", "shopify": "Trending Now",
                    "ebay": "Fast Ship", "temu": "Temu Hot", "tiktok": "TikTok Viral"}


class ListingAgent(BaseAgent):
    name = "listing"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["listing"]

    # ---------- 文案生成 ----------
    @staticmethod
    def _sanitize(text: str, banned: list[str]) -> str:
        """清洗文本中的违禁词（模板生成同样必须过规则，避免脏标题带入 Listing）。"""
        out = str(text or "")
        for w in banned:
            if not w:
                continue
            # 大小写不敏感替换，保留可读性（用空格替代，避免词粘连）
            import re

            out = re.sub(re.escape(str(w)), " ", out, flags=re.I)
        return re.sub(r"\s{2,}", " ", out).strip()

    def _fallback_copy(self, p: dict, platform: str, language: str,
                       banned: list[str] | None = None) -> dict:
        attrs = p["attrs"] or {}
        base = str(attrs.get("title_en") or p["title"])
        if banned:
            base = self._sanitize(base, banned) or base
        raw_title = p["title"]
        if banned:
            raw_title = self._sanitize(raw_title, banned) or raw_title
        material = str(attrs.get("material") or "premium")
        color = str(attrs.get("color") or "classic")
        scene = str(attrs.get("scene") or "daily use")
        suffix = _PLATFORM_SUFFIX.get(platform, "Hot Sale")
        if language.startswith("zh"):
            title = f"{raw_title} {material}材质 {color}色 跨境爆款"
            desc = (f"{raw_title}，采用{material}材质，{color}配色，适合{scene}。"
                    "工厂直供、品质保障，支持一件代发，跨境卖家首选。")
            bullets = ["工厂直供 品质保障", "优选材质 经久耐用", "多场景适用", "支持一件代发", "7天无理由退换"]
            keywords = [p["category"], raw_title, f"{raw_title}批发",
                        f"{color} {p['category']}"]
        else:
            title = f"{base} {material.title()} {color.title()} for {scene} | {suffix} 2026"
            desc = (f"Upgrade your {scene} with this {color} {base}. Made of durable {material}, "
                    f"it combines practical design with reliable quality. Perfect for {scene} and everyday use. "
                    f"Shipped directly from factory with quality inspection before dispatch.")
            bullets = ["Factory direct with strict quality control",
                       f"Durable {material} build, {color} finish",
                       f"Ideal for {scene} and gifting",
                       "Compact, portable and easy to clean",
                       "24/7 customer support & easy returns"]
            keywords = [base, f"{base} {color}", f"{base} {material}",
                        f"best {p['category']}", f"{p['category']} 2026",
                        f"{base} for {scene}"]
        while len(keywords) < 12:
            keywords.append(f"{base} {len(keywords)}")
        return {"title": title[:220], "description": desc, "bullets": bullets[:5],
                "keywords": keywords[:15]}

    @staticmethod
    def _self_check(copy: dict, title_max: int, banned: list[str]) -> list[str]:
        """生成后自检（纯规则引擎，离线可跑）：返回违规项清单，空=合规。"""
        violations: list[str] = []
        title = str(copy.get("title") or "")
        if len(title) > title_max:
            violations.append(f"标题 {len(title)} 字符超出上限 {title_max}")
        text = " ".join([title, str(copy.get("description") or ""),
                         " ".join(copy.get("bullets") or []),
                         " ".join(copy.get("keywords") or [])]).lower()
        for w in banned:
            if w and str(w).lower() in text:
                violations.append(f"命中违禁词「{w}」")
        return violations

    # ---- 读取：全部经 Tool 层（§18.3 第 2 步）----
    def _optional_product(self, product_id) -> dict | None:
        """读商品走 Product Tool；查不到返回 None（发布校验在商品缺失时跳过）。"""
        got = self.tool("product").call("get_products", product_id=product_id)
        rows = got.data if got.ok and isinstance(got.data, list) else []
        return rows[0] if rows else None

    def _product(self, product_id) -> dict:
        """读商品走 Product Tool：跨租户与不存在都返回空列表，判定等价。"""
        p = self._optional_product(product_id)
        if p is None:
            raise ValueError(f"商品 {product_id} 不存在")
        return p

    def _listing(self, listing_id: int) -> dict:
        """读 Listing 走 Listing Tool（跨租户与不存在判定等价于旧实现）。"""
        got = self.tool("listing").call("get_listings", listing_id=listing_id)
        rows = got.data if got.ok and isinstance(got.data, list) else []
        if not rows:
            raise ValueError(f"Listing {listing_id} 不存在")
        return rows[0]

    def _knowledge(self, query: str, top_k: int = 3) -> list[dict]:
        """知识检索走 Knowledge Tool（可审计）；失败降级为空列表。"""
        got = self.tool("knowledge").call("search", query=query, top_k=top_k)
        return got.data if got.ok and isinstance(got.data, list) else []

    def _rule_pack(self, platform: str) -> dict:
        """平台规则包走 Compliance Tool（与 compliance / listing_review 同一口径）。

        取不到时返回空规则包——与旧实现「未知平台得到 rules={}」等价，判定集合
        同样为空，不会因一次读取失败放行脏文案。
        """
        got = self.tool("compliance").call("get_platform_rules", platform=platform)
        pack = got.data if got.ok and isinstance(got.data, dict) else None
        return pack or {"version": None, "rules": {}}

    def _listing_report(self, listing_id: int) -> dict | None:
        """读最近一次 Listing 合规报告走 Compliance Tool（发布门禁读的是 risk_level）。"""
        got = self.tool("compliance").call("check_listing", listing_id=listing_id)
        report = got.data.get("report") if (got.ok and isinstance(got.data, dict)) else None
        return report if isinstance(report, dict) else None

    def _write_listing(self, listing_id: int, **fields) -> None:
        """回写 Listing 字段（写路径，集中一处）。

        §18.3 第 3 步（Action 层）的欠账：仍是一次 Agent 直改业务数据（§9.1），
        不在读取迁移范围内；集中一处，第 3 步改由 Action 执行时只有一处要动。
        """
        obj = self.db.get(Listing, listing_id)
        if obj and obj.tenant_id == self.tenant_id:
            for name, value in fields.items():
                setattr(obj, name, value)
            obj.updated_at = datetime.utcnow()
            self.db.commit()

    def _knowledge_context(self, p: dict, platform: str) -> tuple[str, dict, list[dict], list[str]]:
        """收集生成所需的平台规则与知识库上下文。返回 (prompt片段, 规则包, 知识文档, 违禁词)。"""
        docs = self._knowledge(f"{p['category']} 文案规范 违禁词 平台规则", top_k=3)
        pack = self._rule_pack(platform)
        rules = pack.get("rules", {})
        title_max = int(rules.get("title_max", 200))
        banned = list(rules.get("banned_words", []))

        lines = []
        if docs:
            lines.append("参考知识（来自企业知识库，必须遵守）：")
            lines.extend(f"- {d['title']}：{d['content'][:200]}" for d in docs)
        lines.append(f"平台规则约束（{platform}，规则版本 {pack.get('version')}）：")
        lines.append(f"- 标题长度上限 {title_max} 字符")
        lines.append(f"- 严禁出现违禁词：{'、'.join(banned[:20]) if banned else '无特殊限制'}")
        lines.append(f"- 图片要求：至少 {rules.get('image_min', 1)} 张")
        return "\n".join(lines), pack, docs, banned

    def generate(self, product_id: int, platform: str = "shopee", language: str = "en") -> dict:
        """生成 Listing（M2 知识增强版）。"""
        p = self._product(product_id)
        context, pack, docs, banned = self._knowledge_context(p, platform)

        def rule() -> dict:
            return self._fallback_copy(p, platform, language, banned)
        title_max = int(pack.get("rules", {}).get("title_max", 200))

        system = "你是资深跨境电商 Listing 文案专家，擅长 SEO 与转化率优化。只返回 JSON。"
        prompt = (
            f"为商品生成 {platform} 平台、{language} 语言的 Listing。商品: {p['title']}；"
            f"类目: {p['category']}；属性: {p['attrs']}。要求：标题不超过 {title_max} 字符且含核心关键词；"
            "description 3-5 句；bullets 5 条卖点；keywords 12 个搜索词。\n"
            f"{context}\n"
            '返回 JSON: {"title":"","description":"","bullets":[""],"keywords":[""]}'
        )
        result, mode = self.ask_json("generate", system, prompt, fallback=rule)
        if not result.get("title") or not result.get("description"):
            result, mode = rule(), "rule"

        # 生成后自检：仅违规时重试一次（避免 LLM 成本翻倍）
        violations = self._self_check(result, title_max, banned)
        retried = False
        if violations and mode == "llm":
            retried = True
            fix_prompt = (
                "以下 Listing 违反平台规则，请修正后重新输出完整 JSON：\n"
                f"违规项：{'；'.join(violations)}\n"
                f"原标题：{str(result.get('title', ''))[:200]}\n"
                f"要求：标题不超过 {title_max} 字符，移除违禁词（{'、'.join(banned[:10])}），保持营销力。\n"
                '返回 JSON: {"title":"","description":"","bullets":[""],"keywords":[""]}'
            )
            fixed, _mode2 = self.ask_json("generate_fix", system, fix_prompt,
                                          fallback=lambda: result)
            if fixed.get("title") and not self._self_check(fixed, title_max, banned):
                result, violations = fixed, []

        # 仍违规则降级模板（模板本身过检才用），否则标记待人工复核
        needs_review = bool(violations)
        if needs_review:
            safe = self._fallback_copy(p, platform, language, banned)
            if not self._self_check(safe, title_max, banned):
                result, violations, needs_review = safe, [], False

        row = Listing(tenant_id=self.tenant_id, product_id=product_id, platform=platform,
                      language=language, title=result["title"], description=result["description"],
                      bullets=result.get("bullets") or [], keywords=result.get("keywords") or [],
                      status="draft", risk_level="unknown",
                      model="llm" if mode == "llm" else "rule")
        # 写路径（新建 Listing）：§18.3 第 3 步（Action 层）欠账，见 D40。
        self.db.add(row)
        self.db.commit()

        knowledge_refs = [{"doc_id": d["id"], "title": d["title"]} for d in docs]
        # M6：记录决策依据链（知识来源 + 规则版本 + 自检结果）
        self.record_decision(
            action="generate_listing", subject_type="listing", subject_id=row.id,
            decision={"title_len": len(row.title), "keyword_count": len(row.keywords or []),
                      "needs_review": needs_review, "retried": retried},
            evidence={"knowledge_refs": knowledge_refs, "rule_version": pack.get("version"),
                      "platform": platform, "title_max": title_max,
                      "violations": violations},
            model=row.model)
        return {
            "id": row.id, "product_id": product_id, "platform": platform, "language": language,
            "title": row.title, "description": row.description, "bullets": row.bullets,
            "keywords": row.keywords, "status": row.status, "risk_level": row.risk_level,
            "external_id": row.external_id, "published_at": None, "model": row.model,
            "knowledge_refs": knowledge_refs, "rule_version": pack.get("version"),
            "needs_review": needs_review, "retried": retried,
            "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def optimize(self, listing_id: int) -> dict:
        row = self._listing(listing_id)
        p = self._product(row["product_id"])
        _, _pk, _docs, _banned = self._knowledge_context(p, row["platform"])
        fresh = self._fallback_copy(p, row["platform"], row["language"], _banned)
        title = f"{fresh['title']} [Optimized]"
        keywords = list(dict.fromkeys((row["keywords"] or []) + fresh["keywords"]))[:15]
        self._write_listing(listing_id, title=title, keywords=keywords)
        return {"id": row["id"], "title": title, "keywords": keywords, "status": row["status"]}

    # ---------- 一键发布 ----------
    def publish(self, listing_id: int) -> dict:
        """发布：先过平台规则包校验（人工编辑也可能写入违禁词），再看合规报告。

        规则校验是发布前的硬门禁，与生成期自检相互独立——生成期清洗不替代发布期把关。
        """
        row = self._listing(listing_id)
        # 平台规则包硬校验（标题长度/违禁词/禁售类目/图片要求）：规则包与商品都来自
        # Tool，判定用 services 的字段级核心（T-53：判定逻辑只有一份）。
        pack = self._rule_pack(row["platform"])
        product = self._optional_product(row["product_id"])
        if product is not None:
            violations = validate_listing_fields(row["platform"], pack.get("rules", {}),
                                                 row, product)
            if violations:
                raise ValueError("平台规则校验未通过（为保护店铺拒绝发布）：" + "；".join(violations))
        report = self._listing_report(listing_id)
        if report and report.get("risk_level") == "high":
            raise ValueError("合规风险高，禁止发布")
        external_id = f"{row['platform']}-{row['id']:06d}"
        self._write_listing(listing_id, status="published", external_id=external_id,
                            published_at=datetime.utcnow())
        return {"id": row["id"], "status": "published", "external_id": external_id,
                "platform": row["platform"], "product_id": row["product_id"]}

    # ---------- 批量动作（供工作流调用） ----------
    def generate_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        ids = params.get("product_ids") or context.get("product_ids") or []
        platform = params.get("platform", "shopee")
        language = params.get("language", "en")
        listings, listing_ids = [], []
        for pid in ids[:50]:
            try:
                r = self.generate(int(pid), platform, language)
                listings.append(r)
                listing_ids.append(r["id"])
            except Exception:
                continue
        return {"listings": listings, "context_patch": {"listing_ids": listing_ids}}

    def publish_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        ids = params.get("listing_ids") or context.get("listing_ids") or []
        published, blocked = [], []
        for lid in ids[:50]:
            try:
                r = self.publish(int(lid))
                published.append({"listing_id": r["id"], "external_id": r["external_id"]})
            except ValueError as e:
                blocked.append({"listing_id": lid, "reason": str(e)})
        return {"published": published, "blocked": blocked, "context_patch": {}}
