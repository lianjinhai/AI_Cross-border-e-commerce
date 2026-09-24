"""Model Router：统一 LLM 接入层（对应规划书第五章）。

- 兼容 OpenAI Chat Completions 协议（智谱 GLM / DeepSeek / OpenAI / Ollama 等均可）。
- 运行时配置存于 Setting 表 key="llm"，可经 /api/ai/settings 在线修改。
- 未配置 api_key 时抛出 LLMUnavailable，Agent 层自动降级为规则引擎（离线可用）。
"""
import json
import re
import time

import httpx
from sqlalchemy.orm import Session

from .. import config
from ..models import Setting

DEFAULT_LLM = {
    "enabled": True,
    "api_key": config.settings.llm_api_key,
    "base_url": config.settings.llm_base_url,
    "model": config.settings.llm_model,
    "model_small": config.settings.llm_model_small,
    "embedding_model": config.settings.llm_embedding_model,
}


class LLMUnavailable(Exception):
    pass


def get_llm_config(db: Session) -> dict:
    row = db.get(Setting, "llm")
    cfg = dict(DEFAULT_LLM)
    if row and isinstance(row.value, dict):
        cfg.update(row.value)
    return cfg


def set_llm_config(db: Session, value: dict) -> dict:
    row = db.get(Setting, "llm")
    if not row:
        row = Setting(key="llm", value={})
        db.add(row)
    merged = dict(DEFAULT_LLM)
    merged.update(row.value or {})
    merged.update(value or {})
    row.value = merged
    db.commit()
    return merged


class ModelRouter:
    """按任务选择模型：轻量任务用 model_small，复杂分析用 model。"""

    def __init__(self, db: Session):
        self.cfg = get_llm_config(db)

    @property
    def available(self) -> bool:
        return bool(self.cfg.get("enabled") and self.cfg.get("api_key"))

    def chat(self, messages: list[dict], model: str | None = None,
             json_mode: bool = False, timeout: int | None = None) -> dict:
        if not self.available:
            raise LLMUnavailable("LLM 未配置 api_key，当前为离线规则模式")
        body = {
            "model": model or self.cfg["model"],
            "messages": messages,
            "temperature": 0.4,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        t0 = time.time()
        try:
            resp = httpx.post(
                self.cfg["base_url"].rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {self.cfg['api_key']}"},
                json=body,
                timeout=timeout or config.settings.llm_timeout,
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            raise LLMUnavailable(f"LLM 调用失败: {e}") from e
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "content": content,
            "model": body["model"],
            "latency_ms": int((time.time() - t0) * 1000),
        }

    def ask_json(self, system: str, prompt: str, small_task: bool = False) -> dict:
        model = self.cfg.get("model_small") if small_task else None
        r = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            model=model,
            json_mode=True,
        )
        return {"parsed": parse_json(r["content"]), "raw": r}


def parse_json(text: str) -> dict:
    """容错解析：剥掉 ```json 围栏、截取首尾花括号。"""
    if not text:
        return {}
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}
