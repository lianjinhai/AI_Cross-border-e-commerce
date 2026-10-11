"""店铺授权路由：OAuth 授权链接 / 授权码交换 / 回调 / 真实拉单 / 演示数据清理。"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..auth import (
    get_current_user,
    is_impersonating_user,
    require_admin,
    require_permission,
    require_platform_admin,
)
from ..db import get_db
from ..models import Listing, Product, Shop, User, utcnow
from ..serialize import to_dict
from ..services import platforms
from ..services.regions import store_market
from ..services.store_scope import StoreScopeError, resolve_store_scope
from ..services.workspace_context import resolve_workspace_context

require_write = require_permission("workspace:write", ("admin", "operator"))


def _scope(db, user):
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        return resolve_store_scope(db, ctx)
    except StoreScopeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

router = APIRouter(prefix="/shops", tags=["shops"])


class ShopContextIn(BaseModel):
    market: str | None = Field(default=None, max_length=64)
    store_type: str | None = Field(default=None, max_length=64)
    account_type: str | None = Field(default=None, max_length=64)
    business_mode: str | None = Field(default=None, max_length=64)
    fulfillment_mode: Literal["", "DROPSHIP", "PLATFORM_STOCK", "SELF_STOCK", "FACTORY_DIRECT"] | None = None

    @field_validator("market")
    @classmethod
    def validate_market(cls, value):
        if value is None or not value.strip():
            return value if value is None else ""
        normalized = store_market(value)
        if not normalized:
            raise ValueError("请选择当前支持的具体目标国家，不能使用 EU 区域或未知代码")
        return normalized


class ShopIn(ShopContextIn):
    platform: str
    role: str = ""                 # source=货源 / sales=销售；缺省按平台推导（1688=source 其余=sales）
    shop_name: str = ""
    shop_id: str = ""
    app_key: str = ""
    app_secret: str = ""
    is_demo: bool = False


class ShopUpdate(ShopContextIn):
    shop_name: str | None = None
    shop_id: str | None = None
    app_key: str | None = None
    app_secret: str | None = None


class CodeIn(BaseModel):
    code: str


@router.get("")
def list_shops(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..services.platform_adapters import ADAPTERS

    rows = (_scope(db, user).filter(db.query(Shop), Shop.id).filter(Shop.tenant_id == user.tenant_id)
            .filter(Shop.archived_at.is_(None))
            .order_by(Shop.id).all())
    items = []
    for s in rows:
        d = to_dict(s, exclude=["app_secret", "access_token", "refresh_token"])
        adapter_cls = ADAPTERS.get(s.platform)
        d["platform_label"] = adapter_cls.label if adapter_cls else s.platform
        d["capabilities"] = ({
            "can_order_sync": adapter_cls.can_order_sync,
            "can_publish": adapter_cls.can_publish,
            "can_refresh": adapter_cls.can_refresh,
            "can_listing_readiness": adapter_cls.can_listing_readiness,
        } if adapter_cls else {})
        d["token_valid"] = bool(s.access_token) and (
            s.token_expire_at is None or s.token_expire_at > utcnow())
        items.append(d)
    return {"items": items, "total": len(items)}


@router.post("")
def create_shop(body: ShopIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    from ..services.platform_adapters import ADAPTERS, get_adapter

    if _scope(db, user).shop_ids is not None:
        raise HTTPException(status_code=403, detail="受限店铺成员不能创建范围外的新店铺")

    if body.platform not in ADAPTERS:
        raise HTTPException(status_code=400,
                            detail=f"平台必须是 {'/'.join(ADAPTERS)}")
    # 角色必须明确：显式传入 source/sales，缺省按平台推导（1688=货源，其余=销售）
    role = body.role or ADAPTERS[body.platform].role
    if role not in ("source", "sales"):
        raise HTTPException(status_code=400, detail="role 必须是 source（货源）或 sales（销售）")
    data = body.model_dump(exclude_none=True)
    data["role"] = role
    s = Shop(tenant_id=user.tenant_id, **data)
    if not body.shop_name:
        s.shop_name = f"{ADAPTERS[body.platform].label}{'货源' if role == 'source' else '销售'}店铺"
    db.add(s)
    db.commit()
    out = to_dict(s, exclude=["app_secret", "access_token", "refresh_token"])
    out["capabilities"] = {
        "can_order_sync": get_adapter(db, s).can_order_sync,
        "can_publish": get_adapter(db, s).can_publish,
        "can_refresh": get_adapter(db, s).can_refresh,
    }
    return out


@router.put("/{shop_id}")
def update_shop(shop_id: int, body: ShopUpdate,
                user: User = Depends(require_write), db: Session = Depends(get_db)):
    s = _owned(db, user, shop_id)
    if body.shop_name is not None and body.shop_name != "":
        s.shop_name = body.shop_name
    if body.shop_id is not None:
        s.shop_id = body.shop_id
    if body.app_key is not None and body.app_key != "":
        s.app_key = body.app_key
    if body.app_secret:  # 空串=不修改密钥
        s.app_secret = body.app_secret
    for name in ("market", "store_type", "account_type", "business_mode", "fulfillment_mode"):
        value = getattr(body, name)
        if value is not None:
            setattr(s, name, value)
    db.commit()
    return to_dict(s, exclude=["app_secret", "access_token", "refresh_token"])


@router.delete("/{shop_id}")
def delete_shop(shop_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    """归档店铺（软删除）：清空凭证并置 archived_at，不物理删除。

    为什么不再物理删除：orders / purchase_orders / platform_publish_attempts /
    platform_settlement_records / oauth_states 均引用 shops.id。物理删除会
    ① 触发外键约束失败（IntegrityError → 500）；② 即便级联，也会抹掉订单与
    采购单的店铺归属，破坏财务对账与审计留痕。归档后店铺从列表与所有可写入
    口隐藏，历史业务数据保持完整可追溯。
    """
    s = _owned(db, user, shop_id)
    if s.archived_at is None:
        s.archived_at = utcnow()
    # 凭证即时失效：归档店铺不得再用于任何平台调用。
    s.access_token = ""
    s.refresh_token = ""
    s.app_secret = ""
    s.status = "expired"
    s.auth_message = "店铺已归档（删除）：授权与凭证已清除，历史订单/采购单仍保留"
    db.commit()
    return {"ok": True}


@router.get("/{shop_id}/authorize_url")
def authorize_url(shop_id: int, user: User = Depends(require_write),
                  db: Session = Depends(get_db)):
    """生成平台官方授权页跳转地址（真实 URL，需先填 App Key）。"""
    s = _owned(db, user, shop_id)
    try:
        return {"authorize_url": platforms.build_authorize_url(db, s),
                "manual_hint": "浏览器打开授权链接 → 登录并确认授权 → 平台展示授权码(code)，"
                               "复制回本页「粘贴授权码」完成换 token（本地无公网回调时的标准做法）"}
    except platforms.PlatformError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/callback/{platform}/{shop_id}")
def oauth_callback(platform: str, shop_id: int, code: str = "",
                   error: str = "", state: str = "", db: Session = Depends(get_db)):
    """平台授权回调（有公网回调地址时平台跳回此处）。"""
    s = db.get(Shop, shop_id)
    if not s or s.platform != platform:
        raise HTTPException(status_code=404, detail="店铺不存在")
    try:
        platforms.consume_oauth_state(db, s, state)
    except platforms.PlatformError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if error:
        s.status, s.auth_message = "failed", f"授权被拒绝: {error}"
        db.commit()
        return RedirectResponse("/shops?auth=failed")
    try:
        platforms.exchange_code(db, s, code)
    except platforms.PlatformError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RedirectResponse("/shops?auth=success")


@router.post("/{shop_id}/exchange_code")
def exchange_code(shop_id: int, body: CodeIn,
                  user: User = Depends(require_write), db: Session = Depends(get_db)):
    """手动粘贴授权码换 token（本地开发标准流程，与自动回调等价）。"""
    s = _owned(db, user, shop_id)
    if not body.code.strip():
        raise HTTPException(status_code=400, detail="授权码不能为空")
    try:
        platforms.exchange_code(db, s, body.code.strip())
    except platforms.PlatformError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "status": s.status, "message": s.auth_message,
            "expire_at": s.token_expire_at.strftime("%Y-%m-%d %H:%M:%S") if s.token_expire_at else None}


@router.post("/{shop_id}/refresh")
def refresh(shop_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    s = _owned(db, user, shop_id)
    try:
        platforms.refresh_token(db, s)
    except platforms.PlatformError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "status": s.status}


@router.post("/{shop_id}/sync_orders")
def sync_orders(shop_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    """从授权店铺真实拉单。未授权 -> 400 引导授权；演示店铺 -> 模拟数据。

    Supply/Sales 守门：只有销售店铺（sales）可以拉销售订单，货源店铺（source，如 1688）
    的订单属于采购/代发链路，禁止作为销售订单导入。
    """
    s = _owned(db, user, shop_id)
    if s.role != "sales":
        from ..services.platform_adapters import ADAPTERS

        label = ADAPTERS[s.platform].label if s.platform in ADAPTERS else s.platform
        raise HTTPException(
            status_code=400,
            detail=(f"「{s.shop_name or label}」是 {label} 货源店铺（source）："
                    f"货源店铺(source)不能同步销售订单，请选择销售店铺（sales）"))
    try:
        if s.is_demo:
            from ..services import mock_market

            items = [mock_market.gen_order(db, user.tenant_id, s.platform) for _ in range(5)]
            db.commit()
            return {"synced": len(items), "source": "demo", "items": [to_dict(o) for o in items]}
        created = platforms.sync_orders(db, user.tenant_id, s)
        return {"synced": len(created), "source": "api",
                "items": [to_dict(o) for o in created]}
    except platforms.PlatformError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{shop_id}/listing_readiness/{listing_id}")
def listing_readiness(shop_id: int, listing_id: int,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """真实平台只读预检；不创建草稿、不上传图片、不发布商品。"""
    s = _owned(db, user, shop_id)
    listing = db.get(Listing, listing_id)
    if not listing or listing.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Listing 不存在")
    product = db.get(Product, listing.product_id)
    if not product or product.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    try:
        return platforms.listing_readiness(db, s, listing, product)
    except platforms.PlatformError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{shop_id}/submissions/{submission_id}")
def submission_status(shop_id: int, submission_id: str,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """查询 Walmart 等异步商品提交的处理状态；提交成功不等于上架成功。"""
    s = _owned(db, user, shop_id)
    try:
        return platforms.submission_status(db, s, submission_id)
    except platforms.PlatformError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/platforms")
def platforms_meta(user: User = Depends(get_current_user)):
    """平台能力清单与授权差异说明（前端据此禁用不可用操作）。"""
    return {"items": platforms.platform_meta()}


@router.get("/platform_rules")
def rules_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """各平台规则包（版本/违禁词数/禁售类目/限流/要点）——避免封店的底线配置。"""
    from ..services import platform_rules

    return {"items": platform_rules.all_rules_overview(db)}


@router.post("/platform_rules/{platform}/check_updates")
def rules_check(platform: str, user: User = Depends(require_platform_admin),
                db: Session = Depends(get_db)):
    """检查并应用平台规则更新（配置 ERP_RULES_URL 远程源后自动同步）。"""
    from ..services import platform_rules

    return platform_rules.check_updates(db, platform)


@router.get("/category-mappings")
def list_mappings(platform: str = "", user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    from ..models import CategoryMapping

    q = db.query(CategoryMapping).filter(CategoryMapping.tenant_id == user.tenant_id)
    if platform:
        q = q.filter(CategoryMapping.platform == platform)
    rows = q.order_by(CategoryMapping.id).all()
    return {"items": [to_dict(r) for r in rows], "total": len(rows)}


class MappingIn(BaseModel):
    platform: str
    system_category: str
    platform_category_id: str
    note: str = ""


@router.post("/category-mappings")
def create_mapping(body: MappingIn, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    from ..models import CategoryMapping
    from ..services.platform_adapters import ADAPTERS

    if body.platform not in ADAPTERS:
        raise HTTPException(status_code=400, detail="平台不合法")
    row = CategoryMapping(tenant_id=user.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    return to_dict(row)


@router.delete("/category-mappings/{mapping_id}")
def delete_mapping(mapping_id: int, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    from ..models import CategoryMapping

    m = db.get(CategoryMapping, mapping_id)
    if not m or m.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="映射不存在")
    db.delete(m)
    db.commit()
    return {"ok": True}


@router.post("/purge_demo_data")
def purge_demo_data(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """清空全部演示数据（种子/模拟），保留账号、设置与店铺授权配置。"""
    if _scope(db, user).shop_ids is not None:
        raise HTTPException(status_code=403, detail="店铺受限成员不能执行全 Workspace 数据清理")
    from ..services.tenant_data_purge import purge_tenant_demo_data

    counts = purge_tenant_demo_data(db, user.tenant_id)
    return {"ok": True, "deleted": counts,
            "hint": "演示数据已清空。现在可以：URL 采集真实商品 / 授权店铺拉真实订单 / CSV 导入历史数据。"}


def _owned(db: Session, user: User, shop_id: int) -> Shop:
    try:
        _scope(db, user).require(shop_id)
    except StoreScopeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    s = db.get(Shop, shop_id)
    if not s or s.tenant_id != user.tenant_id or s.archived_at is not None:
        raise HTTPException(status_code=404, detail="店铺不存在")
    return s
