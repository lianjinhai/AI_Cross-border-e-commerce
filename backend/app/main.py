"""应用入口：FastAPI + 全量路由 + 静态托管前端构建产物。

启动：python -m uvicorn app.main:app --port 8000  （或 python app/main.py）
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .db import init_db
from .proxy_headers import install_proxy_headers_middleware
from .routers import (
    actions,
    admin,
    ads,
    ai,
    alerts,
    auth,
    bi,
    business_profiles,
    compliance,
    cross_border,
    discovery,
    factory_network,
    finance,
    knowledge,
    launch,
    listings,
    me,
    orders,
    pricing,
    product_assets,
    product_channels,
    products,
    purchases,
    refunds,
    schedules,
    settlements,
    shops,
    suppliers,
    support,
    workflows,
)
from .seed import ensure_listing_review_workflow, seed_if_empty
from .services.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_if_empty()
    from .db import SessionLocal
    from .seed import _ensure_admin_password, _ensure_superadmin
    with SessionLocal() as db:
        _ensure_superadmin(db)
        _ensure_admin_password(db)
        ensure_listing_review_workflow(db)
    start_scheduler()
    from .workflows.engine import recover_incomplete_runs
    recover_incomplete_runs()
    # 平台上线流程的启动扫描（AC-8.5/D12）：以系统身份回收未结束流程的 RUNNING 步骤，
    # 不依赖任何 manage 用户刷新（系统级确定性）。
    from .workflows.launch_recovery import recover_launch_steps
    with SessionLocal() as db:
        recover_launch_steps(db)
    yield


def create_app() -> FastAPI:
    config.validate_production_settings()
    app = FastAPI(title=config.settings.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.settings.cors_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    # 转发头处理（安全边界，实现与前提见 app/proxy_headers.py）。
    # 放在 CORS 之后 = 成为最外层，信任边界贴在最边缘。
    install_proxy_headers_middleware(app)

    for m in (auth, products, product_assets, product_channels, discovery, suppliers, listings, compliance, actions,
              pricing, ads, orders, support, bi, workflows, launch, knowledge, ai,
              schedules, purchases, shops, admin, refunds, settlements, finance,
              factory_network, cross_border, me, alerts,
              business_profiles):
        app.include_router(m.router, prefix="/api")

    @app.get("/api/health", include_in_schema=False)
    def health():
        return {"ok": True, "app": config.settings.app_name}

    @app.get("/api/placeholder/{seed}.svg", include_in_schema=False)
    def placeholder(seed: str):
        """本地商品占位图（SVG）：保证内网/离线环境图片必定可显示。"""
        import hashlib

        h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
        hue1, hue2 = h % 360, (h // 360) % 360
        label = seed[-6:].upper()
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="hsl({hue1},55%,72%)"/>
<stop offset="100%" stop-color="hsl({hue2},55%,52%)"/>
</linearGradient></defs>
<rect width="400" height="400" fill="url(#g)"/>
<circle cx="{100 + h % 200}" cy="{90 + (h // 7) % 120}" r="70" fill="rgba(255,255,255,0.25)"/>
<rect x="120" y="230" width="160" height="120" rx="12" fill="rgba(255,255,255,0.35)"/>
<text x="200" y="300" font-size="30" font-family="Arial" fill="rgba(255,255,255,0.9)"
  text-anchor="middle" font-weight="bold">{label}</text>
</svg>"""
        from fastapi.responses import Response as _Resp

        return _Resp(svg, media_type="image/svg+xml",
                     headers={"Cache-Control": "max-age=86400"})

    dist = config.settings.frontend_dist
    if os.path.isdir(dist):
        assets = os.path.join(dist, "assets")
        if os.path.isdir(assets):
            # 静态资源文件名含内容 hash（Vite 产物），可长缓存：
            # 内容变化必然换名，不会出现"旧版被缓存住"的问题。
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        # 入口 HTML 必须每次校验：它是 chunk 引用的唯一来源，
        # 若被缓存，用户会长期停留在旧版前端（含旧权限逻辑），
        # 表现为"后端已修复但界面没变"（排查中实际遇到）。
        _NO_CACHE = {"Cache-Control": "no-cache, must-revalidate", "Pragma": "no-cache"}

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str, request: Request):
            # SPA 兜底只服务前端路由；任何疑似 API 或路径穿越的请求一律 JSON 404。
            # 注意：部分客户端（如 httpx）会先规范化 ".."，服务端看到的 raw_path 可能
            # 已不含 "/api" 前缀，故同时校验 full_path 与原始路径，并显式拦截 ".."。
            raw_path = request.url.path
            if (raw_path.startswith("/api") or raw_path.startswith("/docs")
                    or raw_path.startswith("/openapi")
                    or ".." in raw_path or ".." in full_path
                    or full_path.startswith("api") or full_path.startswith("openapi")):
                raise HTTPException(status_code=404, detail="Not Found")
            candidate = os.path.normpath(os.path.join(dist, full_path))
            if full_path and candidate.startswith(dist) and os.path.isfile(candidate):
                # 非 assets 的其它静态文件（favicon 等）：短缓存
                return FileResponse(candidate, headers={"Cache-Control": "max-age=3600"})
            index = os.path.join(dist, "index.html")
            if os.path.isfile(index):
                return FileResponse(index, headers=_NO_CACHE)
            raise HTTPException(status_code=404, detail="前端未构建")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.settings.host, port=config.settings.port)
