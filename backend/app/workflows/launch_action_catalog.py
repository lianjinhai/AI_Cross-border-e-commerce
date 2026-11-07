"""Launch 动作元数据目录与载荷契约：未接通即禁用，完成标记绝不接受客户端勾选。

目录是纯数据（不碰 DB、不读时钟）：执行框架、NBA 与 DTO 角色投影共用同一份事实，
新增业务动作只改本文件与 handlers，框架不动（设计 D1）。本轮接通的动作见
``BUSINESS_ACTION_META`` 的 ``connected`` 标记，其余领域动作（B03-B09）保持禁用并
指向责任领域与后续批次。动作幂等键、载荷指纹与证据指纹（设计 D2/R10）同属动作契约，
随本文件一起冻结。
"""

import hashlib
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import WorkflowRun, WorkflowStep
from ..services.workspace_context import WorkspaceContext
from .launch_access import LaunchError
from .launch_rules import STEP_STATES
from .launch_state import canonical_json
from .profile_schema import BUSINESS_ACTIONS, StepDefinition

# run 级动作（CANCEL/ABANDON_PRODUCT）不受单步骤来源状态约束。
ALL_STEP_STATES = frozenset(STEP_STATES)
ALL_BUSINESS_TYPES = frozenset(BUSINESS_ACTIONS)

# 完成/状态标记键：流程三态只能由服务端事实推导，载荷出现即拒绝（AC-5.3 / AC-10.3）。
FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "completed", "status", "step_status", "execution_status", "platform_status",
    "verification_status", "revision", "active_slot", "started_at", "completed_at", "ended_at"})
# 载荷文本上限：备注与材料引用截断到 500 字符（防审计库被长文本撑爆）。
PAYLOAD_TEXT_LIMIT = 500

DISABLED_STOCK = "备货领域服务未接入（后续批次）"
DISABLED_COMPLIANCE = "合规材料服务未接入（后续批次）"
DISABLED_LABEL = "标签服务未接入（后续批次）"
DISABLED_EVIDENCE = "实物材料核验服务未接入（后续批次）"

# COMPLIANCE 角色投影剔除集（设计 D8）：从动作清单完全移除，不是置灰。
PRICE_STOCK_ACTIONS = frozenset({"REPORT_PRICE", "ACCEPT_PRICE", "COUNTER_PRICE",
                                 "REQUEST_STOCK", "CONFIRM_STOCK", "ABANDON_PRODUCT"})


@dataclass(frozen=True)
class ActionMeta:
    """动作元数据：权限、来源状态、风险、批准、连通性与载荷契约。"""

    business_types: frozenset[str]   # 适用步骤 business_type
    permissions: tuple[str, ...]     # 所需权限（全部满足）
    source_states: frozenset[str]    # 步骤来源状态
    target: str                      # "step" | "run"
    risk: str                        # LOW/MEDIUM/HIGH
    approval_required: bool          # 是否走审批队列（SUBMIT_PLATFORM 复用 PUBLISH_LISTING）
    connected: bool                  # 本轮是否有 handler
    disabled_reason: str             # 未接通/后续批次说明
    required_payload: frozenset[str]
    optional_payload: frozenset[str]
    external_confirmer: bool         # 依赖外部确认者（NBA 安全依赖排序用）
    framework: bool = False          # 框架级动作（RETRY）：不属于 Profile available_actions 词表


@dataclass
class ActionContext:
    """handler 执行上下文：服务端事实 + 请求载荷（只读，不隐式提交）。"""

    db: Session
    run: WorkflowRun
    step: WorkflowStep | None
    current: WorkspaceContext
    payload: dict
    facts: dict
    plan: dict
    definition: StepDefinition | None
    predicates: dict = field(default_factory=dict)


@dataclass
class StepEffect:
    """handler 对目标步骤/流程的断言效果；由执行框架统一落库并记事件。"""

    status: str | None = None          # 断言的目标步骤终态
    result: dict | None = None         # 合并进 step.result
    evidence_refs: list | None = None  # 去重追加
    attempts_delta: int = 0            # 折算为 attempts 增量
    run_fields: dict | None = None     # run 级字段（platform_status 等）
    cancelled: bool = False            # 终止本轮（写 ended_at、释放 active_slot）
    receipt: dict | None = None        # 动作回执（事件与响应共用）
    external: dict | None = None       # {status, reference, type}
    # 收敛重算用的新事实/新谓词（M2-A）：只在本事务内参与条件求值，**不落 step.result**。
    # 为什么需要它：计划在 handler 之前算好，handler 刚写下的领域记录（如报价轮次）
    # 在旧 facts 里还不存在；不给这条通道，PRICE_REVIEW 的完成条件在事务内永远读不到，
    # 要么假失败、要么只能靠在 handler 里造一个 review_id 蒙过去。
    facts: dict | None = None
    predicates: dict | None = None


def _meta(business_types, permissions, source_states, *, target="step", risk="MEDIUM",
          approval_required=False, connected=False, disabled_reason="", required=(),
          optional=("note",), external_confirmer=False, framework=False):
    """构造动作元数据；optional 默认只放备注类字段（AC-5.3）。"""
    return ActionMeta(business_types=frozenset(business_types), permissions=tuple(permissions),
                      source_states=frozenset(source_states), target=target, risk=risk,
                      approval_required=approval_required, connected=connected,
                      disabled_reason=disabled_reason, required_payload=frozenset(required),
                      optional_payload=frozenset(optional), external_confirmer=external_confirmer,
                      framework=framework)


BUSINESS_ACTION_META: dict[str, ActionMeta] = {
    # ---- 本轮接通（P0）：COMPLETE_DATA / SUBMIT_PLATFORM / CONFIRM_ACTIVATION / RETRY / CANCEL ----
    "COMPLETE_DATA": _meta({"DATA_PREPARATION", "HUMAN_DECISION"},
                           ("launch:manage", "listing:write"), {"READY"}, risk="LOW", connected=True),
    "SUBMIT_PLATFORM": _meta({"PLATFORM_SUBMISSION"}, ("launch:submit", "listing:write"),
                             {"READY"}, risk="HIGH", approval_required=True, connected=True,
                             external_confirmer=True),
    # 在售核验的 COMPLETED 来源状态支持误判更正（AC-7.5）：新事件 + history 追加，
    # 不擦除历史核验记录；本轮回流只有 READY（首次核验）与 COMPLETED（更正）两种入口。
    # WAITING_EXTERNAL 也放行：平台可能已在售但我们尚未收到 ACCEPTED 事实，
    # 此时人工去平台核对（source=MANUAL）是合法路径，不冒充 API 核验。
    "CONFIRM_ACTIVATION": _meta({"PLATFORM_ACTIVATION"}, ("launch:submit", "compliance:approve"),
                                {"READY", "COMPLETED", "WAITING_EXTERNAL"}, risk="HIGH", connected=True,
                                external_confirmer=True, required=(), optional=("material_ref", "note")),
    # RETRY 是框架级动作（适用于任意失败步骤），不在 Profile available_actions 词表中。
    "RETRY": _meta(ALL_BUSINESS_TYPES, ("launch:manage",), {"FAILED"}, connected=True, framework=True),
    "CANCEL": _meta(ALL_BUSINESS_TYPES, ("launch:manage",), ALL_STEP_STATES, target="run",
                    risk="HIGH", connected=True, required=("note", "confirm"), optional=()),
    "ABANDON_PRODUCT": _meta({"HUMAN_DECISION"}, ("launch:manage",), ALL_STEP_STATES, target="run",
                             risk="HIGH", connected=True, required=("note", "confirm"), optional=()),
    # ---- 核价（M2-A 接通）：报价轮次只增不改，低价门禁在 handler 内阻断 ----
    # 金额必须带币种：无 currency 一律 422，绝不默认 USD（否则毛利口径就是猜的）。
    "REPORT_PRICE": _meta({"PRICE_REVIEW"}, ("launch:price_review",), {"READY"}, connected=True,
                          required=("price", "currency"), optional=("note",),
                          external_confirmer=True),
    "ACCEPT_PRICE": _meta({"HUMAN_DECISION"}, ("launch:price_review",), {"READY"}, connected=True),
    "COUNTER_PRICE": _meta({"HUMAN_DECISION"}, ("launch:price_review",), {"READY"}, connected=True,
                           required=("price", "currency"), optional=("note",)),
    # ---- 未接通（B03-B09 领域服务建设中）：直接调用 409 ACTION_NOT_ALLOWED ----
    "REQUEST_STOCK": _meta({"STOCK_PREPARATION"}, ("launch:stock_prepare",), {"READY"},
                           disabled_reason=DISABLED_STOCK),
    "CONFIRM_STOCK": _meta({"STOCK_PREPARATION"}, ("launch:stock_prepare",), {"READY"},
                           disabled_reason=DISABLED_STOCK),
    "UPLOAD_ARTIFACT": _meta({"COMPLIANCE"}, ("launch:compliance_manage",), {"READY"},
                             disabled_reason=DISABLED_COMPLIANCE),
    "VERIFY_ARTIFACT": _meta({"COMPLIANCE"}, ("launch:compliance_manage",), {"READY"},
                             disabled_reason=DISABLED_COMPLIANCE),
    "GENERATE_LABEL": _meta({"LABEL"}, ("launch:label_manage",), {"READY"},
                            disabled_reason=DISABLED_LABEL),
    "REGENERATE_LABEL": _meta({"LABEL"}, ("launch:label_manage",), {"READY"},
                              disabled_reason=DISABLED_LABEL),
    "UPLOAD_PHYSICAL_EVIDENCE": _meta({"EVIDENCE"}, ("launch:compliance_manage",), {"READY"},
                                      disabled_reason=DISABLED_EVIDENCE),
    "VERIFY_EVIDENCE": _meta({"EVIDENCE"}, ("launch:compliance_manage",), {"READY"},
                             disabled_reason=DISABLED_EVIDENCE),
}


def action_meta(action: str) -> ActionMeta:
    """取动作元数据；未注册动作 409 ACTION_NOT_ALLOWED（不泄露内部目录结构）。"""
    meta = BUSINESS_ACTION_META.get(action)
    if meta is None:
        raise LaunchError("ACTION_NOT_ALLOWED", "动作不在执行目录：" + str(action)[:64], 409)
    return meta


def validate_payload(action: str, payload: dict) -> dict:
    """严格校验 per-action 载荷：拒绝完成标记与未知键，note 截断；返回规范化载荷。

    抛 LaunchError("ACTION_PAYLOAD_INVALID", msg, 422)。必填键缺失属结构性违约（422）；
    取值语义（如 CONFIRM_ACTIVATION 缺材料引用/备注的「仅勾选」）由各 handler 以 409
    ACTION_PRECONDITION_FAILED 拒绝（AC-7.2）。
    """
    meta = action_meta(action)
    if not isinstance(payload, dict):
        raise LaunchError("ACTION_PAYLOAD_INVALID", "动作载荷必须是对象", 422)
    normalized: dict = {}
    for key, value in payload.items():
        if not isinstance(key, str) or key in FORBIDDEN_PAYLOAD_KEYS:
            raise LaunchError("ACTION_PAYLOAD_INVALID",
                              "载荷包含不允许的状态标记键：" + str(key)[:64], 422)
        if key not in meta.required_payload and key not in meta.optional_payload:
            raise LaunchError("ACTION_PAYLOAD_INVALID", "载荷包含未知键：" + key[:64], 422)
        if key == "confirm" and value is not True:
            raise LaunchError("ACTION_PAYLOAD_INVALID", "人工确认必须为 true", 422)
        normalized[key] = value[:PAYLOAD_TEXT_LIMIT] if isinstance(value, str) else value
    missing = sorted(meta.required_payload - set(normalized))
    if missing:
        raise LaunchError("ACTION_PAYLOAD_INVALID", "载荷缺少必填键：" + "、".join(missing), 422)
    return normalized


# ---------------------------------------------------------------- 派生指纹（设计 D2/R10）

def action_digest(*parts) -> str:
    """复合哈希（sha256，冒号连接）：动作幂等键与载荷指纹的公共基底。"""
    return hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def action_event_key(run_id: int, step_code: str, action: str, raw_key: str) -> str:
    """动作事件幂等键（设计 D2）：前缀隔离 + 复合哈希，长度 78 命中 uq_workflow_event_key。"""
    return "launch:action:" + action_digest(run_id, step_code, action, raw_key)


def payload_hash(step_code: str, action: str, payload: dict) -> str:
    """载荷指纹（设计 D2）：sha256(canonical_json({step_code, action, payload}))。"""
    return action_digest(canonical_json({"step_code": step_code, "action": action, "payload": payload}))


def evidence_fingerprint(run: WorkflowRun, step: WorkflowStep | None, action: str, digest: str) -> str:
    """证据指纹（设计 R10）：sha256(step_code+action+input_revision+definition_hash+facts_digest)。"""
    parts = [step.step_code if step is not None else "", action,
             str(step.input_revision if step is not None else 0), run.definition_hash, digest]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
