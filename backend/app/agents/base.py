"""Agent 基类：会话管理 + LLM/规则双模执行 + AI 审计日志。

所有专业 Agent 继承 BaseAgent，实现具体业务方法。
ask_json() 是核心模式：优先 LLM 产出结构化 JSON，任何失败自动降级到
确定性规则函数 fallback()，保证系统离线零配置也可完整运行。
"""

from ..ai.llm import ModelRouter
from ..db import SessionLocal
from ..models import AiLog


class BaseAgent:
    name = "base"

    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id
        self.db = SessionLocal()

    # ---- 生命周期 ----
    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

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
            except Exception as e:  # 任何 LLM 故障都降级，不阻塞业务
                self._log(action, "llm", "", prompt, str(e), 0, ok=False)
        result = fallback() if fallback else {}
        self._log(action, "rule", "rule-engine", prompt,
                  str(result)[:2000], 0, ok=True)
        return result, "rule"

    def _log(self, action, mode, model, prompt, response, latency_ms, ok):
        self.db.add(AiLog(tenant_id=self.tenant_id, agent=self.name, action=action,
                          mode=mode, model=model, prompt=prompt[:4000],
                          response=str(response)[:4000], latency_ms=latency_ms, ok=ok))
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
