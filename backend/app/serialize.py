"""SQLAlchemy 模型 -> dict 的统一序列化。"""
from datetime import datetime
from decimal import Decimal


def to_dict(obj, exclude: list[str] | None = None) -> dict:
    exclude = set(exclude or [])
    out = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        v = getattr(obj, col.name)
        if isinstance(v, datetime):
            v = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, Decimal):
            v = float(v)
        out[col.name] = v
    return out


def page(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}
