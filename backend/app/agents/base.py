"""Agent 基类：会话管理 + LLM/规则双模执行 + AI 审计日志。

所有专业 Agent 继承 BaseAgent，实现具体业务方法。
ask_json() 是核心模式：优先 LLM 产出结构化 JSON，任何失败自动降级到
确定性规则函数 fallback()，保证系统离线零配置也可完整运行。
"""

from ..ai.llm import ModelRouter
from ..db import SessionLocal
from ..models import AiLog
from ..services.pii_redact import redact, redact_prompt
from ..tools import SOURCE_CONTEXT, ToolContext, legacy_context, open_tool


class BaseAgent:
    name = "base"

    def __init__(self, tenant_id: int, *, context=None):
        self.tenant_id = tenant_id
        self.db = SessionLocal()
        self.context = context

    # ---- 生命周期 ----
    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- Tool Layer（§10 / D37）：Agent 访问业务数据的唯一通道 ----
    def tool_context(self):
        """本 Agent 的 Tool 调用上下文（兼容期：权限未校验，调用会被标记 degraded）。

        为什么收在基类：`legacy_context` 的参数必须逐字一致，散落到各 Agent 手写
        就会出现「有人漏写 permissions=None」——「未校验」被静默当成「已校验」
        （T-53）。迁移期的缺口与代价见 docs/DECISIONS.md D37 / DEBT-35。
        """
        if self.context is None:
            return legacy_context(self.tenant_id, self.name)
        return ToolContext(
            tenant_id=self.tenant_id, workspace_id=self.context.workspace_id,
            agent_type=self.name, user_id=self.context.user_id,
            permissions=self.context.permissions, source=SOURCE_CONTEXT,
            trace_id=self.context.trace_id)

    @staticmethod
    def propose(action_type: str, target_type: str, target_id: int,
                payload: dict, result: dict, reason: str) -> dict:
        """只产生结构化提案；提交、Guardrail 和执行由 Orchestrator 收口。"""
        return {**result, "_action_proposal": {
            "action_type": action_type, "target_type": target_type,
            "target_id": target_id, "payload": payload, "reason": reason}}

    def tool(self, name: str):
        """取一个绑定本 Agent 身份与会话的 Tool（§18.3 第 2 步的迁移入口）。

        用法：``self.tool("product").call("get_products", product_id=1)``。
        返回 ``ToolResult``（ok / data / evidence / degraded / error），失败不抛异常。
        """
        return open_tool(name, self.tool_context(), self.db)

    # ---- LLM + 规则双模 ----
    def ask_json(self, action: str, system: str, prompt: str,
                 fallback, small_task: bool = False) -> tuple[dict, str]:
        """返回 (result, mode)。mode: "llm" / "rule"。

        fallback: 无参可调用，返回 dict 的规则引擎实现（必须可靠）。
        """
        router = ModelRouter(self.db)
        if router.available:
            try:
                r = router.ask_json(system, prompt, small_task=small_task)
                parsed = r["parsed"]
                if parsed:
                    self._log(action, "llm", r["raw"]["model"], prompt,
                              r["raw"]["content"], r["raw"]["latency_ms"], ok=True)
                    return parsed, "llm"
                # 结构无效（空对象/非 dict）：必须留失败痕迹再降级，
                # 否则事后只能看到一条 rule 日志，无法判断模型到底回没回。
                self._log(action, "llm", r["raw"].get("model", ""), prompt,
                          r["raw"].get("content", ""), r["raw"].get("latency_ms", 0), ok=False)
            except Exception as e:  # 任何 LLM 故障都降级，不阻塞业务
                self._log(action, "llm", "", prompt, str(e), 0, ok=False)
        result = fallback() if fallback else {}
        self._log(action, "rule", "rule-engine", prompt,
                  str(result)[:2000], 0, ok=True)
        return result, "rule"

    def _log(self, action, mode, model, prompt, response, latency_ms, ok):
        # PII 脱敏（§19 验收项 8）挂在这里：AiLog 的唯一写入落点。只影响审计表，
        # 业务表（messages 等）保持原文——脱敏不得改写业务数据。
        self.db.add(AiLog(tenant_id=self.tenant_id, agent=self.name, action=action,
                          mode=mode, model=model,
                          prompt=redact_prompt(prompt)[:4000],
                          response=redact(response)[:4000], latency_ms=latency_ms, ok=ok))
        self.db.commit()

    # ---- M6 决策解释层 ----
    def record_decision(self, action: str, subject_type: str, subject_id: int,
                        decision: dict, evidence: dict | None = None,
                        model: str = "rule") -> int:
        """记录一次关键 AI 决策及其依据链（只增不删，可追溯）。

        evidence 应存**引用**（订单号/趋势 id/知识文档 id/规则版本），不存全量快照。
        返回决策记录 id；记录失败不影响主流程（审计不能阻塞业务）。
        """
        try:
            from ..models import AiDecision

            row = AiDecision(tenant_id=self.tenant_id, agent=self.name, action=action,
                             subject_type=subject_type, subject_id=subject_id,
                             decision=decision or {}, evidence=evidence or {}, model=model)
            self.db.add(row)
            self.db.commit()
            return row.id
        except Exception:
            self.db.rollback()
            return 0

    # ---- Agent OS §6.2 契约（§18.3 第 1 步）----
    # 子类必须用 `agent_contract = CONTRACTS["<name>"]` 声明自己的契约。
    # 默认 None 表示「尚未登记」——`assert_contract_declared()` 会因此报错，
    # 避免新增 Agent 悄悄绕过红线 1（禁止未登记 Agent）。
    agent_contract: object | None = None

    @classmethod
    def contract(cls):
        """取本 Agent 的契约（未声明时抛错，而不是静默返回 None）。"""
        if cls.agent_contract is None:
            raise NotImplementedError(
                "Agent %s 未声明 agent_contract——Agent OS §6.2 要求每个 Agent 必须声明 "
                "domain / capabilities / input_schema / output_schema / required_permissions / "
                "required_data_scope / risk_level / max_budget。见 app/agents/contracts.py"
                % cls.__name__)
        return cls.agent_contract
