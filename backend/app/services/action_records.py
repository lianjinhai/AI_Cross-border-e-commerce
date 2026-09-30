"""发布与复核共用的字段级内容指纹，不访问数据库。"""

import hashlib
import json
from collections.abc import Mapping

FINGERPRINT_VERSION = 2


def _field(value, name):
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def listing_fingerprint(listing, product):
    return hashlib.sha256(json.dumps({
        "version": FINGERPRINT_VERSION,
        "platform": _field(listing, "platform"),
        "title": _field(listing, "title"), "description": _field(listing, "description"),
        "bullets": _field(listing, "bullets") or [], "keywords": _field(listing, "keywords") or [],
        "product_title": _field(product, "title"),
        "category": _field(product, "category"), "brand": _field(product, "brand"),
        "images": _field(product, "images") or [],
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]
