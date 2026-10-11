"""版本化定义服务：事务、不可变内容、匹配歧义与现有权限边界。"""

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models import Product, Shop, User, WorkflowTemplate
from app.services.workspace_context import resolve_workspace_context
from app.workflows.contract_profiles import simple_contract
from app.workflows.kinds import PLATFORM_LAUNCH
from app.workflows.profiles import (
    ProfileError,
    create_profile,
    definition_snapshot,
    publish_profile,
    retire_profile,
    select_profile,
    update_draft,
)


@pytest.fixture
def profile_db(client):
    with SessionLocal() as db:
        owner = db.query(User).filter_by(username="admin").one()
        ctx = resolve_workspace_context(db, owner)
        previous = {row.id for row in db.query(WorkflowTemplate).filter_by(flow_kind=PLATFORM_LAUNCH)}
        product = Product(tenant_id=owner.tenant_id, sku="profile-test", title="Profile product", category="家居")
        shop = Shop(tenant_id=owner.tenant_id, platform="shopee", market="SG", fulfillment_mode="DROPSHIP")
        db.add_all([product, shop])
        db.commit()
        yield db, ctx, product, shop
        db.rollback()
        db.query(WorkflowTemplate).filter_by(tenant_id=owner.tenant_id, flow_kind=PLATFORM_LAUNCH).filter(
            WorkflowTemplate.id.notin_(previous)).delete(synchronize_session=False)
        db.delete(product)
        db.delete(shop)
        db.commit()


def _published(db, ctx, payload):
    row = create_profile(db, ctx, payload)
    publish_profile(db, ctx, row.id, row.definition_hash)
    db.commit()
    return row


def test_profile_versions_immutable_and_latest_published_selected(profile_db):
    db, ctx, product, shop = profile_db
    old = _published(db, ctx, simple_contract())
    old_snapshot = definition_snapshot(old)
    with pytest.raises(ProfileError, match="不可修改"):
        update_draft(db, ctx, old.id, {**simple_contract(), "name": "Overwrite"}, old.definition_hash)
    latest = create_profile(db, ctx, simple_contract(2))
    db.commit()
    assert select_profile(db, ctx, product.id, shop.id, "CONTRACT_TEST").id == old.id
    publish_profile(db, ctx, latest.id, latest.definition_hash)
    db.commit()
    assert select_profile(db, ctx, product.id, shop.id, "CONTRACT_TEST").id == latest.id
    assert definition_snapshot(old) == old_snapshot
    retire_profile(db, ctx, latest.id)
    db.commit()
    assert definition_snapshot(latest)["version"] == 2
    assert select_profile(db, ctx, product.id, shop.id, "CONTRACT_TEST").id == old.id
    with pytest.raises(ProfileError) as error:
        select_profile(db, ctx, product.id, shop.id, "PRODUCTION")
    assert error.value.code == "PROFILE_NOT_FOUND"


def test_duplicate_version_and_stale_publish_rejected(profile_db):
    db, ctx, _, _ = profile_db
    row = create_profile(db, ctx, simple_contract())
    old_hash = row.definition_hash
    update_draft(db, ctx, row.id, {**simple_contract(), "name": "Edited draft"}, old_hash)
    with pytest.raises(ProfileError) as error:
        publish_profile(db, ctx, row.id, old_hash)
    assert error.value.code == "PROFILE_IMMUTABLE_OR_STALE"
    assert row.definition_status == "DRAFT"
    with pytest.raises(ProfileError) as duplicate:
        create_profile(db, ctx, simple_contract())
    assert duplicate.value.code == "PROFILE_VERSION_EXISTS"
    assert db.query(WorkflowTemplate).filter_by(profile_key="SIMPLE_CONTRACT").count() == 1


def test_specific_profile_wins_but_equal_candidates_are_ambiguous(profile_db):
    db, ctx, product, shop = profile_db
    _published(db, ctx, simple_contract())
    exact = {**simple_contract(), "profile_key": "SG_HOME", "market": "SG", "category_scope": ["家居"]}
    chosen = _published(db, ctx, exact)
    assert select_profile(db, ctx, product.id, shop.id, "CONTRACT_TEST").id == chosen.id
    _published(db, ctx, {**exact, "profile_key": "SG_HOME_DUPLICATE"})
    with pytest.raises(ProfileError) as error:
        select_profile(db, ctx, product.id, shop.id, "CONTRACT_TEST")
    assert error.value.code == "PROFILE_AMBIGUOUS"


@pytest.mark.parametrize("field,value,code", [("role", "source", "SOURCE_STORE"),
                                              ("market", "", "STORE_CONTEXT_MISSING"),
                                              ("market", "EU", "STORE_CONTEXT_MISSING"),
                                              ("fulfillment_mode", "", "STORE_CONTEXT_MISSING")])
def test_missing_or_source_store_never_gets_default_profile(profile_db, field, value, code):
    db, ctx, product, shop = profile_db
    _published(db, ctx, simple_contract())
    setattr(shop, field, value)
    db.commit()
    with pytest.raises(ProfileError) as error:
        select_profile(db, ctx, product.id, shop.id, "CONTRACT_TEST")
    assert error.value.code == code


def test_profile_write_requires_current_owner_and_all_store_scope(profile_db):
    db, ctx, _, shop = profile_db
    operator = db.query(User).filter_by(username="ops").one()
    with pytest.raises(ProfileError) as forbidden:
        create_profile(db, resolve_workspace_context(db, operator), simple_contract())
    assert forbidden.value.status_code == 403
    db.execute(text("INSERT INTO membership_data_scopes(membership_id,scope_type,scope_ref) VALUES(:id,'SHOP_SCOPED',:ref)"),
               {"id": ctx.membership_id, "ref": '{"shop_ids":[' + str(shop.id) + ']}'})
    try:
        with pytest.raises(ProfileError) as restricted:
            create_profile(db, ctx, simple_contract())
        assert restricted.value.status_code == 403
    finally:
        db.execute(text("DELETE FROM membership_data_scopes WHERE membership_id=:id AND scope_type='SHOP_SCOPED'"),
                   {"id": ctx.membership_id})
        db.commit()


def test_corrupt_published_definition_fails_integrity_check(profile_db):
    db, ctx, product, shop = profile_db
    row = _published(db, ctx, simple_contract())
    row.name = "Unexpected external mutation"
    db.commit()
    with pytest.raises(ProfileError) as error:
        select_profile(db, ctx, product.id, shop.id, "CONTRACT_TEST")
    assert error.value.code == "PROFILE_INTEGRITY_ERROR"
