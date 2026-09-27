"""Conversation Tool：客服会话读取（Agent OS §10.4.1 第二批冻结清单）。

为什么字段口径里**没有 buyer_name**
    会话表带 `buyer_name`（买家姓名），而 Tool 的返回值会被审计落库
    （`tools/audit.py` 记录结果载荷）。§15.4 明确禁止买家 PII 进入审计——因此
    字段口径在这里就把它排除，而不是等审计层去猜哪个字段是 PII。与 `order_dict`
    排除 `buyer_name` 同款纪律：**PII 不进 Tool 返回体**。

为什么第二批才补
    §10.4 第一批聚焦「机会 → 供应 → 商品 → 渠道」主干，客服会话不在其中。
    `support.py`（4 处直连读取）是它的第一个消费方（DEBT-36）。

为什么不返回消息内容
    消息正文是买家 PII 的高发区，且它的唯一消费方（`SupportAgent.auto_reply`）
    已经通过 `knowledge_learning.latest_question_text` 拿到待答问题——那条路径的
    查询口径必须与候选回填完全一致，不能在这里再写第二份（T-53）。
"""

from __future__ import annotations

from ..models import Conversation
from .base import BaseTool, Reading, as_int, clamp_limit, reading, ts
from .contract import ERR_BAD_PARAM, ToolError, ToolSpec

# 状态枚举取自 models.Conversation.status 的注释（open/closed）。
_STATUSES = ("open", "closed")


def conversation_dict(c: Conversation) -> dict:
    """会话的对外字段集（唯一一份；不含买家 PII，见模块文档字符串）。"""
    return {"id": c.id, "platform": c.platform, "status": c.status,
            "order_id": c.order_id, "product_id": c.product_id,
            "last_message_at": ts(c.last_message_at), "created_at": ts(c.created_at)}


class ConversationTool(BaseTool):
    name = "conversation"
    specs = (
        ToolSpec(tool="conversation", method="get_conversations", permission="support:read",
                 writes=False, summary="列出本租户客服会话，可按会话/状态过滤（不含买家姓名）"),
    )

    def _get_conversations(self, conversation_id=None, status: str = "", limit=50) -> Reading:
        # 参数校验先于任何数据库访问（D37 第三节缺陷 1 的教训）。
        cid = None if conversation_id is None else as_int(conversation_id, "conversation_id")
        state = (status or "").strip()
        if state and state not in _STATUSES:
            raise ToolError(ERR_BAD_PARAM,
                            "status 必须是 %s 之一，实际 %r"
                            % ("/".join(_STATUSES), status))
        n = clamp_limit(limit)
        query = self.db.query(Conversation).filter(
            Conversation.tenant_id == self.context.tenant_id)
        if cid is not None:
            query = query.filter(Conversation.id == cid)
        if state:
            query = query.filter(Conversation.status == state)
        rows = query.order_by(Conversation.id.desc()).limit(n).all()
        return reading([conversation_dict(c) for c in rows], table="conversations",
                       conversation_ids=[c.id for c in rows])
