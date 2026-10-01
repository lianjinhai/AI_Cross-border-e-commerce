"""平台费率服务：平台 × 类目 × 站点 × 生效期（P1-6）。

原先平台佣金是硬编码在代码里的一个数字（``DEFAULT_FEES = {"shopee": 0.06, ...}``），
平台一改费率就得改代码发版，而且**用一个数字代表一个平台的费率结构**必然偏：
真实费率为「佣金 + 交易手续费 + 服务费」，且随类目 / 站点 / 卖家等级分层。

本模块把费率升级为可维护的数据表解析，同时保留代码兜底以保证「主库未灌费率」
时口径不变（默认值与旧 ``DEFAULT_FEES`` 完全一致）。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import PlatformFeeSchedule

# 代码兜底费率：与旧 DEFAULT_FEES 数值一致，保证既有利润口径不变。
DEFAULT_FEE_SCHEDULES: dict[str, dict] = {
    "shopee": {"commission_rate": 0.06},
    "amazon": {"commission_rate": 0.15},
    "shopify": {"commission_rate": 0.02},
    "ebay": {"commission_rate": 0.12},
    "temu": {"commission_rate": 0.05},
    "tiktok": {"commission_rate": 0.08},
}
FALLBACK_RATE = 0.06


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _row_dict(row) -> dict:
    commission = _num(row.commission_rate)
    transaction = _num(row.transaction_rate)
    service = _num(row.service_rate)
    return {
        "id": row.id, "platform": row.platform, "category": row.category or "",
        "site": (row.site or "").upper(),
        "commission_rate": commission, "transaction_rate": transaction,
        "service_rate": service, "total_rate": round(commission + transaction + service, 6),
        "note": row.note or "",
        "source": "tenant" if row.tenant_id is not None else "platform",
    }


def _default_schedule(platform: str) -> dict:
    values = DEFAULT_FEE_SCHEDULES.get(platform)
    if values is None:
        return {"platform": platform, "category": "", "site": "", "commission_rate": FALLBACK_RATE,
                "transaction_rate": 0.0, "service_rate": 0.0, "total_rate": FALLBACK_RATE,
                "note": "未知平台，使用兜底费率", "source": "fallback", "id": None}
    return {"platform": platform, "category": "", "site": "",
            "commission_rate": _num(values.get("commission_rate")),
            "transaction_rate": _num(values.get("transaction_rate")),
            "service_rate": _num(values.get("service_rate")),
            "total_rate": round(sum(_num(values.get(key)) for key in
                                    ("commission_rate", "transaction_rate", "service_rate")), 6),
            "note": "代码兜底费率（与旧 DEFAULT_FEES 一致）", "source": "default", "id": None}


def resolve(db: Session, tenant_id: int | None, platform: str, category: str = "",
            site: str = "", at: datetime | None = None) -> dict:
    """解析适用费率：租户行 > 平台内置行 > 代码兜底；同类按「类目 + 站点」specificity 排序。"""
    at = at or datetime.utcnow()
    name = (platform or "").strip().lower()
    if not name:
        return _default_schedule("")
    cat = (category or "").strip()
    site_code = (site or "").strip().upper()
    rows = []
    if db is not None:
        query = db.query(PlatformFeeSchedule).filter(PlatformFeeSchedule.platform == name)
        if tenant_id is None:
            query = query.filter(PlatformFeeSchedule.tenant_id.is_(None))
        else:
            query = query.filter(PlatformFeeSchedule.tenant_id.is_(None)
                                 | (PlatformFeeSchedule.tenant_id == tenant_id))
        rows = [row for row in query.all()
                if (not row.effective_from or row.effective_from <= at)
                and not (row.effective_to and row.effective_to <= at)
                and (not row.category or row.category == cat)
                and (not row.site or (row.site or "").upper() == site_code)]
    if not rows:
        return _default_schedule(name)

    def score(row) -> tuple:
        source_rank = 0 if row.tenant_id is not None else 1
        specificity = (1 if row.category else 0) + (1 if (row.site or "") else 0)
        return (source_rank, -specificity, -int(row.id or 0))

    return _row_dict(min(rows, key=score))


def effective_rate(db: Session, tenant_id: int | None, platform: str, category: str = "",
                   site: str = "", at: datetime | None = None) -> float:
    """返回该平台/类目/站点的综合费率（佣金 + 交易手续费 + 服务费）。"""
    return resolve(db, tenant_id, platform, category, site, at)["total_rate"]


def list_schedules(db: Session, tenant_id: int | None, platform: str = "",
                   include_defaults: bool = True) -> list[dict]:
    """列出可见费率行（租户自有 + 平台内置 + 未被覆盖的代码兜底参考值）。"""
    query = db.query(PlatformFeeSchedule)
    if tenant_id is None:
        query = query.filter(PlatformFeeSchedule.tenant_id.is_(None))
    else:
        query = query.filter(PlatformFeeSchedule.tenant_id.is_(None)
                             | (PlatformFeeSchedule.tenant_id == tenant_id))
    name = (platform or "").strip().lower()
    if name:
        query = query.filter(PlatformFeeSchedule.platform == name)
    items = [_row_dict(row) for row in
             query.order_by(PlatformFeeSchedule.platform, PlatformFeeSchedule.category).all()]
    if include_defaults:
        present = {item["platform"] for item in items}
        for key in DEFAULT_FEE_SCHEDULES:
            if name and key != name:
                continue
            if key in present:
                continue
            items.append(_default_schedule(key) | {"id": None})
    return items
