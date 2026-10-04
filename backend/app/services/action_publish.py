"""发布业务服务：Action 负责审批，平台发布意图与 checkpoint 负责外部幂等。"""

import hashlib
import json
import logging
import uuid
from datetime import datetime

from ..models import (
    ComplianceReport,
    Listing,
    ListingReviewDecision,
    PlatformPublishAttempt,
    Product,
    Shop,
)
from ..serialize import to_dict
from . import platforms, publish_gate
from .action_content import owned
from .action_records import listing_fingerprint
from .ai_actions import ActionError
from .platform_rules import get_active_rules, validate_against_rules
from .review_analysis import digest, review_inputs

logger = logging.getLogger(__name__)


def publish_targets(db, tenant_id, listing_id, shop_id=None):
    listing = owned(db, Listing, tenant_id, listing_id)
    product = owned(db, Product, tenant_id, listing.product_id)
    shop = None if shop_id is None else owned(db, Shop, tenant_id, shop_id)
    if shop is not None:
        if shop.role != "sales":
            raise ActionError(400, "货源平台店铺不能作为销售上架目标")
        if shop.archived_at is not None:
            raise ActionError(404, "店铺不存在")
        if listing.platform != shop.platform:
            raise ActionError(400, f"Listing 平台为 {listing.platform}，不能发布到 {shop.platform} 店铺")
        if not shop.is_demo and shop.status != "authorized":
            raise ActionError(400, "店铺未授权，请先完成 OAuth 授权")
    return listing, product, shop


def publish_facts(db, tenant_id, listing_id, shop_id=None):
    listing, product, shop = publish_targets(db, tenant_id, listing_id, shop_id)
    pack = get_active_rules(db, listing.platform)
    violations = validate_against_rules(db, listing.platform, listing, product)
    if violations:
        raise ActionError(400, "平台规则校验未通过：" + "；".join(violations))
    report = (db.query(ComplianceReport).filter(
        ComplianceReport.tenant_id == tenant_id,
        ComplianceReport.listing_id == listing_id,
        ComplianceReport.target_type == "listing")
        .order_by(ComplianceReport.id.desc()).first())
    if listing.risk_level == "high" or (report and report.risk_level == "high"):
        raise ActionError(400, "合规风险高，禁止发布")
    review = (db.query(ListingReviewDecision).filter(
        ListingReviewDecision.tenant_id == tenant_id,
        ListingReviewDecision.listing_id == listing_id)
        .order_by(ListingReviewDecision.id.desc()).first())
    content_fingerprint = listing_fingerprint(listing, product)
    if (review is None or review.decision != "approved"
            or review.rule_version != pack["version"]
            or (review.evidence or {}).get("content_fingerprint") != content_fingerprint):
        raise ActionError(409, "当前内容与规则版本尚未通过上架复核")
    if (review.evidence or {}).get("review_inputs") is not None:
        inputs = review_inputs(to_dict(listing), to_dict(product), pack, to_dict(report) if report else None)
        sync = (review.evidence or {}).get("rule_sync")
        if sync and (sync.get("error") or sync.get("latest") == "not-found"):
            inputs["rule_sync_failure"] = digest({key: sync.get(key) for key in ("error", "latest", "hint")})
        if review.evidence["review_inputs"] != inputs:
            raise ActionError(409, "复核规则或最新合规报告已变化，请重新复核")
    # 第五道：目的国准入闸门。
    # 放在四道既有校验**之后**——前四道是「内容是否可发」，这一道是「法规是否允许发」。
    # 放在**之前**会让闸门在规则违规时就中断，运营同时看不到两类问题，反而不利排查。
    #
    # 为什么用 enforce（真阻断）而不是只记日志：缺 FCC 认证的充电器一旦上架，
    # 平台会下架甚至封店，代价远高于「多提醒一次」；2026-10 验收证实 warn-only
    # 下缺认证商品确实能一路发到真实 eBay 店铺。
    #
    # 旁路：**本地（shop=None，直接置 published）与demo 店铺（is_demo=1）不拦**。
    # 这两条路径不对外产生真实上架行为，E2E 演示也依赖它们；拦下来只会造成
    # 「闸门把本地流程也打挂」的可用性事故。真实店铺（is_demo=0）必须拦。
    bypass = shop is None or bool(shop.is_demo)
    compliance_gate = publish_gate.evaluate(
        db, tenant_id, product=product, platform=listing.platform, shop=shop,
        mode=publish_gate.MODE_WARN if bypass else publish_gate.MODE_ENFORCE)
    if compliance_gate["gate_status"] != publish_gate.GATE_PASS:
        publish_gate.log_warn(compliance_gate, channel="publish_facts")
    if compliance_gate["gate_status"] == publish_gate.GATE_BLOCK:
        raise ActionError(400, "上架合规闸门未通过：" + "；".join(compliance_gate["reasons"]))
    payload = {"listing": {key: getattr(listing, key) for key in
                           ("title", "description", "bullets", "keywords", "platform")},
               "product": {key: getattr(product, key) for key in
                           ("title", "sku", "category", "brand", "attrs", "images")},
               "rule_version": pack["version"], "shop_id": shop.id if shop else None}
    fingerprint = hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"fingerprint": fingerprint, "rule_version": pack["version"],
            "review_id": review.id, "platform": listing.platform,
            "shop_id": shop.id if shop else None,
            "compliance_gate": compliance_gate}


def _attempt(db, action, listing, shop):
    attempt = (db.query(PlatformPublishAttempt).filter(
        PlatformPublishAttempt.tenant_id == action.tenant_id,
        PlatformPublishAttempt.listing_id == listing.id,
        PlatformPublishAttempt.shop_id == shop.id).first())
    if attempt is None:
        attempt = PlatformPublishAttempt(
            tenant_id=action.tenant_id, listing_id=listing.id, shop_id=shop.id,
            platform=shop.platform, idempotency_key=uuid.uuid4().hex,
            status="queued", checkpoint={}, requested_by=action.requested_by,
            request_payload={"listing_id": listing.id, "shop_id": shop.id,
                             "action_id": action.id})
        db.add(attempt)
        db.commit()  # 外部副作用前持久化意图，进程崩溃后可以找回。
    return attempt


def _external_publish(db, action, listing, product, shop):
    attempt = _attempt(db, action, listing, shop)
    if attempt.status == "succeeded" and attempt.external_id:
        return attempt.external_id, "", "demo" if shop.is_demo else "api", True

    def checkpoint(values):
        attempt.checkpoint = {**(attempt.checkpoint or {}), **values}
        attempt.status = "processing"
        db.commit()

    attempt.status = "processing"
    attempt.started_at = attempt.started_at or datetime.utcnow()
    db.commit()
    try:
        if shop.is_demo:
            result = platforms.demo_publish(listing, product)
            source = "demo"
        else:
            result = platforms.publish_to_shop(
                db, shop, listing, product, resume=attempt.checkpoint or {},
                checkpoint=checkpoint)
            source = "api"
    except platforms.PlatformError as exc:
        attempt.status = "uncertain" if attempt.checkpoint else "failed"
        attempt.error = str(exc)[:2000]
        attempt.finished_at = datetime.utcnow()
        db.commit()
        raise ActionError(400, str(exc)) from exc
    attempt.status = "succeeded"
    attempt.external_id = result.external_id
    attempt.error = ""
    attempt.finished_at = datetime.utcnow()
    db.commit()  # 外部成功凭据先落库，后续本地事务失败仍可 read-back/幂等恢复。
    return result.external_id, result.url, source, False


def publish_listing(db, action, payload):
    """Executor 专用入口；本地与真实平台都在审批后执行。"""
    listing, product, shop = publish_targets(
        db, action.tenant_id, action.target_id, payload.get("shop_id"))
    facts = publish_facts(db, action.tenant_id, action.target_id, payload.get("shop_id"))
    if facts["fingerprint"] != action.evidence.get("fingerprint"):
        raise ActionError(409, "审批期间内容、商品或规则已变化，请新建发布 Action")
    if listing.status == "published" and listing.external_id:
        return {"result": {**to_dict(listing), "source": "api" if shop else "local",
                           "publish_url": "", "idempotent_replay": True}}
    if shop is None:
        external_id, url, source, replay = (
            f"{listing.platform}-{listing.id:06d}", "", "local", False)
    else:
        external_id, url, source, replay = _external_publish(db, action, listing, product, shop)
    listing.status = "published"
    listing.external_id = external_id
    listing.published_at = datetime.utcnow()
    listing.updated_at = listing.published_at
    db.flush()
    return {"result": {**to_dict(listing), "publish_url": url, "source": source,
                       "idempotent_replay": replay}}
