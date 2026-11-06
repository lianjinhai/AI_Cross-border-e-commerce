"""平台状态摄入的纯函数：raw_status 映射、迁移合法性、在售判定唯一口径。

设计依据 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md` §5（平台状态与验证）与 §1（三类状态分离）。
本模块只做判定，不碰 DB、不提交事务，便于单测直接断言。

三条硬约束：
1. **摄入路径永远不能把平台状态置为 ACTIVE** —— `PLATFORM_TRANSITIONS` 的所有目标集合里
   都不含 ACTIVE。在售只能由 `CONFIRM_ACTIVATION` 完成独立核验后置位（§5、§7）。
2. **不认识的 raw_status 一律 UNKNOWN + PLATFORM_ERROR**，不自动推进（§5 末行）。
3. **旧序号事件只留审计，不回退状态**（§5 末段）。
"""

from .profile_schema import PLATFORM_STATES

# 未注册的原始状态：调用方据此记 PLATFORM_ERROR，且不得改写 platform_status。
UNMAPPED_ERROR = "PLATFORM_ERROR"

# 显式枚举合法迁移，不用「序号大小」代替（序号无法表达 REJECTED 回炉与 PAUSED/OFFLINE 分支）。
# 目标集合里刻意不含 ACTIVE：这是「摄入不等于在售」的机器可校验保证。
PLATFORM_TRANSITIONS = {
    "UNKNOWN": {"NOT_SUBMITTED", "SUBMITTED", "UNDER_REVIEW", "ACCEPTED"},
    "NOT_SUBMITTED": {"SUBMITTED", "UNDER_REVIEW", "ACCEPTED"},
    "SUBMITTED": {"UNDER_REVIEW", "ACCEPTED", "REJECTED"},
    "UNDER_REVIEW": {"ACCEPTED", "REJECTED"},
    "ACCEPTED": {"REJECTED"},
    # 上线后的暂停/下架只从 ACTIVE 出发；恢复在售须重新核验，不由摄入路径置位。
    "ACTIVE": {"PAUSED", "OFFLINE"},
    "PAUSED": {"OFFLINE"},
    "OFFLINE": set(),
    # 被拒后补交是新一轮提交，允许回到 SUBMITTED。
    "REJECTED": {"SUBMITTED"},
}


def map_platform_status(raw_status, status_mapping):
    """raw_status -> (platform_status, error_code)。

    消费 Profile 定义的 `status_mapping`（此前只被声明与校验、从未被消费，是 P0-1 F3 的
    根因）。匹配顺序：精确匹配 → 大小写不敏感回退。未注册或映射到非法值时返回
    `("UNKNOWN", PLATFORM_ERROR)`，调用方必须保持原状态不变。
    """
    statuses = (status_mapping or {}).get("statuses") or {}
    key = (raw_status or "").strip()
    if not key:
        return "UNKNOWN", UNMAPPED_ERROR
    mapped = statuses.get(key)
    if mapped is None:
        folded = {str(name).upper(): value for name, value in statuses.items()}
        mapped = folded.get(key.upper())
    if mapped not in PLATFORM_STATES:
        return "UNKNOWN", UNMAPPED_ERROR
    return mapped, None


def can_transition(current, target):
    """迁移是否合法；相同状态视为幂等重放（允许，由调用方决定是否落库）。"""
    if current == target:
        return True
    if target not in PLATFORM_STATES or current not in PLATFORM_TRANSITIONS:
        return False
    return target in PLATFORM_TRANSITIONS[current]


def is_stale_event(incoming_revision, last_revision):
    """旧序号或重复序号事件：只留审计，不回退状态（§5 末段）。"""
    if incoming_revision is None:
        return False
    if last_revision is None:
        return False
    return incoming_revision <= last_revision


def is_verified_online(run):
    """「已核验在售」唯一口径（§1 末段）。

    此前该谓词在 `launch_nba` / `launch_handlers` / `launch_actions` 各写一遍（P0-1 F5），
    改口径要改三处。此处收敛为单一实现，三处改为调用。
    """
    return run is not None and (run.platform_status == "ACTIVE"
                                and run.verification_status == "VERIFIED")


def is_activated(platform_status, completed_at):
    """上线后整改分支开关（原 `launch_plan.activated_flag` 的纯函数版，支持传入新状态）。"""
    return platform_status in {"ACTIVE", "PAUSED", "OFFLINE"} and completed_at is not None
