"""平台服务层（薄壳）：统一入口分发到各平台适配器。

业务代码只 import 本模块，不直接接触各平台差异。
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from ..models import OAuthState, Order, Shop
from .platform_adapters import PlatformError, PublishResult, get_adapter, platform_meta

__all__ = ["PLATFORMS", "PlatformError", "build_authorize_url", "exchange_code",
           "refresh_token", "sync_orders", "publish_to_shop", "platform_meta",
           "listing_readiness", "submission_status", "demo_publish"]


def PLATFORMS() -> list[dict]:
    """平台能力清单（函数化避免与旧的 dict 常量混淆）。"""
    return platform_meta()


def build_authorize_url(db: Session, shop: Shop) -> str:
    """生成绑定店铺的一次性 OAuth state，并覆盖适配器中的占位 state。"""
    raw_state = secrets.token_urlsafe(32)
    db.add(OAuthState(tenant_id=shop.tenant_id, shop_id=shop.id,
                      state_hash=hashlib.sha256(raw_state.encode()).hexdigest(),
                      expires_at=datetime.utcnow() + timedelta(minutes=10)))
    db.commit()
    parts = urlsplit(get_adapter(db, shop).authorize_url())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["state"] = raw_state
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def consume_oauth_state(db: Session, shop: Shop, raw_state: str) -> None:
    if not raw_state:
        raise PlatformError("OAuth state 缺失，请重新发起授权")
    digest = hashlib.sha256(raw_state.encode()).hexdigest()
    row = db.query(OAuthState).filter(OAuthState.state_hash == digest,
                                      OAuthState.shop_id == shop.id,
                                      OAuthState.tenant_id == shop.tenant_id).first()
    if not row or row.consumed_at is not None or row.expires_at < datetime.utcnow():
        raise PlatformError("OAuth state 无效、已过期或已使用，请重新发起授权")
    row.consumed_at = datetime.utcnow()
    db.commit()


def exchange_code(db: Session, shop: Shop, code: str) -> Shop:
    adapter = get_adapter(db, shop)
    if not (shop.app_key and shop.app_secret):
        raise PlatformError("请先在店铺设置中填写 App Key / App Secret")
    token = adapter.exchange_code(code)
    if not token.access_token:
        raise PlatformError("平台未返回 access_token，请检查授权码是否已使用/过期")
    shop.access_token = token.access_token
    shop.refresh_token = token.refresh_token
    if token.raw.get("shop_cipher"):
        shop.shop_id = token.raw["shop_cipher"]
    shop.token_expire_at = datetime.utcnow() + timedelta(seconds=token.expires_in)
    shop.status, shop.auth_message = "authorized", "授权成功"
    db.commit()
    return shop


def refresh_token(db: Session, shop: Shop) -> Shop:
    adapter = get_adapter(db, shop)
    if not adapter.can_refresh:
        raise PlatformError(f"{adapter.label} 不支持 token 刷新，请重新授权")
    token = adapter.refresh()
    shop.access_token = token.access_token
    if token.refresh_token:
        shop.refresh_token = token.refresh_token
    shop.token_expire_at = datetime.utcnow() + timedelta(seconds=token.expires_in)
    shop.status = "authorized"
    db.commit()
    return shop


def sync_orders(db: Session, tenant_id: int, shop: Shop) -> list[Order]:
    """真实拉单：适配器输出规范化订单 -> 落库（按单号去重）。"""
    if shop.status != "authorized":
        raise PlatformError(f"店铺未授权（当前 {shop.status}），请先完成 OAuth 授权")
    adapter = get_adapter(db, shop)
    if not adapter.can_order_sync:
        raise PlatformError(f"{adapter.label} 的拉单协议尚未接入")
    orders = adapter.fetch_orders()
    created = []
    for n in orders:
        o = db.query(Order).filter(Order.tenant_id == tenant_id, Order.shop_id == shop.id,
                                   Order.platform == shop.platform,
                                   Order.external_no == n.external_no).first()
        if o:
            # 平台订单会继续发生付款、取消、发货、签收和退款变化，不能只拉新增。
            o.qty, o.amount, o.currency = n.qty, n.amount, n.currency
            o.status, o.country, o.buyer_name = n.status, n.country, n.buyer_name
            o.source = "api"
            continue
        o = Order(tenant_id=tenant_id, shop_id=shop.id, platform=shop.platform,
                  external_no=n.external_no, qty=n.qty, amount=n.amount,
                  cost=0, profit=0, currency=n.currency, status=n.status,
                  country=n.country, buyer_name=n.buyer_name, source="api")
        db.add(o); created.append(o)
    db.commit()
    return created


def publish_to_shop(db: Session, shop: Shop, listing, product, *, resume=None, checkpoint=None) -> PublishResult:
    """上架到销售平台店铺：适配器真实推品（前置校验+协议调用）。"""
    if shop.role != "sales":
        raise PlatformError(f"{shop.platform} 是货源平台（source），不能作为上架目标")
    return get_adapter(db, shop).publish_listing(listing, product, resume=resume, checkpoint=checkpoint)


def listing_readiness(db: Session, shop: Shop, listing, product) -> dict:
    """只读校验平台实时要求；不会创建草稿或发布商品。"""
    if shop.role != "sales":
        raise PlatformError(f"{shop.platform} 是货源平台，不能执行销售上架预检")
    adapter = get_adapter(db, shop)
    if not adapter.can_listing_readiness:
        raise PlatformError(f"{adapter.label} 尚未接入真实上架预检")
    return adapter.listing_readiness(listing, product)


def submission_status(db: Session, shop: Shop, submission_id: str) -> dict:
    """查询异步发布状态（目前用于 Walmart Feed）。"""
    return get_adapter(db, shop).submission_status(submission_id)


def demo_publish(listing, product) -> PublishResult:
    """演示店铺：模拟平台返回（不调用外部 API，来源标记 demo）。"""
    ext = f"demo-{listing.platform}-{listing.id:06d}"
    return PublishResult(external_id=ext, raw={"demo": True})
