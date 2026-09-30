"""发布与复核共用的字段级内容指纹，不访问数据库。"""

import hashlib
import json


def listing_fingerprint(listing, product):
    return hashlib.sha256(json.dumps({
        "title": listing.title, "description": listing.description,
        "bullets": listing.bullets or [], "keywords": listing.keywords or [],
        "category": product.category, "brand": product.brand,
        "images": product.images or [],
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]
