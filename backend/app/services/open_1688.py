"""1688 开放平台官方 API 客户端（open.1688.com）。

签名协议（param2）：
  path = /openapi/param2/{ns}/{version}/{api}/{app_key}
  签名串 = path + 按key排序的 key1value1key2value2...
  sign = HMAC-SHA1(app_secret, 签名串).hex().upper()

配置存 Setting 表 key="1688_api"：{"app_key", "app_secret", "access_token"}。
未配置或调用失败时，采集管线自动降级到浏览器渲染/粘贴源码模式。
"""
import hashlib
import hmac
import time

import httpx
from sqlalchemy.orm import Session

from ..models import Setting

_GATEWAY = "https://gw.open.1688.com/openapi"
_NAMESPACE = "param2/1/com.alibaba.product"

_DEFAULT = {"app_key": "", "app_secret": "", "access_token": ""}


class Api1688Error(Exception):
    pass


def get_config(db: Session) -> dict:
    row = db.get(Setting, "1688_api")
    cfg = dict(_DEFAULT)
    if row and isinstance(row.value, dict):
        cfg.update(row.value)
    return cfg


def set_config(db: Session, value: dict) -> dict:
    row = db.get(Setting, "1688_api")
    if not row:
        row = Setting(key="1688_api", value={})
        db.add(row)
    merged = {**_DEFAULT, **(row.value or {}), **(value or {})}
    if value.get("app_secret") == "":
        merged["app_secret"] = row.value.get("app_secret", "") if row.value else ""
    if value.get("access_token") == "":
        merged["access_token"] = row.value.get("access_token", "") if row.value else ""
    row.value = merged
    db.commit()
    return merged


def sign(path: str, params: dict, app_secret: str) -> str:
    """官方签名：path + 排序拼接串 的 HMAC-SHA1 大写十六进制。纯函数可测试。"""
    joined = "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(app_secret.encode(), f"{path}{joined}".encode(), hashlib.sha1)
    return digest.hexdigest().upper()


def call_api(db: Session, api: str, extra_params: dict | None = None,
             credentials: dict | None = None) -> dict:
    """调用 1688 openapi（GET）。失败抛 Api1688Error。"""
    cfg = {**get_config(db), **(credentials or {})}
    if not (cfg.get("app_key") and cfg.get("app_secret")):
        raise Api1688Error("未配置 1688 API（app_key/app_secret），请在「AI 设置」中填写")
    path = f"/{_NAMESPACE}/{api}/{cfg['app_key']}"
    params = {
        "access_token": cfg.get("access_token", ""),
        "_aop_signature": "",  # 占位保证排序稳定，签名前剔除
        "timestamp": str(int(time.time() * 1000)),
        **(extra_params or {}),
    }
    params.pop("_aop_signature")
    params["_aop_signature"] = sign(path, params, cfg["app_secret"])
    url = _GATEWAY + path
    try:
        resp = httpx.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise Api1688Error(f"1688 API 调用失败: {e}") from e
    err = data.get("error_code") or data.get("error_message")
    if err:
        raise Api1688Error(f"1688 API 返回错误: {err}")
    return data


def product_info(db: Session, product_id: int) -> dict:
    """alibaba.icp.product.info.get：商品详情 → 统一采集结构。"""
    raw = call_api(db, "alibaba.icp.product.info.get",
                   {"productID": product_id, "webSite": "1688"})
    info = raw.get("result") or raw.get("data") or {}
    subject = info.get("subject") or ""
    if not subject:
        raise Api1688Error("API 返回中缺少商品标题")
    sale_infos = info.get("saleInfos") or []
    price = 0.0
    for s in sale_infos:
        try:
            price = float(str(s.get("price", "")).split("-")[0])
            if price:
                break
        except ValueError:
            continue
    images = (info.get("image") or {}).get("images") or []
    return {
        "title": subject[:200],
        "description": str(info.get("description") or "")[:500],
        "price": price,
        "images": images[:6],
        "domain": "detail.1688.com",
        "source_url": f"https://detail.1688.com/offer/{product_id}.html",
        "product_id": product_id,
    }


def search(db: Session, keywords: str, page: int = 1) -> list[dict]:
    """alibaba.icp.product.search：关键词搜索商品池。"""
    raw = call_api(db, "alibaba.icp.product.search",
                   {"keywords": keywords, "pageNo": page, "pageSize": 20})
    result = raw.get("result") or {}
    items = []
    for p in result.get("result") or []:
        items.append({
            "title": str(p.get("subject") or "")[:200],
            "price": float(p.get("price") or 0),
            "images": (p.get("imageUrls") or [])[:3],
            "product_id": p.get("productId"),
            "source_url": f"https://detail.1688.com/offer/{p.get('productId')}.html",
        })
    return items
