"""权限与数据专项排查：全角色 × 全端点权限矩阵 + 跨表数据一致性审计。

用法：cd backend && python scripts/security_data_audit.py [base_url]
输出：越权访问（应拦未拦）、误拦（应放被拦）、数据不一致清单。

!! 危险提示 !!
本脚本的 ENDPOINTS 里含大量 POST/PUT 写操作（创建商品、供应商、广告、
知识库、定时任务等），会**真实写入**目标服务所连接的数据库。它曾在
主库（erp.db）留下 37 行 tenant_id=0 孤儿数据与 2 个每小时运行的
probe 定时任务，持续污染数据。

因此：**只允许对一次性临时库运行**，禁止直接对开发主库运行。
正确做法：
    1) 复制一份临时库：copy backend\\erp.db %TEMP%\\audit.db
    2) 用临时库启动服务：set ERP_DB_URL=sqlite:///<临时库绝对路径>
       python -m uvicorn app.main:app --port 8099
    3) 指向该端口运行：python scripts/security_data_audit.py http://127.0.0.1:8099
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1
        else "http://127.0.0.1:8000").rstrip("/")
client = httpx.Client(timeout=30)

# 安全护栏：探测前先确认目标库不是开发主库（erp.db）。
# 判定方式：调用平台总览接口，若存在 tenant_id=0 的业务数据或演示租户名，
# 说明极可能是主库；此时要求显式确认。
_ALLOW_MAIN_DB = os.getenv("ERP_AUDIT_ALLOW_MAIN_DB", "") == "1"


def _guard_target() -> None:
    """对开发主库运行前强制二次确认，避免再次污染。"""
    if _ALLOW_MAIN_DB:
        print("[WARN] 已显式允许对主库运行（ERP_AUDIT_ALLOW_MAIN_DB=1）")
        return
    try:
        r = client.get(f"{BASE}/api/health", timeout=5)
        if r.status_code != 200:
            return
    except Exception:
        return
    if BASE.endswith(":8000"):
        print("\n[ABORT] 检测到默认端口 8000（通常是开发主库）。")
        print("        本脚本会写入探测数据，禁止对主库直接运行。")
        print("        如确认要用一次性库，请传入其他端口，例如：")
        print("          python scripts/security_data_audit.py http://127.0.0.1:8099")
        print("        或显式承担风险：set ERP_AUDIT_ALLOW_MAIN_DB=1")
        sys.exit(3)


def login(username: str, password: str) -> dict | None:
    r = client.post(f"{BASE}/api/auth/login",
                    json={"username": username, "password": password})
    return r.json() if r.status_code == 200 else None


ROLES = {
    "viewer": ("viewer", "viewer123"),
    "operator": ("ops", "ops123"),
    "admin": ("admin", "admin123"),
    "superadmin": (os.getenv("ERP_SUPERADMIN_USERNAME", "root"),
                   os.getenv("ERP_SUPERADMIN_PASSWORD", "")),
}

# 端点清单：(方法, 路径模板, {路径参数实际值}, 期望body, 类别)
ENDPOINTS = [
    # 认证
    ("GET", "/api/auth/me", {}, None, "auth"),
    ("GET", "/api/auth/users", {}, None, "auth-admin"),
    ("POST", "/api/auth/users", {}, {"username": "probe-user-tmp", "password": "x12345678", "role": "viewer"}, "auth-admin"),
    # 商品域
    ("GET", "/api/products", {}, None, "read"),
    ("GET", "/api/products/1", {}, None, "read"),
    ("POST", "/api/products", {}, {"title": "probe item"}, "write"),
    ("POST", "/api/products/collect", {}, {"source_platform": "1688", "count": 1}, "write"),
    ("POST", "/api/products/1/standardize", {}, None, "write"),
    ("GET", "/api/products/export", {}, None, "read"),
    ("GET", "/api/discovery/trends", {}, None, "read"),
    ("POST", "/api/discovery/trends/scan", {}, None, "write"),
    ("POST", "/api/discovery/expand", {}, {"keyword": "probe"}, "write"),
    ("POST", "/api/discovery/score/1", {}, None, "write"),
    ("POST", "/api/discovery/pick", {}, {"limit": 1}, "write"),
    ("GET", "/api/discovery/scores", {}, None, "read"),
    ("GET", "/api/suppliers", {}, None, "read"),
    ("POST", "/api/suppliers", {}, {"name": "probe supplier"}, "write"),
    ("POST", "/api/suppliers/1/score", {}, None, "write"),
    ("POST", "/api/suppliers/match", {}, {"product_id": 1}, "write"),
    ("GET", "/api/suppliers/forecast", {}, None, "write"),
    ("GET", "/api/suppliers/offers?product_id=1", {}, None, "read"),
    ("GET", "/api/listings", {}, None, "read"),
    ("POST", "/api/listings/generate", {}, {"product_id": 1}, "write"),
    ("GET", "/api/compliance/reports", {}, None, "read"),
    ("POST", "/api/compliance/check", {}, {"target_type": "product", "ref_id": 1}, "write"),
    # 运营域
    ("GET", "/api/pricing", {}, None, "read"),
    ("POST", "/api/pricing/calc", {}, {"product_id": 1}, "write"),
    ("GET", "/api/ads/campaigns", {}, None, "read"),
    ("POST", "/api/ads/campaigns", {}, {"name": "probe ad"}, "write"),
    ("GET", "/api/orders", {}, None, "read"),
    ("POST", "/api/orders/sync", {}, {"platform": "shopee", "count": 1}, "write"),
    ("POST", "/api/orders/1/ship", {}, None, "write"),
    ("GET", "/api/support/conversations", {}, None, "read"),
    ("POST", "/api/support/conversations", {}, {"buyer_name": "probe", "content": "hi"}, "write"),
    ("GET", "/api/bi/dashboard", {}, None, "read"),
    ("GET", "/api/bi/profit", {}, None, "read"),
    ("GET", "/api/bi/report", {}, None, "read"),
    ("GET", "/api/workflows/templates", {}, None, "read"),
    ("POST", "/api/workflows/run", {}, {"template_key": "reprice"}, "write"),
    ("GET", "/api/workflows/runs", {}, None, "read"),
    ("GET", "/api/knowledge/docs", {}, None, "read"),
    ("GET", "/api/knowledge/search?q=probe", {}, None, "read"),
    ("POST", "/api/knowledge/docs", {}, {"title": "probe", "content": "probe content here"}, "write"),
    ("GET", "/api/ai/settings", {}, None, "read"),
    ("GET", "/api/ai/logs", {}, None, "read"),
    ("POST", "/api/ai/chat", {}, {"message": "hi"}, "write"),
    ("GET", "/api/schedules", {}, None, "read"),
    ("POST", "/api/schedules", {}, {"name": "probe", "kind": "trend_scan", "interval_minutes": 60}, "write"),
    ("GET", "/api/purchases", {}, None, "read"),
    ("POST", "/api/purchases", {}, {"product_id": 1, "qty": 1}, "write"),
    ("GET", "/api/settlements", {}, None, "read"),
    ("GET", "/api/settlements/summary", {}, None, "read"),
    ("GET", "/api/refunds", {}, None, "read"),
    ("POST", "/api/refunds", {}, {"order_id": 1, "qty": 1}, "write"),
    # 店铺与管理
    ("GET", "/api/shops", {}, None, "read"),
    ("GET", "/api/shops/platforms", {}, None, "read"),
    ("GET", "/api/shops/platform_rules", {}, None, "read"),
    ("POST", "/api/shops", {}, {"platform": "1688"}, "write"),
    ("GET", "/api/shops/category-mappings", {}, None, "read"),
    ("POST", "/api/shops/category-mappings", {}, {"platform": "shopee", "system_category": "家居", "platform_category_id": "1"}, "write"),
    # 平台服务商
    ("GET", "/api/admin/tenants", {}, None, "superadmin"),
    ("GET", "/api/admin/overview", {}, None, "superadmin"),
    ("GET", "/api/admin/access_logs", {}, None, "superadmin"),
    ("GET", "/api/admin/ai_logs", {}, None, "superadmin"),
    ("POST", "/api/admin/tenants", {}, {"name": "probe tenant"}, "superadmin"),
    ("PUT", "/api/ai/settings", {}, {"rules": {}}, "auth-admin"),
]

ROLE_EXPECT = {
    "viewer": {"read": 200, "write": 403, "auth": 200, "auth-admin": 403, "superadmin": 403},
    "operator": {"read": 200, "write": 200, "auth": 200, "auth-admin": 403, "superadmin": 403},
    "admin": {"read": 200, "write": 200, "auth": 200, "auth-admin": 200, "superadmin": 403},
    "superadmin": {"read": 200, "write": 200, "auth": 200, "auth-admin": 200, "superadmin": 200},
}


def method_call(method: str, path: str, body):
    if method == "GET":
        return client.get(f"{BASE}{path}", headers=HDRS)
    if method == "POST":
        return client.post(f"{BASE}{path}", json=body, headers=HDRS)
    if method == "PUT":
        return client.put(f"{BASE}{path}", json=body, headers=HDRS)
    raise ValueError(method)


_guard_target()

violations = []
created_cleanup = []

for role_name, (username, password) in ROLES.items():
    if role_name == "superadmin" and not password:
        print("\n[SKIP] superadmin 未配置 ERP_SUPERADMIN_PASSWORD")
        continue
    login_resp = login(username, password)
    if not login_resp:
        print(f"[SKIP] {role_name} 登录失败（{username}）")
        continue
    HDRS = {"Authorization": f"Bearer {login_resp['token']}"}
    print(f"\n=== 角色 {role_name} ===")
    for method, path, params, body, category in ENDPOINTS:
        real_path = path
        for k, v in params.items():
            real_path = real_path.replace(f"{{{k}}}", str(v))
        try:
            r = method_call(method, real_path, body)
        except Exception as e:
            violations.append((role_name, method, real_path, f"EXC {e}"))
            continue
        expect = ROLE_EXPECT[role_name].get(category)
        if expect is None:
            continue
        # 200/400/404 都代表"请求已进入业务层"（授权通过）；401/403 代表被权限拦截
        got_gate = r.status_code in (401, 403)
        expect_gate = expect == 403
        if got_gate != expect_gate:
            violations.append((role_name, method, real_path,
                               f"期望{'拦截' if expect_gate else '放行'}(约{expect}) 实际 {r.status_code} {r.text[:80]}"))
        status_icon = "OK" if got_gate == expect_gate else "VIOLATION"
        if status_icon == "VIOLATION":
            print(f"  [{status_icon}] {method} {real_path} -> {r.status_code}")

print("\n\n========== 权限矩阵违规汇总 ==========")
if not violations:
    print("无违规：4 角色 x 64 端点的拦截/放行全部符合预期")
for v in violations:
    print(f"  [{v[0]}] {v[1]} {v[2]} : {v[3]}")

# ============================================================
print("\n\n========== 数据一致性审计 ==========")
admin_h = {"Authorization": f"Bearer {login('admin', 'admin123')['token']}"}


def get(path):
    return client.get(f"{BASE}{path}", headers=admin_h).json()


def get_all(path: str, **params) -> list[dict]:
    """分页遍历取回全量条目。

    审计脚本必须取全量：`page_size` 有上限（`app/pagination.py` 的 200），
    而「抽样」会让审计结论失真——实测主库订单已 518 条，
    原先写死 `page_size=500` 时**最后 18 条从未被审计过**，
    且脚本还会打印「已全覆盖」，属自欺式通过（审计 #10 / DEBT-27）。
    """
    from app.pagination import MAX_PAGE_SIZE

    items: list[dict] = []
    page_num = 1
    while True:
        query = {**params, "page_num": page_num, "page_size": MAX_PAGE_SIZE}
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        body = get(f"{path}?{qs}")
        items.extend(body["items"])
        if len(items) >= body["total"] or not body["items"]:
            break
        page_num += 1
    return items


issues = []

# 1. 退款单引用的订单存在且属于同租户
refunds = get_all("/api/refunds")
orders = {o["id"]: o for o in get_all("/api/orders")}
for rf in refunds:
    o = orders.get(rf["order_id"])
    if o is None:
        issues.append(f"退款单 {rf['refund_no']} 引用不存在的订单 #{rf['order_id']}")
    elif o["status"] == "refunded" and rf["status"] not in ("refunded", "rejected"):
        issues.append(f"订单 #{o['id']} 已 refunded 但退款单 {rf['refund_no']} 状态为 {rf['status']}")
    elif o["status"] != "refunded" and rf["status"] == "refunded" and rf["qty"] >= o["qty"]:
        issues.append(f"整单退款单 {rf['refund_no']} 已退款但订单 #{o['id']} 状态仍为 {o['status']}")

# 2. 退款金额不超过订单金额比例
for rf in refunds:
    o = orders.get(rf["order_id"])
    if o and rf["amount"] > o["amount"] + 0.01:
        issues.append(f"退款单 {rf['refund_no']} 金额 {rf['amount']} 超过订单总额 {o['amount']}")

# 3. 采购单 ↔ 结算单关联完整性
settlements = get_all("/api/settlements")
st_ids = {s["id"] for s in settlements}
summary = {x["supplier_name"]: x for x in get("/api/settlements/summary")["items"]}
for s in settlements:
    if s["status"] == "paid" and not s.get("paid_at"):
        issues.append(f"结算单 {s['settle_no']} 状态 paid 但无 paid_at")
    if s["status"] != "paid" and s.get("paid_at"):
        issues.append(f"结算单 {s['settle_no']} 有 paid_at 但状态 {s['status']}")

# 4. 结算金额非负 & po_count>0
for s in settlements:
    if s["total_amount"] < 0:
        issues.append(f"结算单 {s['settle_no']} 金额为负")
    if s["po_count"] <= 0:
        issues.append(f"结算单 {s['settle_no']} po_count<=0")

# 5. 订单 source 字段合法值
valid_source = {"seed", "import", "api", "demo", "manual"}
bad = [o["external_no"] for o in orders.values() if o.get("source") not in valid_source]
if bad:
    issues.append(f"{len(bad)} 条订单 source 字段非法: {bad[:5]}")

# 6. BI dashboard 与订单表聚合一致
dash = get("/api/bi/dashboard")
non_refund = [o for o in orders.values() if o["status"] != "refunded"]
api_gmv = round(sum(o["amount"] for o in non_refund), 2)
dash_gmv = float(dash["gmv"])
# 订单已由 get_all 全量取回，故此处必然是全量比对（不再有「抽样」分支）
total_orders = get("/api/orders?page_num=1&page_size=1")["total"]
if len(orders) != total_orders:
    issues.append(f"订单取回 {len(orders)} 条与 total={total_orders} 不一致（分页遍历有缺陷）")
if abs(api_gmv - dash_gmv) > max(1.0, dash_gmv * 0.01):
    issues.append(f"BI GMV {dash_gmv} 与订单明细合计 {api_gmv} 偏差过大")

# 7. 供应商汇总：summary 的供应商都真实存在
sup_names = {s["name"] for s in get("/api/suppliers")["items"]}
for name in summary:
    if name not in sup_names:
        issues.append(f"应付汇总出现未知供应商 {name}")

print("检查项：退款-订单关联/金额上限、结算单状态-时间戳一致、source 合法值、BI GMV 对账、供应商汇总")
if not issues:
    print("数据一致性：未发现不一致")
for i in issues:
    print(f"  [DATA] {i}")

print(f"\n总计：权限违规 {len(violations)} 项，数据不一致 {len(issues)} 项")
