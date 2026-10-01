"""物流计费服务：计费重 × 费率 + 首重 + 附加（P0-2）。

替换原先「一条线性公式」的物流成本口径：

    logistics_cny = logistics_base + logistics_per_kg * weight      # 旧口径

真实跨境物流成本至少包含头程/尾程分离、体积重（泡货按体积重计费）、
分区费率、海外仓/FBA 费用与燃油/旺季附加。本模块把物流升级为
「可配置费率表 + 报价核算」：

    - 计费重 = max(实重, 体积重)，体积重 = 长×宽×高 / 体积系数（默认 6000，空运口径）；
    - 支持按公斤（首重 + 续重）、按立方（CBM）、按件三种计费方式；
    - 叠加燃油附加率与旺季附加率。

兼容：当没有任何路由命中时，回退到旧线性公式（``rules.logistics_base`` +
``rules.logistics_per_kg`` × 实重），保证既有数据与断言口径不变。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import LogisticsRoute
from .regions import region_code

# 参考路由（代码兜底，按目的国生效；数据库行优先）。仅在调用方给出目的国时命中，
# 因此不会改变「未指定目的国」时的既有线性口径。
DEFAULT_LOGISTICS_ROUTES: tuple[dict, ...] = (
    {
        "name": "美国-空运直邮小包", "channel_type": "direct_mail", "destination_country": "US",
        "billing_method": "per_kg", "first_weight_kg": 0.5, "first_weight_fee": 62.0,
        "additional_per_kg": 48.0, "volumetric_divisor": 6000, "min_charge": 62.0,
        "fuel_surcharge_rate": 0.0, "peak_surcharge_rate": 0.0,
        "note": "参考值，须按实际货代报价维护；美国已无 de minimis 免税",
    },
    {
        "name": "欧盟-空运直邮小包", "channel_type": "direct_mail", "destination_country": "EU",
        "billing_method": "per_kg", "first_weight_kg": 0.5, "first_weight_fee": 58.0,
        "additional_per_kg": 45.0, "volumetric_divisor": 6000, "min_charge": 58.0,
        "fuel_surcharge_rate": 0.0, "peak_surcharge_rate": 0.0,
        "note": "参考值，须按实际货代报价维护",
    },
    {
        "name": "欧盟-海运头程+海外仓", "channel_type": "overseas_warehouse",
        "destination_country": "EU", "billing_method": "per_cbm", "per_cbm": 780.0,
        "per_item": 6.5, "volumetric_divisor": 6000, "min_charge": 300.0,
        "fuel_surcharge_rate": 0.0, "peak_surcharge_rate": 0.0,
        "note": "头程按 CBM 计费 + 海外仓操作费/件；适合大件泡货",
    },
)

DIMENSION_KEYS = (("length_cm", "length"), ("width_cm", "width"), ("height_cm", "height"))


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dims(attrs: dict) -> tuple[float, float, float]:
    """从商品属性提取长宽高（厘米）。兼容 ``dim_cm: [l, w, h]`` 与分字段两种写法。"""
    dims = (attrs or {}).get("dim_cm")
    if isinstance(dims, (list, tuple)) and len(dims) == 3:
        return (_num(dims[0]), _num(dims[1]), _num(dims[2]))
    values = []
    for primary, alias in DIMENSION_KEYS:
        values.append(_num((attrs or {}).get(primary) or (attrs or {}).get(alias)))
    return (values[0], values[1], values[2])


def volumetric_weight(attrs: dict, divisor: int = 6000) -> float:
    """体积重（kg）：长×宽×高(cm) / 体积系数；缺尺寸或系数非法时返回 0。"""
    length, width, height = _dims(attrs)
    if length <= 0 or width <= 0 or height <= 0 or divisor <= 0:
        return 0.0
    return round(length * width * height / float(divisor), 4)


def actual_weight(attrs: dict) -> float:
    """实重（kg）；与旧口径一致，缺省 0.3kg。"""
    return _num((attrs or {}).get("weight_kg")) or 0.3


def cbm(attrs: dict) -> float:
    """体积（立方米）。"""
    length, width, height = _dims(attrs)
    return round(length * width * height / 1_000_000.0, 6)


def _route_dict(row) -> dict:
    return {
        "id": row.id, "name": row.name, "channel_type": row.channel_type,
        "destination_country": row.destination_country or "",
        "billing_method": row.billing_method,
        "first_weight_kg": _num(row.first_weight_kg),
        "first_weight_fee": _num(row.first_weight_fee),
        "additional_per_kg": _num(row.additional_per_kg),
        "per_cbm": _num(row.per_cbm), "per_item": _num(row.per_item),
        "volumetric_divisor": int(row.volumetric_divisor or 6000),
        "min_charge": _num(row.min_charge),
        "fuel_surcharge_rate": _num(row.fuel_surcharge_rate),
        "peak_surcharge_rate": _num(row.peak_surcharge_rate),
        "active": bool(row.active), "note": row.note or "",
        "source": "tenant" if row.tenant_id is not None else "platform",
    }


def resolve_route(db: Session, tenant_id: int | None, *, destination_country: str = "",
                  channel_type: str = "", route_id: int | None = None,
                  at: datetime | None = None) -> dict | None:
    """解析适用的物流路由：route_id 精确指定 > 目的国 + 渠道 > 目的国 > 渠道 > 通用。"""
    at = at or datetime.utcnow()
    # 目的国与关税共用同一套归一化（欧盟成员国统一按 EU 路由），避免
    # "关税按 EU 算、物流按 DE 找不到路由"这类口径分裂。
    country = region_code(destination_country)
    channel = (channel_type or "").strip()
    if route_id and db is not None:
        row = db.get(LogisticsRoute, route_id)
        if row and (tenant_id is None or row.tenant_id in (None, tenant_id)):
            return _route_dict(row)
    rows = []
    if db is not None:
        query = db.query(LogisticsRoute).filter(LogisticsRoute.active.is_(True))
        if tenant_id is None:
            query = query.filter(LogisticsRoute.tenant_id.is_(None))
        else:
            query = query.filter(LogisticsRoute.tenant_id.is_(None)
                                 | (LogisticsRoute.tenant_id == tenant_id))
        rows = [row for row in query.all()
                if (not row.effective_from or row.effective_from <= at)
                and not (row.effective_to and row.effective_to <= at)]
    if rows:
        pool = [_route_dict(row) for row in rows]
        for candidate in pool:
            if (country and candidate["destination_country"] == country
                    and (not channel or candidate["channel_type"] == channel)):
                return candidate
        for candidate in pool:
            if country and candidate["destination_country"] == country:
                return candidate
        for candidate in pool:
            if channel and candidate["channel_type"] == channel and not candidate["destination_country"]:
                return candidate
        for candidate in pool:
            if not candidate["destination_country"]:
                return candidate
    for item in DEFAULT_LOGISTICS_ROUTES:
        if country and item["destination_country"] == country and (
                not channel or item["channel_type"] == channel):
            return dict(item) | {"id": None, "active": True, "source": "default"}
    return None


def quote(db: Session, tenant_id: int | None, attrs: dict, *, destination_country: str = "",
          channel_type: str = "", route_id: int | None = None, qty: int = 1,
          rules: dict | None = None, at: datetime | None = None) -> dict:
    """物流报价（人民币）。无路由命中时回退旧线性公式，``source="legacy"``。"""
    qty = max(int(qty or 1), 1)
    route = resolve_route(db, tenant_id, destination_country=destination_country,
                          channel_type=channel_type, route_id=route_id, at=at)
    weight = actual_weight(attrs)
    if route is None:
        rules = rules or {}
        base = _num(rules.get("logistics_base", 18.0)) + _num(rules.get("logistics_per_kg", 8.0)) * weight
        total = round(base, 2)
        return {
            "route_id": None, "name": "旧线性口径（未配置路由）", "channel_type": "",
            "billing_method": "per_kg", "source": "legacy",
            "actual_weight_kg": round(weight, 4), "volumetric_weight_kg": 0.0,
            "billing_weight_kg": round(weight, 4), "cbm": cbm(attrs),
            "base_cny": total, "surcharge_cny": 0.0, "total_cny": total,
            "breakdown": [{"item": "基础运费", "amount": total}],
        }
    volume_weight = volumetric_weight(attrs, route["volumetric_divisor"])
    billed = max(weight, volume_weight)
    volume = cbm(attrs)
    method = route["billing_method"]
    if method == "per_cbm":
        base = route["per_cbm"] * volume * qty + route["per_item"] * qty
    elif method == "per_item":
        base = route["per_item"] * qty
    else:
        extra = max(0.0, billed - route["first_weight_kg"])
        base = route["first_weight_fee"] + route["additional_per_kg"] * extra
    base = max(base, route["min_charge"])
    surcharge = base * (route["fuel_surcharge_rate"] + route["peak_surcharge_rate"])
    total = round(base + surcharge, 2)
    return {
        "route_id": route.get("id"), "name": route["name"],
        "channel_type": route["channel_type"], "billing_method": method,
        "source": route.get("source", "route"),
        "actual_weight_kg": round(weight, 4),
        "volumetric_weight_kg": round(volume_weight, 4),
        "billing_weight_kg": round(billed, 4), "cbm": volume,
        "base_cny": round(base, 2), "surcharge_cny": round(surcharge, 2),
        "total_cny": total,
        "breakdown": [{"item": "基础运费", "amount": round(base, 2)},
                      {"item": "燃油/旺季附加", "amount": round(surcharge, 2)}],
    }


def list_routes(db: Session, tenant_id: int | None, include_defaults: bool = True) -> list[dict]:
    """列出可见物流路由（租户自有 + 平台内置 + 未被覆盖的代码兜底参考值）。"""
    query = db.query(LogisticsRoute)
    if tenant_id is None:
        query = query.filter(LogisticsRoute.tenant_id.is_(None))
    else:
        query = query.filter(LogisticsRoute.tenant_id.is_(None)
                             | (LogisticsRoute.tenant_id == tenant_id))
    items = [_route_dict(row) for row in
             query.order_by(LogisticsRoute.destination_country, LogisticsRoute.name).all()]
    if include_defaults:
        keys = {(item["destination_country"], item["channel_type"]) for item in items}
        for item in DEFAULT_LOGISTICS_ROUTES:
            if (item["destination_country"], item["channel_type"]) in keys:
                continue
            items.append(dict(item) | {"id": None, "active": True, "source": "default"})
    return items
