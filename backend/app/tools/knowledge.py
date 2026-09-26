"""Knowledge Tool：把 RAG 检索收进 Tool 层（§10.4 冻结清单）。

为什么不直接让 Agent 调 ``ai.knowledge.retrieve``
    检索结果会进入 Agent 的推理依据，属于「读了什么数据」的一部分。若不收进
    Tool 层，Trace 里就查不到这次运行到底依据了哪几篇知识文档，§19 验收项 5
    （全部可追溯）随之落空。收进来的代价只是一次转发，收益是这条读取可审计。
"""

from __future__ import annotations

from ..ai.knowledge import retrieve
from .base import BaseTool, Reading, reading
from .contract import ERR_BAD_PARAM, ToolError, ToolSpec

# 上限而非默认值：默认 4 与 ai.knowledge.retrieve 的默认保持一致，
# 上限用于挡住「top_k=100000」这类把整个知识库灌进上下文的调用。
_DEFAULT_TOP_K = 4
_MAX_TOP_K = 20


class KnowledgeTool(BaseTool):
    name = "knowledge"
    specs = (
        ToolSpec(tool="knowledge", method="search", permission="ai:read",
                 writes=False, summary="检索本租户知识库，返回带评分的文档片段"),
    )

    def _search(self, query: str = "", top_k: int = _DEFAULT_TOP_K) -> Reading:
        if not (query or "").strip():
            raise ToolError(ERR_BAD_PARAM, "query 不能为空")
        if not 1 <= int(top_k) <= _MAX_TOP_K:
            raise ToolError(ERR_BAD_PARAM,
                            "top_k 必须在 1~%d 之间，实际 %r" % (_MAX_TOP_K, top_k))
        docs = retrieve(self.db, self.context.tenant_id, query, int(top_k))
        return reading(docs, source="knowledge_docs", query=query,
                       doc_ids=[d["id"] for d in docs], count=len(docs))
