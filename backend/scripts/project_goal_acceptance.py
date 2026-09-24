"""项目目标验收：在独立数据库上模拟跨境 ERP 的主要业务闭环。

用法：python scripts/project_goal_acceptance.py [base_url]
说明：脚本只应指向验收实例；会写入商品、广告、客服等演示记录。
"""
import sys

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/") + "/api"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    results: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        results.append((name, condition, detail))
        print(f"[{'PASS' if condition else 'FAIL'}] {name}: {detail}")

    with httpx.Client(base_url=BASE, timeout=30) as client:
        def request(method: str, path: str, **kwargs):
            response = client.request(method, path, **kwargs)
            try:
                data = response.json()
            except Exception:
                data = {"_raw": response.text[:200]}
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"{method} {path} -> {response.status_code}: {data}")
            return data

        try:
            login = request("POST", "/auth/login", json={"username": "admin", "password": "admin123"})
            headers = {"Authorization": f"Bearer {login['token']}"}
            check("账号与鉴权", bool(login.get("token")), "管理员登录成功")

            meta = request("GET", "/shops/platforms", headers=headers)["items"]
            by_key = {row["platform"]: row for row in meta}
            expected = {"1688", "tiktok", "shopee", "amazon", "ebay", "walmart",
                        "lazada", "aliexpress", "temu", "shopify", "mercadolibre", "shein"}
            source_ok = by_key["1688"]["role"] == "source" and not by_key["1688"]["can_publish"]
            planned_safe = all(not by_key[k]["can_publish"] and not by_key[k]["can_order_sync"]
                               for k in ("amazon", "aliexpress", "temu",
                                         "shopify", "mercadolibre", "shein"))
            check("平台定位与能力门禁", expected.issubset(by_key) and source_ok and planned_safe,
                  f"识别 {len(expected)} 个目标平台；1688=货源，未实接能力保持关闭")

            collected = request("POST", "/products/collect", headers=headers,
                                json={"source_platform": "1688", "keyword": "portable pet feeder", "count": 2})
            product = collected["items"][0]
            pid = product["id"]
            standardized = request("POST", f"/products/{pid}/standardize", headers=headers)
            score = request("POST", f"/discovery/score/{pid}", headers=headers)
            check("1688货源选品", standardized.get("product_id") == pid and score.get("total") is not None,
                  f"商品#{pid} 已标准化，选品分={score.get('total')}")

            pricing = request("POST", "/pricing/suggest", headers=headers, json={"product_id": pid})
            profit = request("POST", "/pricing/calc", headers=headers, json={"product_id": pid})
            compliance = request("POST", "/compliance/check", headers=headers,
                                 json={"target_type": "product", "ref_id": pid})
            check("定价与合规", pricing.get("suggested_price") is not None and
                  profit.get("profit") is not None and compliance.get("risk_level") is not None,
                  f"建议价={pricing.get('suggested_price')}，利润={profit.get('profit')}，风险={compliance.get('risk_level')}")

            listing = request("POST", "/listings/generate", headers=headers,
                              json={"product_id": pid, "platform": "shopee", "language": "en"})
            published = request("POST", f"/listings/{listing['id']}/publish", headers=headers, json={})
            check("Listing生成与演示发布", published.get("status") == "published" and
                  published.get("source") == "local",
                  f"Listing#{listing['id']} source={published.get('source')}（非真实平台发布）")

            ad = request("POST", "/ads/campaigns", headers=headers,
                         json={"name": "验收广告", "platform": "facebook", "product_id": pid,
                               "keywords": ["pet feeder"], "budget": 50})
            suggestion = request("POST", "/ads/suggest", headers=headers,
                                 json={"product_id": pid, "platform": "facebook"})
            optimized = request("POST", f"/ads/campaigns/{ad['id']}/optimize", headers=headers)
            check("广告增长", bool(suggestion) and optimized.get("campaign_id") == ad["id"],
                  f"广告#{ad['id']} 已生成建议并完成预算优化")

            synced = request("POST", "/orders/sync", headers=headers,
                             json={"platform": "shopee", "count": 1})
            order = synced["items"][0]
            oid = order["id"]
            if order.get("status") != "paid":
                request("PUT", f"/orders/{oid}/status", headers=headers, json={"status": "paid"})
            shipped = request("POST", f"/orders/{oid}/ship", headers=headers)
            check("市场订单履约", shipped.get("status") == "shipped" and bool(shipped.get("tracking_no")),
                  f"订单#{oid} 已发货，运单={shipped.get('tracking_no')}（系统模拟单号）")

            conversation = request("POST", "/support/conversations", headers=headers,
                                   json={"platform": "shopee", "buyer_name": "Acceptance Buyer",
                                         "content": "Where is my order?", "order_id": oid})
            auto_reply = request("POST", f"/support/conversations/{conversation['id']}/auto_reply",
                                 headers=headers)
            closed = request("POST", f"/support/conversations/{conversation['id']}/close", headers=headers)
            check("智能客服", bool(auto_reply.get("content")) and closed.get("status") == "closed",
                  f"会话#{conversation['id']} 自动回复后关闭")

            products_csv = client.get("/products/export", headers=headers)
            orders_csv = client.get("/orders/export", headers=headers)
            check("数据导出", products_csv.status_code == 200 and orders_csv.status_code == 200 and
                  len(products_csv.content) > 20 and len(orders_csv.content) > 20,
                  f"商品CSV={len(products_csv.content)}B，订单CSV={len(orders_csv.content)}B")

            dashboard = request("GET", "/bi/dashboard", headers=headers)
            report = request("GET", "/bi/report", headers=headers)
            check("BI经营分析", bool(dashboard) and bool(report), "仪表盘和经营报告均返回有效结果")

            knowledge = request("GET", "/knowledge/search", headers=headers,
                                params={"q": "违禁词", "top_k": 3})
            chat = request("POST", "/ai/chat", headers=headers, json={"message": "帮我分析这个商品"})
            check("知识库与AI助手", bool(knowledge.get("items")) and bool(chat.get("reply")),
                  f"知识命中={len(knowledge.get('items', []))}，助手意图={chat.get('intent')}")
        except Exception as exc:
            check("未捕获接口异常", False, str(exc))

    failed = [item for item in results if not item[1]]
    print(f"\n项目目标验收：PASS {len(results) - len(failed)} / FAIL {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
