"""P1 AI 原生能力验收：M2 Listing 知识增强 / M5 真实趋势接入。

方案依据：docs/AI原生能力升级方案.md（定稿）
关键红线：演示数据不得伪装成真实数据（M5 的 source 字段如实标记）。
"""
import time

import pytest


class TestListingKnowledgeEnhancement:
    """M2：生成前注入知识/规则，生成后自检，引用可追溯。"""

    def test_generate_returns_knowledge_refs(self, client, auth_headers):
        """生成结果含 knowledge_refs 与 rule_version（用了哪些知识/规则）。"""
        pid = client.get("/api/products", headers=auth_headers,
                         params={"page_size": 1}).json()["items"][0]["id"]
        r = client.post("/api/listings/generate", headers=auth_headers,
                        json={"product_id": pid, "platform": "shopee", "language": "en"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "knowledge_refs" in d, "缺少知识引用（M2 核心字段）"
        assert d.get("rule_version"), "缺少规则版本"
        assert "needs_review" in d and "retried" in d

    def test_knowledge_refs_point_to_real_docs(self, client, auth_headers):
        """knowledge_refs 必须指向真实存在的知识文档。"""
        # 自建商品 + 知识文档：原实现依赖种子商品与"知识库恰好有匹配文档"，
        # 不满足就 skip —— 单跑时该用例静默跳过，引用有效性零覆盖
        # （规范 §8 T-2：不得依赖前序用例产出）。
        pid = client.post("/api/products", headers=auth_headers, json={
            "title": "知识引用测试品 退货流程", "category": "家居",
            "attrs": {"supplier_price": 8, "sale_price": 20,
                      "material": "PP", "scene": "home"}}).json()["id"]
        client.post("/api/knowledge/docs", headers=auth_headers, json={
            "title": "退货流程说明", "content": "退货流程说明：签收后 7 天内可申请退货",
            "source": "test", "tags": ["退货"]})
        d = client.post("/api/listings/generate", headers=auth_headers,
                        json={"product_id": pid}).json()
        refs = d.get("knowledge_refs") or []
        assert refs, "已建知识文档却未产生 knowledge_refs（M2 引用链断裂）"
        docs = client.get("/api/knowledge/docs", headers=auth_headers,
                          params={"page_size": 100}).json()["items"]
        doc_ids = {x["id"] for x in docs}
        for ref in refs:
            assert ref["doc_id"] in doc_ids, f"引用了不存在的文档 {ref}"

    def test_self_check_blocks_banned_words(self, client, auth_headers):
        """自检逻辑：构造含违禁词的商品，生成结果不得含该词（模板降级或重试）。"""
        r = client.post("/api/products", headers=auth_headers,
                        json={"title": "违禁词自检测试 best seller 商品", "category": "家居",
                              "attrs": {"sale_price": 20, "supplier_price": 8,
                                        "material": "PP", "color": "white", "scene": "home"}})
        pid = r.json()["id"]
        d = client.post("/api/listings/generate", headers=auth_headers,
                        json={"product_id": pid, "platform": "amazon"}).json()
        # amazon 规则包含 "best seller" 违禁词；生成结果（标题+描述+卖点+关键词）不得含
        text = " ".join([d["title"], d.get("description", ""),
                         " ".join(d.get("bullets") or []),
                         " ".join(d.get("keywords") or [])]).lower()
        assert "best seller" not in text, f"违禁词未被拦截: {d['title']}"

    def test_decision_recorded_with_rule_version(self, client, auth_headers):
        """M6：生成决策留痕，evidence 含规则版本与知识引用。"""
        pid = client.get("/api/products", headers=auth_headers,
                         params={"page_size": 1}).json()["items"][0]["id"]
        d = client.post("/api/listings/generate", headers=auth_headers,
                        json={"product_id": pid}).json()
        r = client.get("/api/ai/decisions", headers=auth_headers,
                       params={"subject_type": "listing", "subject_id": d["id"]})
        assert r.status_code == 200
        items = r.json()["items"]
        assert items and items[0]["action"] == "generate_listing"
        ev = items[0]["evidence"]
        assert "rule_version" in ev and "knowledge_refs" in ev

    def test_offline_mode_still_works(self, client, auth_headers):
        """离线（无 LLM）时生成仍可用，降级模板且不报错。"""
        pid = client.get("/api/products", headers=auth_headers,
                         params={"page_size": 1}).json()["items"][0]["id"]
        r = client.post("/api/listings/generate", headers=auth_headers,
                        json={"product_id": pid, "language": "zh"})
        assert r.status_code == 200
        # 测试环境未配置 LLM（无 API key），ask_json 必然降级到规则引擎。
        # 原断言 `in ("rule", "llm")` 是恒真式（该字段只能取这两值），
        # 无法发现"本该降级却误报 llm"或"降级链路坏掉"。
        assert r.json()["model"] == "rule", r.json()
        assert r.json()["title"]


class TestTrendSource:
    """M5：真实趋势接入，来源如实标记（不伪装数据）。"""

    def test_import_csv_trends(self, client, auth_headers):
        """CSV 导入真实趋势：source=csv，数据可查。"""
        stamp = int(time.time())
        kw = f"csv测试关键词{stamp}"
        csv_text = (
            "关键词,搜索量,增长率,竞争度,平台\n"
            f"{kw},25000,145.5,38,google\n"
            f"csv测试词B{stamp},12000,80.0,55,amazon\n"
        )
        r = client.post("/api/discovery/trends/import", headers=auth_headers,
                        json={"csv_text": csv_text})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["imported"] == 2 and d["source"] == "csv", d

        trends = client.get("/api/discovery/trends", headers=auth_headers).json()["items"]
        row = next((t for t in trends if t["keyword"] == kw), None)
        assert row, "导入的趋势未出现在列表"
        assert row["search_volume"] == 25000 and row["growth_30d"] == 145.5
        assert row["source"] == "csv", "来源必须标记为 csv"

    def test_csv_header_aliases(self, client, auth_headers):
        """兼容英文表头（keyword/volume/growth/competition）。"""
        stamp = int(time.time())
        csv_text = (
            "keyword,volume,growth,competition\n"
            f"alias-test-{stamp},8888,66.6,44\n"
        )
        r = client.post("/api/discovery/trends/import", headers=auth_headers,
                        json={"csv_text": csv_text})
        assert r.status_code == 200 and r.json()["imported"] == 1, r.text

    def test_import_validates_input(self, client, auth_headers):
        """空内容/缺关键词必须给出可读错误。"""
        r = client.post("/api/discovery/trends/import", headers=auth_headers,
                        json={"csv_text": "   "})
        assert r.status_code == 400
        r = client.post("/api/discovery/trends/import", headers=auth_headers,
                        json={"csv_text": "关键词,搜索量\n,123"})
        assert r.status_code == 200 and r.json()["imported"] == 0
        assert r.json()["errors"], "缺关键词应记录错误"

    def test_scan_does_not_overwrite_real_data(self, client, auth_headers):
        """红线：内置词池扫描不得覆盖真实来源（csv/api）的趋势数据。"""
        # 刻意用与内置池同名的关键词：只有同名才会触发「扫描是否覆盖」这一冲突路径
        kw = "led strip lights"
        csv_text = f"关键词,搜索量,增长率,竞争度\n{kw},99999,200.0,10\n"
        r = client.post("/api/discovery/trends/import", headers=auth_headers,
                        json={"csv_text": csv_text})
        assert r.status_code == 200
        # 触发内置扫描（会尝试写同名关键词）
        client.post("/api/discovery/trends/scan", headers=auth_headers)
        trends = client.get("/api/discovery/trends", headers=auth_headers).json()["items"]
        row = next((t for t in trends if t["keyword"] == kw), None)
        assert row and row["source"] == "csv", f"真实数据被内置池覆盖: {row}"
        assert row["search_volume"] == 99999, "真实数据被覆盖"

    def test_source_summary_distinguishes_real_data(self, client, auth_headers):
        """来源汇总如实区分真实/演示数据（前端据此提示）。"""
        r = client.get("/api/discovery/trends/source", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d["counts"]) == {"api", "csv", "builtin"}
        assert "has_real_data" in d and "hint" in d
        assert d["real_count"] == d["counts"]["api"] + d["counts"]["csv"]

    def test_1688_trend_without_key_errors_clearly(self, client, auth_headers):
        """无 1688 API 配置时，真实源必须明确报错而非返回假数据。"""
        from app.db import SessionLocal
        from app.services.trend_source import fetch_from_1688

        db = SessionLocal()
        try:
            with pytest.raises(ValueError) as exc:
                fetch_from_1688(db, 1, ["test"])
            assert "1688" in str(exc.value)
        finally:
            db.close()
