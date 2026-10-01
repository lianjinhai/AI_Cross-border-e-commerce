"""Agent Tool Layer（Agent OS §10）—— Agent 访问业务能力的**唯一入口**。

对外只需要四个符号：

    ``legacy_context`` / ``ToolContext`` —— 构造调用上下文（身份 + 追踪）
    ``open_tool(name, context, db)``     —— 取一个 Tool 实例
    ``ToolResult``                       —— 读结果（ok / data / evidence / degraded / error）

为什么 Agent 只能经这里碰数据
    架构红线 3 禁止 Agent 直接操作数据库；§10.2 的三项强制要求（绑定 Workspace /
    检查 Permission / 记录 Audit）必须有一个**唯一落点**才能生效。若各 Agent 继续
    自建查询，这三项要求在任何地方都落不了地。
"""

from .base import BaseTool, Reading, reading
from .contract import (
                       ERR_BAD_PARAM,
                       ERR_INTERNAL,
                       ERR_NOT_FOUND,
                       ERR_NOT_IMPLEMENTED,
                       ERR_PERMISSION,
                       SOURCE_CONTEXT,
                       SOURCE_LEGACY,
                       TRIGGER_EVENT,
                       TRIGGER_MANUAL,
                       TRIGGER_USER_GOAL,
                       TRIGGER_WORKFLOW,
                       ToolCall,
                       ToolContext,
                       ToolError,
                       ToolResult,
                       ToolSpec,
                       legacy_context,
)
from .registry import TOOLS, get_tool, open_tool, tool_specs

__all__ = [
    "BaseTool", "Reading", "reading",
    "SOURCE_CONTEXT", "SOURCE_LEGACY",
    "TRIGGER_USER_GOAL", "TRIGGER_EVENT", "TRIGGER_WORKFLOW", "TRIGGER_MANUAL",
    "ERR_PERMISSION", "ERR_NOT_FOUND", "ERR_BAD_PARAM", "ERR_NOT_IMPLEMENTED",
    "ERR_INTERNAL",
    "ToolCall", "ToolContext", "ToolError", "ToolResult", "ToolSpec",
    "legacy_context", "TOOLS", "get_tool", "open_tool", "tool_specs",
]
