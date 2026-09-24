"""本地平台契约沙箱。

仅供开发/CI。启动：uvicorn scripts.platform_contract_sandbox:app --port 8877
适配器通过 ERP_<PLATFORM>_BASE_URL=http://127.0.0.1:8877 指向这里。
请求头 ``X-Contract-Error`` 可模拟 unauthorized/rate_limit/validation 错误。
"""
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(title="ERP Platform Contract Sandbox")


def fail(mode: str | None):
    if mode == "unauthorized":
        raise HTTPException(401, "sandbox token expired")
    if mode == "rate_limit":
        raise HTTPException(429, "sandbox rate limit")
    if mode == "validation":
        raise HTTPException(400, "sandbox field validation failed")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def contract(path: str, request: Request,
                   x_contract_error: str | None = Header(default=None)):
    fail(x_contract_error)
    body = await request.body()
    if path.endswith("token") or "/token/" in path or "/auth/token/" in path:
        return {"access_token": "sandbox-access", "refresh_token": "sandbox-refresh",
                "expires_in": 3600, "data": {"access_token": "sandbox-access",
                "refresh_token": "sandbox-refresh", "expires_in": 3600}}
    if "images/upload" in path:
        return {"code": 0, "data": {"uri": "sandbox-image-uri"}}
    if path.endswith("global_products"):
        return {"code": 0, "data": {"global_product_id": "gp-sandbox-1"}}
    if path.endswith("/publish"):
        return {"code": 0, "data": {"product_ids": ["local-sandbox-1"]}}
    if "inventory_item/" in path:
        return {}
    if path.endswith("sell/inventory/v1/offer"):
        return {"offerId": "offer-sandbox-1"}
    if "sell/inventory/v1/offer/" in path and path.endswith("publish"):
        return {"listingId": "listing-sandbox-1"}
    if path.endswith("v3/feeds") and request.method == "POST":
        return {"feedId": "feed-sandbox-1"}
    if path.endswith("v3/feeds"):
        return {"results": [{"feedId": "feed-sandbox-1", "feedStatus": "PROCESSED",
                              "itemsSucceeded": 1, "itemsFailed": 0}]}
    if path.endswith("v3/orders"):
        return {"list": {"elements": {"order": []}}}
    if path.endswith("orders/get"):
        return {"code": "0", "data": {"orders": []}}
    if path.endswith("product/create"):
        return {"code": "0", "data": {"item_id": "lazada-sandbox-1"}}
    return {"ok": True, "path": path, "method": request.method,
            "received_bytes": len(body)}
