"""RAG 知识库路由：文档 CRUD / 检索（对应规划 5.3）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai.knowledge import retrieve
from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import KnowledgeDoc, User
from ..serialize import page, to_dict

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class DocIn(BaseModel):
    title: str
    content: str
    source: str = ""
    tags: list[str] = []
    enabled: bool = True


@router.get("/docs")
def list_docs(keyword: str = "", page_num: int = 1, page_size: int = 20,
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(KnowledgeDoc).filter(KnowledgeDoc.tenant_id == user.tenant_id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(KnowledgeDoc.title.like(like) | KnowledgeDoc.content.like(like))
    total = q.count()
    items = (q.order_by(KnowledgeDoc.id.desc())
             .offset((page_num - 1) * page_size).limit(page_size).all())
    return page([to_dict(d) for d in items], total, page_num, page_size)


@router.post("/docs")
def create_doc(body: DocIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    d = KnowledgeDoc(tenant_id=user.tenant_id, **body.model_dump())
    db.add(d)
    db.commit()
    return to_dict(d)


@router.put("/docs/{doc_id}")
def update_doc(doc_id: int, body: DocIn, user: User = Depends(require_write),
               db: Session = Depends(get_db)):
    d = _owned(db, user.tenant_id, doc_id)
    # 仅更新请求中显式给出的字段：未传 tags/enabled 时保留原值（避免编辑清空标签/误启用停用文档）
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    db.commit()
    return to_dict(d)


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    d = _owned(db, user.tenant_id, doc_id)
    # M4 引入 knowledge_candidates.doc_id → knowledge_docs.id 外键后，直接删除被
    # 候选引用的文档会抛 IntegrityError（接口 500，真实回归）。此处先解除引用：
    # 候选是"待验证线索"，文档没了线索应退回未入库态，而不是连带删掉线索。
    # 不解除会同时命中两个入口——本接口与 revoke（revoke 恰好先置空 doc_id 才没暴露）。
    from ..models import KnowledgeCandidate

    (db.query(KnowledgeCandidate)
     .filter(KnowledgeCandidate.tenant_id == user.tenant_id,
             KnowledgeCandidate.doc_id == doc_id)
     .update({"doc_id": None, "auto_learned": False, "status": "rejected"},
             synchronize_session=False))
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.get("/search")
def search(q: str = "", top_k: int = 4, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    return {"items": retrieve(db, user.tenant_id, q, top_k=max(1, min(10, top_k)))}


def _owned(db: Session, tenant_id: int, doc_id: int) -> KnowledgeDoc:
    d = db.get(KnowledgeDoc, doc_id)
    if not d or d.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    return d

# ============================================================ M4 客服知识自进化

class CandidateAnswer(BaseModel):
    answer: str = ""


class LearningConfig(BaseModel):
    auto_learn_enabled: bool | None = None
    auto_learn_threshold: int | None = None


@router.get("/candidates")
def list_candidates(status: str = "", min_hits: int = 0, limit: int = 100,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """知识候选列表（按出现次数排序）：未命中问题沉淀，供人工验证后固化。"""
    from ..services import knowledge_learning

    items = knowledge_learning.list_candidates(db, user.tenant_id, status, min_hits, limit)
    return {"items": items, "total": len(items)}


@router.post("/candidates/{candidate_id}/answer")
def answer_candidate(candidate_id: int, body: CandidateAnswer,
                     user: User = Depends(require_write), db: Session = Depends(get_db)):
    """人工补写答案（补写后 answer_source 变为 operator，可参与自动学习）。

    已入库的候选禁止改写（会与知识文档内容不一致），须先 revoke。
    """
    from ..services import knowledge_learning

    try:
        return knowledge_learning.update_answer(db, user.tenant_id, candidate_id,
                                                body.answer)
    except ValueError as e:
        code = 404 if "不存在" in str(e) else 400
        raise HTTPException(status_code=code, detail=str(e)) from e


@router.post("/candidates/{candidate_id}/approve")
def approve_candidate(candidate_id: int, body: CandidateAnswer,
                      user: User = Depends(require_write), db: Session = Depends(get_db)):
    """采纳为知识文档。无人工验证答案的候选不可采纳（安全红线）。"""
    from ..services import knowledge_learning

    try:
        return knowledge_learning.approve_candidate(db, user.tenant_id, candidate_id, body.answer)
    except ValueError as e:
        code = 404 if "不存在" in str(e) else 400
        raise HTTPException(status_code=code, detail=str(e)) from e


@router.post("/candidates/{candidate_id}/reject")
def reject_candidate(candidate_id: int, user: User = Depends(require_write),
                     db: Session = Depends(get_db)):
    from ..services import knowledge_learning

    try:
        return knowledge_learning.reject_candidate(db, user.tenant_id, candidate_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/candidates/{candidate_id}/revoke")
def revoke_candidate(candidate_id: int, user: User = Depends(require_write),
                     db: Session = Depends(get_db)):
    """撤销自动入库：删除已生成的知识文档（红线：自动学习必须可撤销）。"""
    from ..services import knowledge_learning

    try:
        return knowledge_learning.revoke_candidate(db, user.tenant_id, candidate_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/learning/settings")
def get_learning(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """知识学习配置（默认关闭，需显式开启）。"""
    from ..services import knowledge_learning

    cfg = knowledge_learning.get_learning_config(db, user.tenant_id)
    return {**cfg, "hint": ("自动学习已关闭：候选仅累积，需人工采纳；"
                            "开启后，出现次数达阈值且有人工验证答案的问题会自动固化为知识"
                            if not cfg["auto_learn_enabled"] else
                            "自动学习已开启：仅对有人工验证答案的问题生效（AI 不自行编答案）")}


@router.put("/learning/settings")
def set_learning(body: LearningConfig, user: User = Depends(require_write),
                 db: Session = Depends(get_db)):
    from ..services import knowledge_learning

    cfg = knowledge_learning.set_learning_config(db, user.tenant_id, body.model_dump())
    return cfg
