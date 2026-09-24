"""RAG 知识检索（对应规划 5.3 RAG 知识库）。

双模式：
- 配置 LLM Key → 调用 /embeddings 接口做真实向量检索（余弦相似度），向量缓存到文档行；
- 未配置 / 调用失败 → 退回 TF 关键词计分（ASCII 按词、中文按二元组切分，标题加权）。
"""
import math
import re

import httpx
from sqlalchemy.orm import Session

from .. import config
from ..models import KnowledgeDoc
from .llm import get_llm_config

# ---------------------------------------------------------------- 向量检索

def _embed(db: Session, text: str) -> list[float] | None:
    """调用 OpenAI 兼容 embeddings 接口；失败返回 None（调用方退 TF 模式）。"""
    cfg = get_llm_config(db)
    if not (cfg.get("enabled") and cfg.get("api_key")):
        return None
    try:
        resp = httpx.post(
            cfg["base_url"].rstrip("/") + "/embeddings",
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
            json={"model": cfg.get("embedding_model") or "embedding-3", "input": text[:2000]},
            timeout=config.settings.llm_timeout,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _vector_retrieve(db: Session, tenant_id: int, query: str, top_k: int) -> list[dict] | None:
    """向量检索；embedding 不可用（无Key/失败/无文档向量）时返回 None 走 TF。"""
    docs = (db.query(KnowledgeDoc)
            .filter(KnowledgeDoc.tenant_id == tenant_id, KnowledgeDoc.enabled.is_(True))
            .all())
    if not docs:
        return []
    qv = _embed(db, query)
    if not qv:
        return None
    scored, dirty = [], False
    for d in docs:
        if not d.embedding:
            dv = _embed(db, f"{d.title}\n{d.content[:1500]}")
            if dv:
                d.embedding = dv
                dirty = True
            else:
                return None  # 中途向量化失败，整体退 TF，保证口径一致
        scored.append({"id": d.id, "title": d.title, "source": d.source,
                       "content": d.content[:800],
                       "score": round(_cosine(qv, d.embedding), 4)})
    if dirty:
        db.commit()
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


# ---------------------------------------------------------------- TF 兜底

def _terms(text: str) -> list[str]:
    text = (text or "").lower()
    terms = re.findall(r"[a-z0-9]{2,}", text)
    for ch_block in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(ch_block) == 1:
            terms.append(ch_block)
        else:
            terms.extend(ch_block[i:i + 2] for i in range(len(ch_block) - 1))
    return terms


def _tf_retrieve(db: Session, tenant_id: int, query: str, top_k: int) -> list[dict]:
    q = _terms(query)
    if not q:
        return []
    docs = (db.query(KnowledgeDoc)
            .filter(KnowledgeDoc.tenant_id == tenant_id, KnowledgeDoc.enabled.is_(True))
            .all())
    scored = []
    for d in docs:
        title_terms = _terms(d.title)
        body_terms = _terms(d.content)
        score = 0.0
        for t in q:
            score += 3.0 * title_terms.count(t)
            score += 1.0 * body_terms.count(t)
        if score > 0:
            scored.append({"id": d.id, "title": d.title, "source": d.source,
                           "content": d.content[:800], "score": round(score, 2)})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


def retrieve(db: Session, tenant_id: int, query: str, top_k: int = 4) -> list[dict]:
    if not (query or "").strip():
        return []
    try:
        vr = _vector_retrieve(db, tenant_id, query, top_k)
        if vr is not None:
            return vr
    except Exception:
        pass
    return _tf_retrieve(db, tenant_id, query, top_k)
