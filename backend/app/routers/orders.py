"""订单路由：列表 / CSV导入导出 / 平台同步（模拟）/ 状态流转。"""
import csv
import io
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import Order, Product, Shop, User
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict
from ..services import mock_market

router = APIRouter(prefix="/orders", tags=["orders"])

_VALID_STATUS = {"pending", "paid", "shipped", "delivered", "refunded"}
_STATUS_CN = {"pending", "paid", "shipped", "delivered", "refunded",
              "待支付", "已付款", "已发货", "已签收", "已退款", "已取消", "cancelled", "canceled"}
_STATUS_MAP = {"待支付": "pending", "已付款": "paid", "已发货": "shipped", "已签收": "delivered",
               "已退款": "refunded", "已取消": "refunded", "cancelled": "refunded",
               "canceled": "refunded"}


class ImportIn(BaseModel):
    csv_text: str
    shop_id: int | None = None      # 指定归属店铺时必须为销售店铺（sales）


class SyncIn(BaseModel):
    platform: str = "shopee"
    count: int = 5


class StatusIn(BaseModel):
    status: str


@router.get("")
def list_orders(platform: str = "", status: str = "", keyword: str = "",
                page_num: int = PageNum, page_size: int = PageSize,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Order).filter(Order.tenant_id == user.tenant_id)
    if platform:
        q = q.filter(Order.platform == platform)
    if status:
        q = q.filter(Order.status == status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(Order.external_no.like(like) | Order.buyer_name.like(like))
    total = q.count()
    items = (q.order_by(Order.created_at.desc())
             .offset((page_num - 1) * page_size).limit(page_size).all())
    return page([to_dict(o) for o in items], total, page_num, page_size)


def _ensure_sales_platform(db: Session, tenant_id: int, platform: str) -> None:
    """按平台同步的 Supply/Sales 守门：货源平台，或该平台命中的店铺均为货源店铺 -> 400。

    订单本身不携带店铺归属时无法区分来源，因此只要平台本身是货源平台（如 1688），
    或租户内该平台没有一家销售店铺，就必须拒绝，避免货源订单混入销售订单。
    """
    from ..services.platform_adapters import ADAPTERS

    cls = ADAPTERS.get(platform)
    label = cls.label if cls else platform
    default_role = cls.role if cls else ("source" if platform == "1688" else "sales")
    if default_role == "source":
        raise HTTPException(
            status_code=400,
            detail=(f"{label} 是货源平台（source）：货源店铺(source)不能同步销售订单，"
                    f"请选择销售店铺（sales）"))
    shops = (db.query(Shop).filter(Shop.tenant_id == tenant_id,
                                   Shop.platform == platform,
                                   Shop.archived_at.is_(None)).all())
    if shops and all(s.role != "sales" for s in shops):
        raise HTTPException(
            status_code=400,
            detail=(f"{label} 命中的店铺均为货源店铺（source）：货源店铺(source)不能同步销售订单，"
                    f"请选择销售店铺（sales）"))


@router.post("/sync")
def sync_orders(body: SyncIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    """仅供显式演示数据生成；真实拉单必须从授权店铺入口执行。

    Supply/Sales 守门：货源平台 / 货源店铺（source）不得作为销售订单来源。
    """
    if not 1 <= body.count <= 50:
        raise HTTPException(status_code=400, detail="count 需在 1-50 之间")
    if not body.platform.startswith("demo:"):
        raise HTTPException(status_code=409,
                            detail="该入口只生成演示订单，请使用 demo:平台名；真实拉单请从已授权店铺执行")
    platform = body.platform.split(":", 1)[1] or "demo"
    _ensure_sales_platform(db, user.tenant_id, platform)
    items = [mock_market.gen_order(db, user.tenant_id, platform) for _ in range(body.count)]
    db.commit()
    return {"synced": len(items), "items": [to_dict(o) for o in items]}


@router.post("/import")
def import_csv(body: ImportIn, user: User = Depends(require_write),
               db: Session = Depends(get_db)):
    """CSV 批量导入订单（平台后台导出格式：表头含 订单号/external_no，金额/amount 等）。

    按订单号去重（已存在则跳过），产品可用 SKU 列关联商品池。
    指定 shop_id 时必须指向销售店铺（sales）：货源店铺导入会被 400 拒绝。
    """
    shop = None
    if body.shop_id is not None:
        from ..services.shop_scope import active_shop

        shop = active_shop(db, user.tenant_id, body.shop_id)
        if not shop:
            raise HTTPException(status_code=404, detail="店铺不存在")
        if shop.role != "sales":
            from ..services.platform_adapters import ADAPTERS

            label = ADAPTERS[shop.platform].label if shop.platform in ADAPTERS else shop.platform
            raise HTTPException(
                status_code=400,
                detail=(f"「{shop.shop_name or label}」是 {label} 货源店铺（source）："
                        f"货源店铺(source)不能同步销售订单，请选择销售店铺（sales）"))
    text = body.csv_text.strip().lstrip("\ufeff")
    if not text:
        raise HTTPException(status_code=400, detail="CSV 内容为空")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    reader = csv.reader(io.StringIO(lines[0] + "\n" + "\n".join(lines[1:])))
    rows = list(reader)
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="CSV 需要表头 + 至少一行数据")

    header = [h.strip().lower() for h in rows[0]]

    def col(*names: str) -> int | None:
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_no = col("external_no", "订单号", "订单编号", "order_no", "order_id")
    i_amount = col("amount", "金额", "销售额", "总价", "total", "revenue")
    if i_no is None or i_amount is None:
        raise HTTPException(status_code=400,
                            detail="CSV 缺少必需列：订单号(external_no) 与 金额(amount)")
    i_platform = col("platform", "平台")
    i_status = col("status", "状态")
    i_qty = col("qty", "数量", "件数")
    i_country = col("country", "国家")
    i_buyer = col("buyer_name", "买家", "买家名", "buyer")
    i_sku = col("sku", "商品sku", "product_sku")
    i_cost = col("cost", "成本")
    i_currency = col("currency", "币种")
    i_date = col("created_at", "下单时间", "时间", "date")

    existing = {(o.platform, o.external_no) for o in db.query(Order.platform, Order.external_no)
                .filter(Order.tenant_id == user.tenant_id).all()}
    sku_map = {p.sku: p for p in db.query(Product)
               .filter(Product.tenant_id == user.tenant_id).all()}
    imported, skipped, errors = 0, 0, []
    for ln, row in enumerate(rows[1:], start=2):
        ext_no = row[i_no].strip() if len(row) > i_no else ""
        try:
            if not ext_no:
                raise ValueError("订单号为空")
            raw_amount = re.sub(r"[^\d.\-]", "", row[i_amount])
            if not raw_amount:
                raise ValueError("金额非法")
            amount = float(raw_amount)
            status = (row[i_status].strip().lower() if i_status is not None and len(row) > i_status else "paid")
            status = _STATUS_MAP.get(status, status)
            if status not in _VALID_STATUS:
                status = "paid"
            qty = int(float(row[i_qty])) if i_qty is not None and len(row) > i_qty else 1
            product = None
            if i_sku is not None and len(row) > i_sku:
                product = sku_map.get(row[i_sku].strip())
            cost = (float(row[i_cost]) if i_cost is not None and len(row) > i_cost
                    and row[i_cost].strip() else round(amount * 0.65, 2))
            created = None
            if i_date is not None and len(row) > i_date and row[i_date].strip():
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%m/%d/%Y"):
                    try:
                        created = datetime.strptime(row[i_date].strip(), fmt)
                        break
                    except ValueError:
                        continue
            platform = ((row[i_platform].strip() if i_platform is not None
                         and len(row) > i_platform and row[i_platform].strip() else "") or "import")
            if platform == "import" and shop is not None:
                platform = shop.platform   # 指定销售店铺时按店铺平台归属
            if (platform, ext_no) in existing:
                skipped += 1
                continue
            currency = (row[i_currency].strip().upper() if i_currency is not None
                        and len(row) > i_currency and row[i_currency].strip() else "USD")
            o = Order(tenant_id=user.tenant_id,
                      shop_id=body.shop_id,
                      platform=platform,
                      external_no=ext_no,
                      product_id=product.id if product else None,
                      qty=qty, amount=round(amount, 2), cost=cost,
                      profit=round(amount - cost, 2), currency=currency,
                      source="import",
                      status=status,
                      country=(row[i_country].strip() if i_country is not None
                               and len(row) > i_country else ""),
                      buyer_name=(row[i_buyer].strip() if i_buyer is not None
                                  and len(row) > i_buyer else ""))
            if created:
                o.created_at = o.updated_at = created
            db.add(o)
            existing.add((platform, ext_no))
            imported += 1
        except (ValueError, IndexError) as e:
            errors.append(f"第{ln}行({ext_no or '无订单号'}): {e}")
    db.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors[:20]}


@router.get("/export")
def export_csv(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """导出订单 CSV（utf-8-sig）。"""
    rows = (db.query(Order).filter(Order.tenant_id == user.tenant_id)
            .order_by(Order.created_at.desc()).limit(5000).all())
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["external_no", "platform", "qty", "amount", "cost", "profit",
                     "currency", "status", "country", "buyer_name", "created_at"])
    for o in rows:
        writer.writerow([o.external_no, o.platform, o.qty, o.amount, o.cost, o.profit,
                         o.currency, o.status, o.country, o.buyer_name,
                         o.created_at.strftime("%Y-%m-%d %H:%M:%S")])
    data = buf.getvalue().encode("utf-8-sig")
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=orders.csv"})


@router.post("/{order_id}/ship")
def ship_order(order_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    """发货：生成物流单号，状态流转为已发货。"""
    o = db.get(Order, order_id)
    if not o or o.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    if o.status != "paid":
        raise HTTPException(status_code=400, detail=f"仅已付款(paid)订单可发货，当前状态 {o.status}")
    o.status = "shipped"
    o.tracking_no = f"SF{int(datetime.utcnow().timestamp() * 1000) % 10 ** 13:013d}"
    o.updated_at = datetime.utcnow()
    db.commit()
    return to_dict(o)


@router.put("/{order_id}/status")
def update_status(order_id: int, body: StatusIn,
                  user: User = Depends(require_write), db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if not o or o.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    if body.status not in _VALID_STATUS:
        raise HTTPException(status_code=400, detail=f"状态必须是 {'/'.join(_VALID_STATUS)}")
    allowed = {
        "pending": {"paid", "refunded"},
        "paid": {"shipped", "refunded"},
        "shipped": {"delivered", "refunded"},
        "delivered": {"refunded"},
        "refunded": set(),
    }
    if body.status != o.status and body.status not in allowed.get(o.status, set()):
        raise HTTPException(status_code=409, detail=f"订单状态不可从 {o.status} 流转到 {body.status}")
    o.status = body.status
    o.updated_at = datetime.utcnow()
    db.commit()
    return to_dict(o)
