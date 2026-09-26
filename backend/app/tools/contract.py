"""Tool Layer 契约（Agent OS §10.3 冻结签名）与调用上下文。

**本模块只放契约与词汇表：零业务逻辑、零 I/O、零数据库访问。**

为什么必须有 Tool Layer
    架构红线 3 禁止 Agent 直接操作数据库；§10.1 把 Tool Layer 定义为 Agent
    访问业务能力的**唯一入口**。入口唯一，§10.2 的三项强制要求（绑定
    Workspace / 检查 Permission / 记录 Audit）才有唯一落点。若各 Agent 继续
    自建查询，这三项要求没有任何一处能够生效。

为什么契约要与实现分离
    §10.3 把 ToolCall / ToolResult 定义为**冻结**结构。冻结的含义是：任何 Tool
    实现都必须遵守同一套字段语义。否则 Guardrail 无法统一判定权限、Trace 无法
    统一记录调用、Action 层无法统一取 evidence——三处各写一套解析必然漂移
    （T-53）。因此触发来源、上下文来源、Tool 清单三份词汇表全部集中在本模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ---------------------------------------------------------------- 触发来源（§15.2）

TRIGGER_USER_GOAL = "USER_GOAL"
TRIGGER_EVENT = "EVENT"
TRIGGER_WORKFLOW = "WORKFLOW"
TRIGGER_MANUAL = "MANUAL"
TRIGGERS = frozenset({TRIGGER_USER_GOAL, TRIGGER_EVENT, TRIGGER_WORKFLOW,
                      TRIGGER_MANUAL})

# ---------------------------------------------------------------- 上下文来源

# 权威源：由 services/workspace_context.resolve_workspace_context 解析，权限齐备。
SOURCE_CONTEXT = "context"
# 兜底源：兼容期路由已鉴权、Agent 仅持 tenant_id，Tool 层**无法复校权限**。
# 该路径下的调用一律标记 degraded，使缺口可见而不是假装已校验（纪律 7）。
SOURCE_LEGACY = "legacy"
SOURCES = frozenset({SOURCE_CONTEXT, SOURCE_LEGACY})

# ---------------------------------------------------------------- 失败码（冻结）

# 调用方按码分支，不要匹配中文文案——文案会改，码不会。
ERR_PERMISSION = "PERMISSION_DENIED"
ERR_NOT_FOUND = "NOT_FOUND"
ERR_BAD_PARAM = "BAD_PARAM"
ERR_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
ERR_INTERNAL = "INTERNAL"


class ToolError(RuntimeError):
    """Tool 调用失败（对应 ToolResult.ok=False 的 error 载荷）。

    为什么用异常而不是返回 None：失败必须**可归因**——是权限不足、对象不存在，
    还是能力尚未实现？返回 None 会把语义压平成一个值，调用方只能靠猜，
    Trace 也记不下原因（§15.4「降级不得静默」）。
    """

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------- 调用上下文


@dataclass(frozen=True)
class ToolContext:
    """一次 Agent 运行的身份与追踪上下文（§17.1 的 Workspace-aware 要求）。

    字段口径说明（**重要，不要按字面猜测**）：
      - `tenant_id` 是**当前模型层唯一可用的数据隔离键**：全部业务表都带
        `tenant_id` 且受外键约束（DEBT-03），而模型层尚无 `workspace_id` 列。
        因此 Tool 内部一律按 `tenant_id` 过滤——这是事实，不是设计理想。
      - `workspace_id` 是 §10.2 强制的**审计主体**（对应 `workspace_profiles.id`）。
        legacy 路径下它与 `tenant_id` 同值（见 workspace_context 的兼容期实现），
        MEMBERSHIP 路径下二者不同。**记录审计用它，过滤数据用 tenant_id**，
        两者不得互相替代。
      - `permissions=None` 表示**未经校验的兼容路径**，而非「无权限」。二者语义
        截然不同：前者是缺口（调用会标记 degraded），后者是拒绝。
      - `steps` 是 §15.2 Trace 的 `steps[]`。冻结的 dataclass 持有可变列表是
        刻意选择：上下文身份不可变，而调用序列必须随执行增长。
    """

    tenant_id: int
    workspace_id: int
    agent_type: str
    permissions: frozenset[str] | None = None
    user_id: int | None = None
    task_id: int | None = None
    trace_id: str = ""
    parent_trace_id: str = ""
    trigger: str = TRIGGER_MANUAL
    source: str = SOURCE_LEGACY
    steps: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.trigger not in TRIGGERS:
            raise ValueError("trigger 不在冻结枚举内：%r" % (self.trigger,))
        if self.source not in SOURCES:
            raise ValueError("source 不在冻结枚举内：%r" % (self.source,))
        if not self.workspace_id:
            # §17.1：禁止无上下文 Agent。workspace_id 缺失即拒绝，不降级放行。
            raise ValueError("workspace_id 必填——§17.1 禁止无上下文 Agent")

    @property
    def permission_checked(self) -> bool:
        """本上下文是否具备可校验的权限集合（决定调用是否标记 degraded）。"""
        return self.permissions is not None

    def has(self, permission: str) -> bool:
        """是否持有某权限。**未校验上下文一律返回 False**（fail-closed）。"""
        if self.permissions is None:
            return False
        return permission in self.permissions


def legacy_context(tenant_id: int, agent_type: str, **kwargs) -> ToolContext:
    """构造兼容期上下文：workspace_id 取 tenant_id，权限标记为未校验。

    为什么单独抽成函数：兼容期与权威期的差别只应有**一处**（T-53）。散落各处
    手写 `ToolContext(tenant_id=t, workspace_id=t, permissions=None, ...)` 时，
    迟早有人漏写 `permissions=None`，于是「未校验」被静默当成「已校验」。
    """
    return ToolContext(tenant_id=tenant_id, workspace_id=tenant_id,
                       agent_type=agent_type, permissions=None, source=SOURCE_LEGACY,
                       **kwargs)


# ---------------------------------------------------------------- 调用与结果


@dataclass(frozen=True)
class ToolCall:
    """一次 Tool 调用请求（§10.3 冻结）。

    **与 §10.3 的一处刻意偏离（安全决策，已登记）**：§10.3 把 `permission`
    列为 ToolCall 字段，本实现**不接收调用方传入的权限 key**，改由 Tool 依据
    自身 `ToolSpec` 解析。理由：调用方传入的权限可被伪造或误填，等于把闸门的
    钥匙交给被检查者——权限来源必须是被调用方，而不是调用方。
    """

    tool: str
    method: str
    params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool or not self.method:
            raise ValueError("ToolCall 必须同时指定 tool 与 method")


@dataclass(frozen=True)
class ToolResult:
    """一次 Tool 调用的结果（§10.3 冻结的六个字段，逐条对应）。"""

    ok: bool
    data: object = None
    evidence: dict = field(default_factory=dict)
    freshness: datetime | None = None
    degraded: bool = False
    error: dict | None = None

    def __post_init__(self) -> None:
        if not self.ok and not self.error:
            # §10.3：ok=false 时 error 必填。缺失即构造错误，当场暴露。
            raise ValueError("ToolResult.ok=False 时必须提供 error")
        if self.ok and self.error:
            raise ValueError("ToolResult.ok=True 时不得携带 error")


@dataclass(frozen=True)
class ToolSpec:
    """单个 Tool 方法的声明——§10.4 冻结清单的机器可读形式。

    为什么清单是数据而不是散落在各 Tool 类里：Guardrail 要按清单判定权限、
    Trace 要按清单记录、测试要按清单比对实现是否齐全。三处各维护一份必然漂移。
    """

    tool: str
    method: str
    permission: str
    writes: bool
    summary: str

    def __post_init__(self) -> None:
        if self.permission not in _ALL_KNOWN_PERMISSIONS:
            raise ValueError("permission 不在冻结目录内：%r" % (self.permission,))

    @property
    def key(self) -> str:
        return "%s.%s" % (self.tool, self.method)


# ---------------------------------------------------------------- 权限目录（引用）

# 权限 key 的权威源是 services/workspace_context.ROLE_PERMISSIONS（其取值与
# docs/phase1_interfaces.md 第 4 节逐条一致）。这里**不复制一份清单**，而是从
# 角色矩阵求并集（T-53：同一份信息不得维护在两个地方）。
#
# 为什么从 services 取而不是从 agents/contracts.py 取：依赖方向是
# `routers -> agents -> tools -> services -> models`（规范 §4）。tools 反向
# import agents 会形成环，且会让 Tool 层无法脱离 Agent 独立测试。
from ..services.workspace_context import ROLE_PERMISSIONS  # noqa: E402

_ALL_KNOWN_PERMISSIONS = frozenset(
    perm for perms in ROLE_PERMISSIONS.values() for perm in perms)
