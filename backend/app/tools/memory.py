"""Memory Tool：§10.4 冻结清单里的 Memory 入口（本阶段只冻结接口）。

为什么现在只声明不实现
    §18.2 把五层 Memory 排在 Phase 6，§18.3 又要求「禁止跳步」。此处把
    ``recall`` / ``remember`` 登记进清单，是为了让 §10.4 的清单完整性可校验
    （清单缺项会被 tests/test_tool_layer.py 直接打回）；实现留到 Phase 6。

为什么返回 NOT_IMPLEMENTED 而不是空结果
    「没有相关记忆」与「记忆系统还不存在」是两件完全不同的事。若这里静默返回
    空列表，Agent 会把「系统没建好」当成「确实没经验」，并据此产出结论——这是
    最危险的一类错误：错得毫无痕迹。§15.4「降级不得静默」正是为此。
"""

from __future__ import annotations

from .base import BaseTool, Reading
from .contract import ERR_NOT_IMPLEMENTED, ToolError, ToolSpec

_PHASE6 = "Memory 系统属 Agent OS §18.2 Phase 6，尚未实现"


class MemoryTool(BaseTool):
    name = "memory"
    specs = (
        ToolSpec(tool="memory", method="recall", permission="ai:read",
                 writes=False, summary="读取 Memory（Phase 6 实现，当前返回 NOT_IMPLEMENTED）"),
        ToolSpec(tool="memory", method="remember", permission="ai:write",
                 writes=True, summary="写入 Memory（Phase 6 实现，须经 Action）"),
    )

    def _recall(self, **params) -> Reading:
        raise ToolError(ERR_NOT_IMPLEMENTED, _PHASE6)
