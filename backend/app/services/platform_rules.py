"""平台规则引擎：发布前强制校验，违规拒绝（底线：避免用户店铺被封）。

规则包来源：
1. 内置 DEFAULT_RULE_PACKS（基于各平台公开的卖家规则整理，带版本日期与出处）；
2. 数据库 PlatformRulePack（版本更新时写入，覆盖内置）；
3. 预留远程更新：环境变量 ERP_RULES_URL 指向规则 JSON 源，check_updates 可拉取。

各平台不一致性全部体现在各自的规则包里（标题长度/违禁词/禁售类目/图片要求/限流）。
"""
import hashlib
import hmac
import json
import os
import time

import httpx
from sqlalchemy.orm import Session

from ..models import PlatformRulePack

# ---------------------------------------------------------------- 内置规则包

DEFAULT_RULE_PACKS: dict[str, dict] = {
    "shopee": {
        "version": "2026-09-19",
        "source_url": "https://open.shopee.com/documents/v2/v2.product.post_item",
        "rules": {
            "title_max": 255, "desc_max": 3000, "image_min": 1, "image_max": 9,
            "public_image_required": False, "rate_limit_per_sec": 10,
            "banned_words": ["最", "第一品牌", "no.1", "top 1", "fda approved",
                             "治疗", "防癌", "杀菌", "certified authentic"],
            "banned_categories": ["药品", "医疗器材", "枪支", "电子烟"],
            "notes": [
                "标题超过 60 字符在部分类目会降低搜索权重（平台建议精简）",
                "类目/品牌为 Shopee post_item 必填，缺类目映射将无法上架",
                "重量单位为克（g），系统内部 kg 已自动换算",
            ],
        },
    },
    "amazon": {
        "version": "2026-09-19",
        "source_url": "https://developer-docs.amazon.com/sp-api/docs/listings-items-api",
        "rules": {
            "title_max": 200, "desc_max": 2000, "image_min": 1, "image_max": 9,
            "public_image_required": True, "rate_limit_per_sec": 5,
            "banned_words": ["free shipping", "best seller", "guarantee", "100%",
                             "hot item", "sale", "cheap", "discount", "free gift",
                             "最", "第一", "顶级", "fda approved", "cure", "treats"],
            "banned_categories": ["处方药", "枪支", "活的动物"],
            "notes": [
                "Amazon 严禁标题/描述含任何促销用语（free shipping/sale 等），违者 Listing 下架",
                "主图必须纯白底、无水印、无文字，图片 URL 必须公网可访问",
                "上架需要 product_type（PCP）与类目属性，未接入前请勿强行发布",
            ],
        },
    },
    "tiktok": {
        "version": "2026-09-19",
        "source_url": "https://partner.tiktokshop.com/docv2/page/6507ead7b99d5302be949ba9",
        "rules": {
            "title_max": 255, "desc_max": 3000, "image_min": 1, "image_max": 9,
            "public_image_required": True, "rate_limit_per_sec": 10,
            "banned_words": ["减肥药", "医美", "壮阳", "成人", "医疗", "最", "第一"],
            "banned_categories": ["医疗", "成人用品", "药品"],
            "notes": [
                "商品图需先调用预上传接口转为平台素材 URL，外链图会被拒",
                "资质类目（食品/美妆/儿童）需提前在商家后台提交资质",
            ],
        },
    },
    "1688": {
        "version": "2026-09-19",
        "source_url": "https://open.1688.com/api/apidocdetail.htm",
        "rules": {
            "title_max": 128, "desc_max": 5000, "image_min": 1, "image_max": 6,
            "public_image_required": False, "rate_limit_per_sec": 10,
            "banned_words": ["最", "第一", "顶级", "no.1", "防癌", "治疗"],
            "banned_categories": [],
            "notes": [
                "1688 为货源平台：用于搜品/详情/代发下单，不承担销售上架",
                "开放平台接口有应用级频控，系统默认按 10 QPS 节流",
            ],
        },
    },
    "ebay": {
        "version": "2026-09-22",
        "source_url": "https://www.ebay.com/help/policies/default/ebay-policies?id=4207",
        "rules": {
            "title_max": 80, "desc_max": 500000, "image_min": 1, "image_max": 24,
            "public_image_required": True, "rate_limit_per_sec": 5,
            "banned_words": ["counterfeit", "replica", "unauthorized copy", "假货", "仿品"],
            "banned_categories": ["枪支", "毒品", "赃物", "电子烟", "烟草"],
            "manual_categories": ["药品", "医疗器械", "酒类", "刀具", "汽车安全气囊", "收藏品"],
            "notes": ["国际销售还需同时满足目的地法律", "品牌、图片和描述必须拥有合法知识产权",
                      "发布 Offer 前必须配置付款、退货和履约政策"],
        },
    },
    "walmart": {
        "version": "2026-09-22",
        "source_url": "https://marketplace.walmart.com/wp-content/uploads/2019/06/walmart-marketplace-quickstart-item-setup-content-policies.pdf",
        "rules": {
            "title_max": 200, "desc_max": 4000, "image_min": 1, "image_max": 20,
            "public_image_required": True, "rate_limit_per_sec": 5,
            "banned_words": ["counterfeit", "replica", "假货", "仿品"],
            "banned_categories": ["枪支", "毒品", "赃物", "电子烟", "烟草", "活体动物"],
            "manual_categories": ["香水", "奢侈品", "软件", "手机", "定制商品", "酒类", "食品", "危险品"],
            "notes": ["部分品牌和类目必须预先获得 Walmart 书面批准",
                      "通常需要 GTIN/UPC；豁免商品必须先取得平台批准", "Feed 提交不等于商品已上架"],
        },
    },
}


def get_active_rules(db: Session, platform: str) -> dict:
    """当前生效规则包：库内最新版本优先，否则内置。返回 {version, rules, source_url, origin}。"""
    # 平台级共享数据：规则包由平台公开文档整理而来，对**所有租户**一致，
    # 因此 tenant_id 恒为 NULL（平台级哨兵），查询刻意**不带租户过滤**。
    # 与 users.tenant_id 的 superadmin 处理同源（见 docs/DECISIONS.md D27）。
    row = (db.query(PlatformRulePack)
           .filter(PlatformRulePack.platform == platform)
           .order_by(PlatformRulePack.updated_at.desc()).first())
    if row:
        return {"platform": platform, "version": row.version,
                "rules": row.rules, "source_url": row.source_url, "origin": "db"}
    d = DEFAULT_RULE_PACKS.get(platform)
    if not d:
        return {"platform": platform, "version": "none", "rules": {},
                "source_url": "", "origin": "none"}
    return {"platform": platform, "version": d["version"], "rules": d["rules"],
            "source_url": d["source_url"], "origin": "builtin"}


def all_rules_overview(db: Session) -> list[dict]:
    from .platform_adapters import ADAPTERS

    out = []
    for platform in ADAPTERS:
        r = get_active_rules(db, platform)
        rules = r["rules"]
        out.append({**r, "summary": {
            "title_max": rules.get("title_max"), "image_min": rules.get("image_min"),
            "image_max": rules.get("image_max"),
            "banned_words_count": len(rules.get("banned_words", [])),
            "banned_categories": rules.get("banned_categories", []),
            "rate_limit_per_sec": rules.get("rate_limit_per_sec"),
            "public_image_required": rules.get("public_image_required"),
            "notes": rules.get("notes", []),
        }})
    return out


def validate_listing_fields(platform: str, rules: dict, listing: dict,
                            product: dict) -> list[str]:
    """字段级校验核心：纯函数，接收字段字典，不碰数据库，返回违规清单。

    为什么从 ``validate_against_rules`` 拆出来（D40）
        Agent 侧读取已全部走 Tool（§18.3 第 2 步），拿到的是字段字典而不是 ORM
        对象。若校验函数只接受 ORM 对象，Agent 要么回退直连数据库、要么把字典
        再拼回对象——两条路都违反架构。把「规则怎么判」与「数据从哪来」拆开：
        本函数只判字段；``validate_against_rules`` 保留为 ORM 适配器，供
        services/adapters 等未迁移调用点使用（T-53：判定逻辑只有一份）。
    """
    if not rules:
        return []
    violations: list[str] = []
    title = (listing.get("title") or "")
    if len(title) > rules.get("title_max", 255):
        violations.append(f"标题 {len(title)} 字符超出 {platform} 上限 {rules['title_max']}")
    desc_len = len(listing.get("description") or "")
    if desc_len > rules.get("desc_max", 100000):
        violations.append(f"描述 {desc_len} 字符超出上限 {rules['desc_max']}")

    text = " ".join([title, listing.get("description") or "",
                     " ".join(listing.get("keywords") or []),
                     " ".join(listing.get("bullets") or []),
                     product.get("title") or ""]).lower()
    for w in rules.get("banned_words", []):
        if w.lower() in text:
            violations.append(f"命中 {platform} 违禁词「{w}」（发布将导致下架/处罚）")

    for cat in rules.get("banned_categories", []):
        if cat and cat in (product.get("category") or ""):
            violations.append(f"类目「{product.get('category')}」属于 {platform} 禁售范围")

    images = [i for i in (product.get("images") or []) if i]
    if len(images) < rules.get("image_min", 1):
        violations.append(f"商品图片不足：{platform} 要求至少 {rules['image_min']} 张")
    if len(images) > rules.get("image_max", 99):
        violations.append(f"图片超过 {platform} 上限 {rules['image_max']} 张")
    if rules.get("public_image_required"):
        bad = [i for i in images if i.startswith("/api/") or i.startswith("data:")]
        if bad:
            violations.append(f"{platform} 要求公网可访问图片，存在 {len(bad)} 张本地占位图")
    return violations


_LISTING_FIELDS = ("title", "description", "keywords", "bullets", "category", "images")


def _fields_of(obj) -> dict:
    """ORM 对象或字典 -> 字段字典（只取校验需要的键，缺省 None 由核心兜底）。"""
    if isinstance(obj, dict):
        return obj
    return {name: getattr(obj, name, None) for name in _LISTING_FIELDS}


def validate_against_rules(db: Session, platform: str, listing, product) -> list[str]:
    """发布前强制规则校验，返回违规清单（非空即拒绝发布）。

    ORM 适配器：取规则包 + 从 ORM 对象抽字段，判定委托 ``validate_listing_fields``。
    Agent 侧请改用 Tool 取数 + ``validate_listing_fields``（D40）。
    """
    pack = get_active_rules(db, platform)
    return validate_listing_fields(platform, pack["rules"], _fields_of(listing),
                                   _fields_of(product))


def check_updates(db: Session, platform: str) -> dict:
    """规则更新检查：ERP_RULES_URL 配置了远程源则拉取比对，否则与内置版本比对。"""
    remote_url = os.getenv("ERP_RULES_URL", "")
    builtin = DEFAULT_RULE_PACKS.get(platform, {})
    if not remote_url:
        return {"platform": platform, "current": get_active_rules(db, platform)["version"],
                "latest": builtin.get("version", "none"),
                "updated": False,
                "hint": "未配置 ERP_RULES_URL 远程规则源；内置规则包为最新。"}
    try:
        resp = httpx.get(remote_url, timeout=10,
                         headers={"User-Agent": "AI-Commerce-ERP"})
        resp.raise_for_status()
        payload = resp.json()
        signing_key = os.getenv("ERP_RULES_SIGNING_KEY", "")
        if isinstance(payload, dict):
            packs = payload.get("packs")
            signature = str(payload.get("signature") or "")
            if signing_key:
                canonical = json.dumps(packs, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode()
                expected = hmac.new(signing_key.encode(), canonical, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(signature, expected):
                    raise ValueError("远程规则包签名无效")
        else:
            packs = payload
            if signing_key:
                raise ValueError("启用签名后远程规则源必须返回 {packs, signature}")
        if not isinstance(packs, list):
            raise ValueError("远程规则源 packs 必须是数组")
        target = next((p for p in packs if p.get("platform") == platform), None)
        if not target:
            return {"platform": platform, "current": get_active_rules(db, platform)["version"],
                    "latest": "not-found", "updated": False, "hint": "远程源无该平台规则"}
        required = {"title_max": int, "desc_max": int, "image_min": int,
                    "image_max": int, "banned_words": list, "banned_categories": list}
        if not isinstance(target.get("version"), str) or len(target["version"]) < 10:
            raise ValueError("规则版本必须是可追溯日期版本")
        if not isinstance(target.get("rules"), dict):
            raise ValueError("rules 必须是对象")
        for key, kind in required.items():
            if not isinstance(target["rules"].get(key), kind):
                raise ValueError(f"规则字段 {key} 缺失或类型错误")
        current_version = get_active_rules(db, platform)["version"]
        if current_version != "none" and target["version"] < current_version:
            raise ValueError(f"拒绝规则降级：{target['version']} < {current_version}")
        if target.get("version") == current_version:
            return {"platform": platform, "updated": False,
                    "hint": "已是最新版本"}
        # tenant_id=None：平台级共享规则包，不归属任何租户（禁止写 0 哨兵值——
        # tenants 表无 id=0，开启 foreign_keys 后会直接违反外键约束，
        # 历史事故见 app/seed.py 的同类注释）。
        row = PlatformRulePack(tenant_id=None, platform=platform,
                               version=target["version"], rules=target["rules"],
                               source_url=str(target.get("source_url") or remote_url))
        db.add(row)
        db.commit()
        return {"platform": platform, "updated": True,
                "version": target["version"], "hint": "规则包已更新并即时生效"}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        return {"platform": platform, "updated": False, "error": str(e)}


class RateLimiter:
    """平台调用节流：避免超平台频控触发风控（封店底线的一部分）。"""

    def __init__(self, per_second: float = 10.0):
        self.min_interval = 1.0 / max(0.1, per_second)
        self._last = 0.0

    def wait(self):
        now = time.monotonic()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()
