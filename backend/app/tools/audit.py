"""Tool 调用审计：Agent OS §10.2「必须记录 Audit」的唯一落点。

为什么审计用独立短会话，而不是调用方持有的业务会话
    审计与业务事务是两件事。若把审计写进调用方的会话，业务回滚会把审计一起
    回滚——事后无法区分「操作没发生」与「操作发生了但审计丢了」，审计随即失去
    证明力。因此审计走独立短会话，业务成败与审计留存互不牵连。代价是每次调用
    多开一次连接；Tool 调用以只读为主，本地 SQLite 完全承受得住。

为什么审计失败不抛异常
    与 ``BaseAgent.record_decision`` 同款纪律：审计是旁路，不能反过来阻塞业务。
    失败降级为 ``logger.warning``，但**不静默**（§15.4「降级不得静默」）。
"""

from __future__ import annotations

import logging

from ..db import SessionLocal
from ..models import AiLog
from .contract import ToolContext, ToolResult

logger = logging.getLogger(__name__)

# 第 5 步（Runtime 注入会话）只需替换这一个符号，审计侧不需要改动。
_session_factory = SessionLocal

_MAX_FIELD = 4000  # 与 BaseAgent._log 对齐，避免超长载荷撑爆 AiLog


def record(context: ToolContext, tool: str, method: str, params: dict,
           result: ToolResult, latency_ms: int) -> None:
    """记录一次 Tool 调用。best-effort：任何失败都不向上抛。"""
    try:
        db = _session_factory()
    except Exception as exc:
        logger.warning("tool audit 无法开启会话 %s.%s: %s", tool, method, exc)
        return
    try:
        db.add(AiLog(
            tenant_id=context.tenant_id,
            agent=(context.agent_type or "unknown")[:32],
            action=("tool:%s.%s" % (tool, method))[:64],
            mode="tool",
            model="",
            prompt=_brief(params),
            response=_brief(_payload(result)),
            latency_ms=latency_ms,
            ok=result.ok,
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("tool audit 写入失败 %s.%s: %s", tool, method, exc)
    finally:
        db.close()


def _payload(result: ToolResult) -> dict:
    """审计只留结论与降级标记，不留全量数据副本（避免第二份真相）。"""
    if result.ok:
        return {"degraded": result.degraded, "data": result.data}
    return {"degraded": result.degraded, "error": result.error}


def _brief(payload) -> str:
    return repr(payload)[:_MAX_FIELD]
