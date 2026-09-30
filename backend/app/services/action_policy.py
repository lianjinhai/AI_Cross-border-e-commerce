"""Action 类型、权限和风险的服务端目录；Agent 无权覆盖。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionPolicy:
    agents: frozenset[str]
    permission: str
    target_type: str
    risk: str = "LOW"
    approval: bool = False
    rollback: str = "删除本次新建记录；保留 Action 审计"


POLICIES = {
    "UPDATE_PRODUCT_CONTENT": ActionPolicy(
        frozenset({"product"}), "product:write", "product",
        rollback="按 outcome.before 人工恢复商品安全标准化内容；保留 Action 审计"),
    "CREATE_AD_CAMPAIGN_DRAFT": ActionPolicy(
        frozenset({"ads"}), "finance:write", "product",
        rollback="人工删除本次广告草稿；保留 Action 审计，禁止自动启动投放"),
    "ADJUST_AD_BUDGET": ActionPolicy(
        frozenset({"ads"}), "finance:write", "ad_campaign", "HIGH", True,
        "按 outcome.old_budget 发起新的预算审批 Action"),
    "CREATE_LISTING_DRAFT": ActionPolicy(
        frozenset({"listing"}), "listing:write", "product", "MEDIUM"),
    "UPDATE_LISTING_CONTENT": ActionPolicy(
        frozenset({"listing"}), "listing:write", "listing",
        rollback="按 outcome.before 恢复草稿内容；已发布内容禁止自动更新"),
    "PUBLISH_LISTING": ActionPolicy(
        frozenset({"listing"}), "listing:write", "listing", "MEDIUM", True,
        "本地撤销走人工业务接口；真实平台撤销另走 UNPUBLISH_LISTING 审批"),
}
