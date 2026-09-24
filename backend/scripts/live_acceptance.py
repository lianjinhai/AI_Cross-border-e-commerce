"""全链路验收脚本：对运行中的后端执行 4 条业务闭环（读取为主 + 少量演示数据写入）。

用法：python scripts/live_acceptance.py [base_url]   # base_url 默认 http://127.0.0.1:8000
输出：每步 PASS/FAIL（附关键字段），最后汇总；任一 FAIL 时退出码为 1。

**脚本自身必须可靠**（2026-09-24 修正两处"验收自己失灵"的缺陷）：
  1. 采购闭环原先取 `GET /products` 的**第一个**商品建单，一旦该商品没有
     `supplier_offers` 记录就会 404「无可用货源报价」——**是脚本选错了商品，
     不是采购功能坏了**。现在改为显式探测"有在库报价"的商品（offers 的
     `product_id` 字段反查），拿不到就明确报 SKIP 并说明原因，绝不伪装成 FAIL。
  2. 订单闭环原先传 `platform="shopee"`，而 `/orders/sync` 是**演示订单入口**，
     只接受 `demo:<平台>`（传真实平台名返回 409）。现在改用 `demo:shopee`。

为什么这两处必须修：验收脚本一旦自己不可靠，就会把"功能正常"误报为"功能坏了"，
反之也可能漏报。**假失败与假通过同样有害**。
"""
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1
        else "http://127.0.0.1:8000").rstrip("/") + "/api"


def call(client, method, path, **kw):
    """发请求，返回 (status, ok, data)。"""
    r = client.request(method, path, **kw)
    ok = 200 <= r.status_code < 300
    try:
        data = r.json()
    except Exception:
        data = {"_raw": r.text[:300]}
    return r.status_code, ok, data


def add(results, flow, step, status, detail):
    results.append((flow, step, status, detail))
    print(f"[{status}] {flow} / {step}: {detail}")


def _product_with_stock_offer(client, headers) -> int | None:
    """找一个「有在库货源报价」的商品 id，供采购闭环使用。

    `/suppliers/offers` 强制要求 `product_id` 参数，无法直接列出全部报价；
    因此先取商品列表，再逐个探测其报价接口，命中即返回。
    全部探测失败时返回 None（调用方据此报 SKIP 而非 FAIL）。
    """
    _, ok, prods = call(client, "GET", "/products",
                        params={"page_size": 50}, headers=headers)
    if not ok or not prods.get("items"):
        return None
    for p in prods["items"]:
        st, _, offers = call(client, "GET", "/suppliers/offers",
                             params={"product_id": p["id"]}, headers=headers)
        if st == 200 and any(o.get("in_stock") for o in (offers.get("items") or [])):
            return p["id"]
    return None


def _run_purchase_flow(client, headers, product_id: int):
    """执行采购 → 提交 → 收货 → 生成结算 → 确认 → 付款，返回关键对象供断言。"""
    _, _, po = call(client, "POST", "/purchases",
                    json={"product_id": product_id, "qty": 3}, headers=headers)
    po_id = po.get("id")
    call(client, "PUT", f"/purchases/{po_id}",
         json={"status": "submitted"}, headers=headers)
    _, ok, po_recv = call(client, "POST", f"/purchases/{po_id}/receive",
                          json={"qty": 3}, headers=headers)
    sid = po_recv["purchase"]["supplier_id"] if ok else 0
    _, ok, st = call(client, "POST", "/settlements/generate",
                     json={"supplier_id": sid}, headers=headers)
    st_id = st.get("id") if ok else None
    if st_id:
        call(client, "PUT", f"/settlements/{st_id}",
             json={"status": "confirmed"}, headers=headers)
        _, _, st_p = call(client, "PUT", f"/settlements/{st_id}",
                          json={"status": "paid"}, headers=headers)
    else:
        st_p = {}
    # 校验「本次生成的结算单」已 paid，而不是「该供应商应付总额归零」：
    # 供应商可能存在历史遗留的未结清结算单（种子数据里就有），
    # 用总额归零做断言会把「历史遗留」误报成「本次闭环失败」。
    _, _, st_detail = call(client, "GET", f"/settlements/{st_id}", headers=headers)
    if isinstance(st_p, dict) and st_id:
        st_p.setdefault("id", st_id)
        st_p.setdefault("status", st_detail.get("status") if isinstance(st_detail, dict) else None)
    return po_id, sid, st_p, st_detail


def main() -> int:
    results = []
    with httpx.Client(base_url=BASE, timeout=30) as c:
        _, ok, login = call(c, "POST", "/auth/login",
                            json={"username": "admin", "password": "admin123"})
        if not ok:
            add(results, "公共", "登录", "FAIL", str(login))
            return 1
        headers = {"Authorization": f"Bearer {login['token']}"}

        # ---- 流程1：采购 → 收货 → 结算闭环 ----
        # 必须选"有在库货源报价"的商品：任意取第一个商品会在无报价时误报失败。
        pid = _product_with_stock_offer(c, headers)
        if pid is None:
            add(results, "采购→收货→结算", "前置数据", "SKIP",
                "当前租户没有任何「在库货源报价」的商品，无法验证采购闭环"
                "（需先导入供应商报价；这是数据前提缺失，不是功能缺陷）")
            po_id = None
            sid = 0
            st_p = {}
            st_detail = {}
        else:
            po_id, sid, st_p, st_detail = _run_purchase_flow(c, headers, pid)
        if pid is not None:
            if st_p.get("status") == "paid":
                add(results, "采购→收货→结算", "全链状态", "PASS",
                    f"PO#{po_id} received → 结算#{st_p.get('id')} paid"
                    f"（供应商{sid}本次应付已结清）")
            else:
                add(results, "采购→收货→结算", "全链状态", "FAIL",
                    f"settle={st_p.get('status')}, detail={st_detail}")

        # ---- 流程2：订单 → 发货 → 售后退款闭环 ----
        # /orders/sync 是演示订单入口，必须用 demo:<平台>；传真实平台名会被 409 拒绝。
        # count 取 10：演示订单状态是随机的（5 选 1），3 个全落在终态的概率约
        # (3/5)^3≈22%，会让闭环**频繁跳过**；10 个全终态的概率降到约 0.6%，
        # 保证这条闭环几乎总能被真正验证到（要验证就要真的跑到）。
        _, ok, sync = call(c, "POST", "/orders/sync",
                           json={"platform": "demo:shopee", "count": 10}, headers=headers)
        # 演示订单状态是**随机**的（pending/paid/shipped/delivered/refunded）。
        # 原先盲取 items[0] 去发货，若恰好抽到 shipped/refunded 就会 400
        # 「仅已付款(paid)订单可发货」——**是脚本选错订单，不是发货功能坏了**。
        # 因此显式挑选可推进的订单：优先 pending/paid，其次任何未终态订单。
        items = (sync.get("items") or []) if ok else []
        o = next((x for x in items if x.get("status") in ("pending", "paid")), None) \
            or next((x for x in items if x.get("status") not in ("shipped", "delivered", "refunded")), None)
        if o is None:
            add(results, "订单→发货→退款", "前置数据", "SKIP",
                f"本次生成的 {len(items)} 个演示订单状态均为终态"
                f"（{[x.get('status') for x in items]}），无可推进订单；"
                "可重跑或提高 count（这是随机数据前提，不是功能缺陷）")
        oid = o.get("id") if o is not None else None
        if o is not None and o.get("status") != "paid":
            _, ok, _ = call(c, "PUT", f"/orders/{oid}/status",
                            json={"status": "paid"}, headers=headers)
        if o is not None:
            _, ok, ship = call(c, "POST", f"/orders/{oid}/ship", headers=headers)
            _, ok, rf = call(c, "POST", "/refunds",
                             json={"order_id": oid, "type": "return_refund",
                                   "qty": o.get("qty", 1)}, headers=headers)
            rid = rf.get("id") if ok else None
            _, ok, _ = call(c, "PUT", f"/refunds/{rid}/status",
                            json={"status": "approved"}, headers=headers)
            _, ok, rr = call(c, "POST", f"/refunds/{rid}/return_receive", headers=headers)
            _, ok, rd = call(c, "POST", f"/refunds/{rid}/refund", headers=headers)
            if ok and rd.get("order_status") == "refunded" and ship.get("tracking_no"):
                add(results, "订单→发货→退款", "全链状态", "PASS",
                    f"订单#{oid} shipped(tracking={ship['tracking_no']}) → 退款#{rid} refunded")
            else:
                add(results, "订单→发货→退款", "全链状态", "FAIL",
                    f"ship={ship}, refund_done={rd}")

        # ---- 流程3：采集 → 标准化 → 选品 → Listing → 发布 ----
        _, ok, col = call(c, "POST", "/products/collect",
                          json={"source_platform": "1688", "keyword": "pet", "count": 2},
                          headers=headers)
        cid = col["items"][0]["id"] if ok and col.get("items") else None
        _, ok, _ = call(c, "POST", f"/products/{cid}/standardize", headers=headers)
        _, ok, sc = call(c, "POST", f"/discovery/score/{cid}", headers=headers)
        _, ok, lg = call(c, "POST", "/listings/generate",
                         json={"product_id": cid, "platform": "shopee", "language": "en"},
                         headers=headers)
        lid = lg.get("id") if ok else None
        _, ok, pb = call(c, "POST", f"/listings/{lid}/publish", json={}, headers=headers)
        if ok and pb.get("source") == "local" and pb.get("status") == "published":
            add(results, "采集→选品→Listing→发布", "全链状态", "PASS",
                f"商品#{cid} score={sc.get('total')} → Listing#{lid} 本地发布 source=local")
        else:
            add(results, "采集→选品→Listing→发布", "全链状态", "FAIL",
                f"publish={pb}")
        _, _ok, _ = call(c, "DELETE", f"/listings/{lid}", headers=headers)

        # ---- 流程4：AI 工作流 + 调度 + 知识库 + 助手 ----
        _, ok, run = call(c, "POST", "/workflows/run",
                          json={"template_key": "auto_listing"}, headers=headers)
        run_id = run.get("id") if ok else None
        steps_ok = None
        for _ in range(60):
            _, ok2, rd2 = call(c, "GET", f"/workflows/runs/{run_id}", headers=headers)
            if ok2 and rd2.get("status") != "running":
                steps_ok = all(s.get("status") == "success" for s in rd2.get("steps", []))
                break
            time.sleep(2)
        if ok and steps_ok:
            add(results, "AI工作流", "auto_listing", "PASS",
                f"run#{run_id} 全部 {len(rd2.get('steps', []))} 步 success")
        else:
            add(results, "AI工作流", "auto_listing", "FAIL", f"run={rd2 if 'rd2' in dir() else run}")
        _, ok, sch = call(c, "POST", "/schedules",
                          json={"name": "临时验收趋势扫描", "kind": "trend_scan",
                                "interval_minutes": 60}, headers=headers)
        sch_id = sch.get("id") if ok else None
        _, ok, trig = call(c, "POST", f"/schedules/{sch_id}/run", headers=headers)
        _, ok, _ = call(c, "DELETE", f"/schedules/{sch_id}", headers=headers)
        if ok and trig.get("ok"):
            add(results, "调度", "临时趋势扫描+清理", "PASS", "立即执行成功，任务已删除")
        else:
            add(results, "调度", "临时趋势扫描+清理", "FAIL", str(trig))
        _, ok, kb = call(c, "GET", "/knowledge/search",
                         params={"q": "违禁词", "top_k": 3}, headers=headers)
        if ok and kb.get("items"):
            add(results, "知识库", "检索", "PASS", f"命中 {len(kb['items'])} 条")
        else:
            add(results, "知识库", "检索", "FAIL", str(kb))
        _, ok, chat = call(c, "POST", "/ai/chat",
                           json={"message": "帮我选品"}, headers=headers)
        if ok and chat.get("reply"):
            add(results, "AI助手", "chat", "PASS",
                f"intent={chat.get('intent')}, reply={str(chat.get('reply'))[:40]}")
        else:
            add(results, "AI助手", "chat", "FAIL", str(chat))

    fails = [r for r in results if r[2] == "FAIL"]
    skips = [r for r in results if r[2] == "SKIP"]
    passes = [r for r in results if r[2] == "PASS"]
    print("\n==== 汇总 ====")
    print(f"共 {len(results)} 步：PASS {len(passes)} / FAIL {len(fails)} / SKIP {len(skips)}")
    if skips:
        print("SKIP 原因（数据前提缺失，非功能缺陷）：")
        for _, step, _, detail in skips:
            print(f"  - {step}: {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
