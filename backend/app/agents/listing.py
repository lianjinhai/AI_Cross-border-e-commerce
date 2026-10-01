"""Listing Agent：AI 生成多语言商品文案 / 优化 / 一键发布（对应规划第五章 4.5 节、第九章）。

M2 知识增强：生成前注入知识库检索结果与平台规则包约束；生成后规则引擎自检，
违禁词/超长时带修正提示重试一次（上限 1 次）；仍违规则降级模板并标记待复核。

读取全部经 Tool 层；草稿、优化、发布只产生提案，Orchestrator 调度独立 Action 执行。
"""
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
        lang = (language or "en").strip().lower()
        copy = self._localized_copy(lang, raw_title, base, material, color, scene,
                                     suffix, p, banned)
        title, desc, bullets, keywords = copy
        while len(keywords) < 12:
            keywords.append(f"{base} {len(keywords)}")
        return {"title": title[:220], "description": desc, "bullets": bullets[:5],
                "keywords": keywords[:15]}

    @staticmethod
    def _localized_copy(lang: str, raw_title: str, base: str, material: str,
                        color: str, scene: str, suffix: str, p: dict,
                        banned: list[str] | None) -> tuple[str, str, list[str], list[str]]:
        """按目的国语种生成 fallback 文案（D60 多语言扩展）。

        之前只有 zh / en 两分支，日韩德法西泰越等目的国一律落进 en 分支，
        卖到日本页面全是英文——转化率与 SEO 双输。这里按语种给出本地化模板，
        关键词同步本地化；未覆盖语种回退到 en（保留原行为）。
        """
        category = p.get("category", "")
        if lang.startswith("zh"):
            title = f"{raw_title} {material}材质 {color}色 跨境爆款"
            desc = (f"{raw_title}，采用{material}材质，{color}配色，适合{scene}。"
                    "工厂直供、品质保障，支持一件代发，跨境卖家首选。")
            bullets = ["工厂直供 品质保障", "优选材质 经久耐用", "多场景适用", "支持一件代发", "7天无理由退换"]
            keywords = [category, raw_title, f"{raw_title}批发", f"{color} {category}"]
            return title, desc, bullets, keywords
        if lang.startswith("ja"):
            title = f"{base} {material} {color} {scene}用 | {suffix} 2026"
            desc = (f"{scene}に最適な{color}の{base}。耐久性のある{material}で作られ、"
                    f"実用的なデザインと信頼できる品質を組み合わせています。工場から直接発送、品質検査済み。")
            bullets = ["工場直送・厳格な品質管理", f"耐久性のある{material}、{color}仕上げ",
                       f"{scene}やギフトに最適", "コンパクトで持ち運び簡単", "24時間サポート・返品対応"]
            keywords = [base, f"{base} {color}", f"{base} {material}", f"おすすめ {category}", f"{category} 2026"]
            return title, desc, bullets, keywords
        if lang.startswith("ko"):
            title = f"{base} {material} {color} {scene}용 | {suffix} 2026"
            desc = (f"{scene}에 적합한 {color} {base}. 내구성 있는 {material}로 제작되어 "
                    f"실용적인 디자인과 신뢰할 수 있는 품질을 결합했습니다. 공장 직접 배송, 품질 검사 완료.")
            bullets = ["공장 직송·엄격한 품질 관리", f"내구성 {material}, {color} 마감",
                       f"{scene} 및 선물용으로 적합", "소형·휴대용·세척 용이", "24시간 고객 지원·반품 가능"]
            keywords = [base, f"{base} {color}", f"{base} {material}", f"추천 {category}", f"{category} 2026"]
            return title, desc, bullets, keywords
        if lang.startswith("de"):
            title = f"{base} {material} {color} für {scene} | {suffix} 2026"
            desc = (f"Verbessern Sie Ihr {scene} mit diesem {color} {base}. Aus langlebigem {material} gefertigt, "
                    f"vereint es praktisches Design mit zuverlässiger Qualität. Direktwerkversand mit Qualitätsprüfung.")
            bullets = ["Direkt ab Werk mit strenger Qualitätskontrolle",
                       f"Langlebiges {material}, {color}-Farbton", f"Ideal für {scene} und als Geschenk",
                       "Kompakt, tragbar und leicht zu reinigen", "24/7 Kundenservice & einfache Rückgabe"]
            keywords = [base, f"{base} {color}", f"{base} {material}", f"beste {category}", f"{category} 2026"]
            return title, desc, bullets, keywords
        if lang.startswith(("fr",)):
            title = f"{base} {material} {color} pour {scene} | {suffix} 2026"
            desc = (f"Améliorez votre {scene} avec ce {base} {color}. Fabriqué en {material} durable, "
                    f"il combine design pratique et qualité fiable. Expédition directe usine, contrôle qualité inclus.")
            bullets = ["Direct usine avec contrôle qualité strict",
                       f"{material} durable, finition {color}", f"idéal pour {scene} et cadeaux",
                       "Compact, portable et facile à nettoyer", "Support 24/7 et retours faciles"]
            keywords = [base, f"{base} {color}", f"{base} {material}", f"meilleur {category}", f"{category} 2026"]
            return title, desc, bullets, keywords
        if lang.startswith(("es",)):
            title = f"{base} {material} {color} para {scene} | {suffix} 2026"
            desc = (f"Mejora tu {scene} con este {base} {color}. Fabricado en {material} resistente, "
                    f"combina diseño práctico con calidad fiable. Envío directo de fábrica con control de calidad.")
            bullets = ["Directo de fábrica con control de calidad estricto",
                       f"{material} resistente, acabado {color}", f"ideal para {scene} y regalos",
                       "Compacto, portátil y fácil de limpiar", "Soporte 24/7 y devoluciones fáciles"]
            keywords = [base, f"{base} {color}", f"{base} {material}", f"mejor {category}", f"{category} 2026"]
            return title, desc, bullets, keywords
        if lang.startswith(("th",)):
            title = f"{base} {material} สี{color} สำหรับ{scene} | {suffix} 2026"
            desc = (f"ปรับปรุง{scene}ของคุณด้วย{base}สี{color} ทำจาก{material}ที่ทนทาน "
                    f"ผสมผสานดีไซน์ที่ใช้งานได้จริงและคุณภาพที่เชื่อถือได้ ส่งตรงจากโรงงานพร้อมตรวจสอบคุณภาพ")
            bullets = ["ส่งตรงจากโรงงานพร้อมการตรวจสอบคุณภาพ",
                       f"{material}ทนทาน สี{color}", f"เหมาะสำหรับ{scene}และของขวัญ",
                       "กะทัดรัด พกพาง่าย ทำความสะอาดง่าย", "บริการ 24/7 และคืนสินค้าง่าย"]
            keywords = [base, f"{base} {color}", f"{base} {material}", f"{category} แนะนำ", f"{category} 2026"]
            return title, desc, bullets, keywords
        if lang.startswith(("vi",)):
            title = f"{base} {material} màu {color} cho {scene} | {suffix} 2026"
            desc = (f"Nâng tầm {scene} của bạn với {base} màu {color}. Làm từ {material} bền bỉ, "
                    f"kết hợp thiết kế thực dụng và chất lượng đáng tin cậy. Giao trực tiếp từ nhà máy, đã kiểm tra chất lượng.")
            bullets = ["Giao trực tiếp từ nhà máy, kiểm soát chất lượng nghiêm ngặt",
                       f"{material} bền, màu {color}", f"phù hợp cho {scene} và quà tặng",
                       "Nhỏ gọn, dễ mang theo, dễ làm sạch", "Hỗ trợ 24/7 và đổi trả dễ dàng"]
            keywords = [base, f"{base} {color}", f"{base} {material}", f"{category} tốt nhất", f"{category} 2026"]
            return title, desc, bullets, keywords
        # 默认 en（保留原行为）
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
                    f"best {category}", f"{category} 2026",
                    f"{base} for {scene}"]
        return title, desc, bullets, keywords

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

        knowledge_refs = [{"doc_id": d["id"], "title": d["title"]} for d in docs]
        payload = {"platform": platform, "language": language, "title": result["title"],
                   "description": result["description"], "bullets": result.get("bullets") or [],
                   "keywords": result.get("keywords") or [],
                   "model": "llm" if mode == "llm" else "rule"}
        output = {
            **payload, "id": None, "product_id": product_id,
            "status": "PROPOSED", "risk_level": "unknown",
            "external_id": "", "published_at": None,
            "knowledge_refs": knowledge_refs, "rule_version": pack.get("version"),
            "needs_review": needs_review, "retried": retried,
            "_decision_record": {"decision": {
                "title_len": len(payload["title"]), "keyword_count": len(payload["keywords"]),
                "needs_review": needs_review, "retried": retried},
                "evidence": {"knowledge_refs": knowledge_refs, "rule_version": pack.get("version"),
                             "platform": platform, "title_max": title_max, "violations": violations}},
        }
        return self.propose("CREATE_LISTING_DRAFT", "product", product_id, payload,
                            output, "生成经过文案自检的 Listing 草稿，不执行上架")

    def optimize(self, listing_id: int) -> dict:
        row = self._listing(listing_id)
        p = self._product(row["product_id"])
        _, _pk, _docs, _banned = self._knowledge_context(p, row["platform"])
        fresh = self._fallback_copy(p, row["platform"], row["language"], _banned)
        title = f"{fresh['title']} [Optimized]"
        keywords = list(dict.fromkeys((row["keywords"] or []) + fresh["keywords"]))[:15]
        return self.propose("UPDATE_LISTING_CONTENT", "listing", listing_id,
                            {"title": title, "keywords": keywords,
                             "before": {"title": row["title"], "keywords": row["keywords"] or []}},
                            {"id": row["id"], "title": title, "keywords": keywords,
                             "status": "PROPOSED"}, "优化草稿标题与关键词，不修改已发布内容")

    # ---------- 一键发布 ----------
    def publish(self, listing_id: int, shop_id: int | None = None) -> dict:
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
        return self.propose("PUBLISH_LISTING", "listing", listing_id,
                            {"shop_id": shop_id},
                            {"id": row["id"], "status": "PROPOSED",
                             "platform": row["platform"], "product_id": row["product_id"]},
                            "发布已通过规则检查的 Listing，必须人工审批后执行")

    # ---------- 批量动作（供工作流调用） ----------
    def generate_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        ids = params.get("product_ids") or context.get("product_ids") or []
        platform = params.get("platform", "shopee")
        language = params.get("language", "en")
        listings, listing_ids, errors = [], [], []
        for index, pid in enumerate(ids[:50]):
            try:
                r = self.generate(int(pid), platform, language)
                r["_proposal_slot"] = index
                listings.append(r)
                listing_ids.append(r["id"])
            except ValueError as exc:
                errors.append({"product_id": pid, "reason": str(exc)})
        return {"listings": listings, "errors": errors, "context_patch": {"listing_ids": listing_ids}}

    def publish_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        ids = params.get("listing_ids", context.get("approved_listing_ids", context.get("listing_ids", [])))
        published, blocked = [], []
        for lid in ids[:50]:
            try:
                r = self.publish(int(lid), params.get("shop_id"))
                published.append({"listing_id": r["id"], **r})
            except ValueError as e:
                blocked.append({"listing_id": lid, "reason": str(e)})
        return {"published": published, "blocked": blocked, "context_patch": {}}
