"""智能客服路由：会话 / 消息 / AI 自动回复（第十三章）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.support import SupportAgent
from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import Conversation, Message, User
from ..serialize import page, to_dict

router = APIRouter(prefix="/support", tags=["support"])


class ConversationIn(BaseModel):
    platform: str = "shopee"
    buyer_name: str
    content: str
    order_id: int | None = None
    product_id: int | None = None


class ReplyIn(BaseModel):
    content: str


@router.get("/conversations")
def list_conversations(status: str = "", page_num: int = 1, page_size: int = 20,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Conversation).filter(Conversation.tenant_id == user.tenant_id)
    if status:
        q = q.filter(Conversation.status == status)
    total = q.count()
    rows = (q.order_by(Conversation.last_message_at.desc())
            .offset((page_num - 1) * page_size).limit(page_size).all())
    items = []
    for c in rows:
        d = to_dict(c)
        last = (db.query(Message)
                .filter(Message.tenant_id == user.tenant_id, Message.conversation_id == c.id)
                .order_by(Message.created_at.desc()).first())
        d["last_message"] = last.content[:60] if last else ""
        d["message_count"] = (db.query(Message)
                              .filter(Message.tenant_id == user.tenant_id,
                                      Message.conversation_id == c.id).count())
        items.append(d)
    return page(items, total, page_num, page_size)


@router.post("/conversations")
def create_conversation(body: ConversationIn,
                        user: User = Depends(require_write), db: Session = Depends(get_db)):
    c = Conversation(tenant_id=user.tenant_id, platform=body.platform,
                     buyer_name=body.buyer_name, order_id=body.order_id,
                     product_id=body.product_id, status="open")
    db.add(c)
    db.flush()
    _sa = SupportAgent(user.tenant_id)
    m = Message(tenant_id=user.tenant_id, conversation_id=c.id, role="buyer",
                content=body.content, intent=_sa.classify(body.content))
    _sa.close()
    db.add(m)
    c.last_message_at = datetime.utcnow()
    db.commit()
    return {**to_dict(c), "messages": [to_dict(m)]}


@router.get("/conversations/{conversation_id}")
def conversation_detail(conversation_id: int,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _owned(db, user.tenant_id, conversation_id)
    msgs = (db.query(Message)
            .filter(Message.tenant_id == user.tenant_id, Message.conversation_id == conversation_id)
            .order_by(Message.created_at).all())
    return {**to_dict(c), "messages": [to_dict(m) for m in msgs]}


@router.post("/conversations/{conversation_id}/reply")
def reply(conversation_id: int, body: ReplyIn,
          user: User = Depends(require_write), db: Session = Depends(get_db)):
    c = _owned(db, user.tenant_id, conversation_id)
    m = Message(tenant_id=user.tenant_id, conversation_id=conversation_id,
                role="operator", content=body.content, auto=False)
    db.add(m)
    c.last_message_at = datetime.utcnow()
    db.commit()
    # M4 知识自进化（方案 §8-修正8）：人工回复即回填候选答案。
    # auto_reply 与 reply 是独立触发端点，候选先记录问题、此处补答案——
    # 这样"客服先答、系统后沉淀"的真实流程才能被学习到。
    from ..services import knowledge_learning

    backfilled = knowledge_learning.backfill_answer(
        db, user.tenant_id, conversation_id, body.content)
    out = to_dict(m)
    if backfilled:
        out["knowledge_backfilled"] = backfilled
    return out


@router.post("/conversations/{conversation_id}/auto_reply")
def auto_reply(conversation_id: int,
               user: User = Depends(require_write), db: Session = Depends(get_db)):
    _owned(db, user.tenant_id, conversation_id)
    with SupportAgent(user.tenant_id) as a:
        return a.auto_reply(conversation_id)


@router.post("/conversations/{conversation_id}/close")
def close(conversation_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    c = _owned(db, user.tenant_id, conversation_id)
    c.status = "closed"
    db.commit()
    return to_dict(c)


def _owned(db: Session, tenant_id: int, conversation_id: int) -> Conversation:
    c = db.get(Conversation, conversation_id)
    if not c or c.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return c
