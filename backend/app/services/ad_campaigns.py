"""广告活动的业务写入口；Action Executor 与人工操作共用业务校验。"""

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import AdCampaign


class CampaignChangeError(ValueError):
    pass


def apply_budget_change(db: Session, tenant_id: int, campaign_id: int,
                        expected_old: float, new_budget: float) -> AdCampaign:
    """在调用方事务内调整预算；陈旧建议和跨租户目标一律拒绝。"""
    campaign = db.get(AdCampaign, campaign_id)
    if campaign is None or campaign.tenant_id != tenant_id:
        raise CampaignChangeError("广告活动不存在")
    if abs(campaign.budget - expected_old) > 0.001:
        raise CampaignChangeError("广告预算已变化")
    if not 5.0 <= new_budget <= 500.0:
        raise CampaignChangeError("预算必须在 5-500 美元之间")
    campaign.budget = new_budget
    campaign.updated_at = datetime.utcnow()
    return campaign
