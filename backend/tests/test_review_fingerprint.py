"""复核与发布统一指纹；旧内容人工批准不得覆盖新商品标题或平台。"""

import hashlib
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.listing_review import ListingReviewAgent
from app.db import Base
from app.models import Listing, ListingReviewDecision, PlatformRulePack, Product, Tenant
from app.services.action_publish import publish_facts
from app.services.action_records import listing_fingerprint
from app.services.ai_actions import ActionError


def inputs():
    return ({"platform": "probe", "title": "Listing title", "description": "Description",
             "bullets": ["Bullet"], "keywords": ["Keyword"]},
            {"title": "商品标题", "category": "家居", "brand": "", "images": ["https://example.com/a.jpg"]})


def test_dict_and_orm_like_inputs_have_one_fingerprint():
    listing, product = inputs()
    assert listing_fingerprint(listing, product) == listing_fingerprint(
        SimpleNamespace(**listing), SimpleNamespace(**product))


@pytest.mark.parametrize("target,field", [
    ("listing", "platform"), ("listing", "title"), ("listing", "description"),
    ("product", "title"), ("product", "category"), ("product", "brand")])
def test_every_scalar_review_input_change_invalidates_prior_fingerprint(target, field):
    listing, product = inputs()
    original = listing_fingerprint(listing, product)
    (listing if target == "listing" else product)[field] += " changed"
    assert listing_fingerprint(listing, product) != original


@pytest.mark.parametrize("target,field", [("listing", "bullets"), ("listing", "keywords"), ("product", "images")])
def test_every_list_review_input_change_invalidates_prior_fingerprint(target, field):
    listing, product = inputs()
    original = listing_fingerprint(listing, product)
    (listing if target == "listing" else product)[field].append("changed")
    assert listing_fingerprint(listing, product) != original


def test_legacy_v1_is_not_silently_reinterpreted_as_current_approval():
    listing, product = inputs()
    old = {"title": listing["title"], "description": listing["description"],
           "bullets": listing["bullets"], "keywords": listing["keywords"],
           "category": product["category"], "brand": product["brand"], "images": product["images"]}
    legacy = hashlib.sha256(json.dumps(old, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    assert legacy != listing_fingerprint(listing, product)


def test_product_title_change_blocks_old_human_review_in_agent_and_executor(monkeypatch):
    monkeypatch.delenv("ERP_RULES_URL", raising=False)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="复核指纹探针")
        db.add(tenant)
        db.flush()
        product = Product(tenant_id=tenant.id, sku="REVIEW", title="Old product title",
                          category="家居", images=["https://example.com/probe.jpg"])
        db.add(product)
        db.flush()
        listing = Listing(tenant_id=tenant.id, product_id=product.id, platform="fingerprint_probe",
                          title="Listing", description="Description", bullets=[], keywords=[], status="draft")
        version = datetime.utcnow().strftime("%Y-%m-%d")
        rules = {"manual_categories": ["家居"], "banned_words": [], "image_min": 1}
        db.add_all([listing, PlatformRulePack(platform=listing.platform, version=version,
            rules=rules, source_url="https://example.com/rules")])
        db.flush()
        fingerprint = listing_fingerprint(listing, product)
        approval = ListingReviewDecision(tenant_id=tenant.id, listing_id=listing.id, product_id=product.id,
            platform=listing.platform, decision="approved", human_override=True, reviewer="human:probe",
            reasons=["已人工核对"], rule_version=version,
            evidence={"content_fingerprint": fingerprint})
        db.add(approval)
        db.commit()
        publish_facts(db, tenant.id, listing.id)  # 判别力：变化前确实通过。
        product.title = "Changed product title"
        db.commit()
        with pytest.raises(ActionError, match="尚未通过上架复核"):
            publish_facts(db, tenant.id, listing.id)
        assert listing.status == "draft"
        lid, pid, tid = listing.id, product.id, tenant.id
    monkeypatch.setattr("app.agents.base.SessionLocal", lambda: Session(engine))
    with ListingReviewAgent(tid) as agent:
        monkeypatch.setattr(agent, "_listing", lambda _: {"id": lid, "product_id": pid,
            "platform": "fingerprint_probe", "title": "Listing", "description": "Description",
            "bullets": [], "keywords": []})
        monkeypatch.setattr(agent, "_product", lambda _: {"id": pid, "title": "Changed product title",
            "category": "家居", "brand": "", "images": ["https://example.com/probe.jpg"]})
        monkeypatch.setattr(agent, "_rule_pack", lambda _: {"platform": "fingerprint_probe", "version": version,
            "origin": "db", "source_url": "https://example.com/rules", "rules": rules})
        monkeypatch.setattr(agent, "_listing_report", lambda _: None)
        monkeypatch.setattr(agent, "_decisions", lambda **kw: [] if kw.get("decision") == "rejected" else [
            {"rule_version": version, "evidence": {"content_fingerprint": fingerprint}, "reviewer": "human:probe"}])
        assert agent.review(lid)["decision"] == "manual_required"
    engine.dispose()
