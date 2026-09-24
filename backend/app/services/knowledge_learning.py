"""客服知识自进化服务（M4）：未命中问题沉淀 → 人工验证答案 → 可选自动固化。

安全红线（方案 §3-修正1）：**只沉淀人工验证过的答案，AI 不自行编答案**。
  answer_source = "operator" → 客服人工回复过，可信，可参与自动学习
  answer_source = "none"     → 无答案，永不可入库（人工也只能先补答案）

时序设计（方案 §8-修正8）：auto_reply 与 reply 是两个独立触发端点，
候选先记录问题，operator 后续回复时通过 backfill_answer 回填答案。
"""
import hashlib
import logging
import re

from sqlalchemy.orm import Session

from ..models import KnowledgeCandidate, KnowledgeDoc, Message, Setting, utcnow

logger = logging.getLogger("erp.knowledge_learning")

# 自动学习默认配置（opt-in：默认关闭，与"不擅自变更业务数据"原则一致）
_DEFAULT_LEARNING = {"auto_learn_enabled": False, "auto_learn_threshold": 5}


def get_learning_config(db: Session, tenant_id: int) -> dict:
    """读取知识学习配置（默认关闭）。"""
    row = db.get(Setting, f"knowledge_learning:{tenant_id}")
    cfg = dict(_DEFAULT_LEARNING)
    if row and isinstance(row.value, dict):
        cfg.update(row.value)
    return cfg


def set_learning_config(db: Session, tenant_id: int, value: dict) -> dict:
    """更新配置（仅接受已知字段，避免脏数据）。"""
    key = f"knowledge_learning:{tenant_id}"
    row = db.get(Setting, key)
    if not row:
        row = Setting(key=key, value={})
        db.add(row)
    merged = dict(_DEFAULT_LEARNING)
    merged.update(row.value or {})
    if "auto_learn_enabled" in value:
        merged["auto_learn_enabled"] = bool(value["auto_learn_enabled"])
    if "auto_learn_threshold" in value:
        try:
            merged["auto_learn_threshold"] = max(2, min(100, int(value["auto_learn_threshold"])))
        except (TypeError, ValueError):
            pass
    row.value = merged
    db.commit()
    return merged


def question_hash(text: str) -> str:
    """归一化哈希：去空白/标点、转小写，使格式差异不产生重复候选。

    论证说明（方案 §4-修正4）：不引入向量聚类——候选只是线索，
    聚类不完美只影响线索数量，不影响正确性；向量方案维护成本陡增。
    """
    norm = re.sub(r"[\s\W_]+", "", (text or "").lower(), flags=re.UNICODE)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24]


def is_recordable_question(text: str) -> bool:
    """是否值得记为候选：归一化后必须有实际内容（防纯标点噪音）。

    为什么单独抽出来：原实现在归一化**之前**检查 `len(q) < 2`，挡不住
    "？？"、"！！！"、"..." 这类输入——它们 strip 后长度 ≥2，归一化后却是空串，
    全部落到同一个哈希上被 upsert 成一条候选并累加 hit_count，把噪音顶到列表
    顶部并误导自动学习阈值判断（实测 6 种纯标点输入哈希完全相同）。
    """
    norm = re.sub(r"[\s\W_]+", "", (text or "").lower(), flags=re.UNICODE)
    return len(norm) >= 2


_BUYER_QUESTION_WINDOW = 5


def latest_question_text(db: Session, tenant_id: int, conversation_id: int) -> str:
    """构造会话的「当前待答问题」文本：最近 N 条买家消息按时间正序拼接。

    为什么必须抽成单一实现：候选的 `question_hash` 由 `SupportAgent.auto_reply`
    记录，回填时要用**同一个哈希**才能命中正确候选。两处各写一遍查询迟早漂移，
    一旦漂移，回填要么失配（答案丢失）要么错配（答非所问）。故两处共用本函数。
    """
    msgs = (db.query(Message)
            .filter(Message.tenant_id == tenant_id,
                    Message.conversation_id == conversation_id,
                    Message.role == "buyer")
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(_BUYER_QUESTION_WINDOW).all())
    return " ".join(m.content for m in reversed(msgs))


def record_candidate(db: Session, tenant_id: int, question: str, intent: str,
                     conversation_id: int | None = None) -> dict | None:
    """记录未命中问题为候选（乐观 upsert：已存在则 hit_count+1）。

    容错：任何异常都不抛出——审计/学习不能阻塞客服业务（方案 §4-修正7）。
    """
    try:
        q = (question or "").strip()
        if not is_recordable_question(q):
            logger.info("knowledge candidate skipped: question has no usable content",
                        extra={"tenant_id": tenant_id, "raw_len": len(q)})
            return None
        h = question_hash(q)
        row = (db.query(KnowledgeCandidate)
               .filter(KnowledgeCandidate.tenant_id == tenant_id,
                       KnowledgeCandidate.question_hash == h).first())
        if row:
            row.hit_count += 1
            row.last_seen_at = utcnow()
            if conversation_id and not row.conversation_id:
                row.conversation_id = conversation_id
        else:
            row = KnowledgeCandidate(tenant_id=tenant_id, question_hash=h,
                                     question_text=q[:512], intent=intent or "other",
                                     conversation_id=conversation_id, hit_count=1,
                                     answer_source="none", status="pending")
            db.add(row)
        db.commit()
        # 达标则尝试自动学习（内部自行判断开关与阈值）
        _maybe_auto_learn(db, tenant_id, row)
        db.refresh(row)
        return to_dict(row)
    except Exception as exc:
        # 不阻塞客服回复，但必须留痕：静默吞错会让"候选记录失效"在生产完全不可见
        logger.warning("knowledge candidate recording failed",
                       extra={"tenant_id": tenant_id, "error": repr(exc)})
        db.rollback()
        return None


def backfill_answer(db: Session, tenant_id: int, conversation_id: int,
                    answer: str) -> int:
    """把 operator 的人工回复回填到同会话的候选上（方案 §8-修正8）。

    只在候选尚无答案（answer_source == "none"）时回填，不覆盖已有人工答案。
    返回回填条数；异常不抛出（不阻塞客服回复）。

    匹配口径（P1 修复）：按**当前待答问题的哈希**命中候选，而不是"本会话的全部
    候选"。原实现按 conversation_id 全量匹配，同一会话先后问了两件不同的事时，
    operator 只回一次就会把同一条答案写给两个候选，`_create_doc` 随后把
    "问题 A + 答案 B" 固化成知识——答非所问的知识入库，且人工很难发现。
    用哈希匹配还有第二个好处：候选跨会话合并（conversation_id 只记首次出现）时，
    在任一会话里给出的答案都能正确落到同一条候选上。
    """
    try:
        text = (answer or "").strip()
        if not text:
            return 0
        question = latest_question_text(db, tenant_id, conversation_id)
        if not is_recordable_question(question):
            return 0
        rows = (db.query(KnowledgeCandidate)
                .filter(KnowledgeCandidate.tenant_id == tenant_id,
                        KnowledgeCandidate.question_hash == question_hash(question),
                        KnowledgeCandidate.answer_source == "none").all())
        for row in rows:
            row.answer_source = "operator"
            row.answer_draft = text[:2000]
        if rows:
            db.commit()
        return len(rows)
    except Exception as exc:
        logger.warning("knowledge answer backfill failed",
                       extra={"tenant_id": tenant_id,
                              "conversation_id": conversation_id, "error": repr(exc)})
        db.rollback()
        return 0


def _maybe_auto_learn(db: Session, tenant_id: int, row: KnowledgeCandidate) -> bool:
    """达标则自动固化为知识文档（需：开关开启 + 有可信答案 + 达阈值 + 未处理）。

    `rejected` 是**人工终态**：拒绝（reject_candidate）与撤销（revoke_candidate）
    都会落到该状态，两者都表达"这条线索不应入库"的人工判断。若允许后续提问把它
    重新翻成 auto_learned，人工拒绝会被静默推翻——实测可复现：拒绝一条候选后
    同类问题再出现 1 次、hit_count 达阈值，即被重新入库。故此处直接短路。
    """
    cfg = get_learning_config(db, tenant_id)
    if not cfg.get("auto_learn_enabled"):
        return False
    if row.status == "rejected":
        return False          # 人工终态：拒绝/撤销后不得被后续提问复活
    if row.answer_source != "operator" or not row.answer_draft:
        return False          # 红线：无人工验证的答案绝不入库
    if row.hit_count < int(cfg.get("auto_learn_threshold", 5)):
        return False
    if row.status in ("approved", "auto_learned") and row.doc_id:
        return False
    doc = _create_doc(db, tenant_id, row, auto=True)
    row.status = "auto_learned"
    row.auto_learned = True
    row.doc_id = doc.id
    db.commit()
    return True


def _create_doc(db: Session, tenant_id: int, row: KnowledgeCandidate, auto: bool) -> KnowledgeDoc:
    """把候选固化为知识文档。source 如实标记来源，便于识别与批量回退。"""
    doc = KnowledgeDoc(
        tenant_id=tenant_id,
        title=f"[客服沉淀] {row.question_text[:80]}",
        content=f"问题：{row.question_text}\n\n回复：{row.answer_draft}",
        source="auto_learned" if auto else "support_candidate",
        tags=["客服", "auto_learned"] if auto else ["客服"],
    )
    db.add(doc)
    db.flush()
    return doc


def approve_candidate(db: Session, tenant_id: int, candidate_id: int,
                      answer: str = "") -> dict:
    """采纳候选为知识文档。需有答案（人工补写或 operator 回复过）。"""
    row = _owned(db, tenant_id, candidate_id)
    if row.status == "rejected":
        raise ValueError("已拒绝的候选不可采纳")
    if answer.strip():
        row.answer_source = "operator"
        row.answer_draft = answer.strip()[:2000]
    if row.answer_source != "operator" or not row.answer_draft:
        # 安全红线：无答案不可入库（AI 不编答案）
        raise ValueError("该候选没有人工验证过的答案，请先补写答案再采纳")
    if row.doc_id:
        return to_dict(row)
    doc = _create_doc(db, tenant_id, row, auto=False)
    row.status = "approved"
    row.doc_id = doc.id
    db.commit()
    return to_dict(row)


def update_answer(db: Session, tenant_id: int, candidate_id: int, answer: str) -> dict:
    """人工补写/修正候选答案。

    守卫（P1 修复）：已入库（approved / auto_learned 且已有 doc_id）的候选禁止
    直接改写答案——文档内容在 `_create_doc` 时就已固化，改候选不会回写文档，
    结果是"候选记录与知识库内容不一致"，且审计无法判断哪份是准的。
    要改已入库知识，应先 revoke（回收文档）再重新补答案采纳。
    """
    text = (answer or "").strip()
    if not text:
        raise ValueError("答案不能为空")
    row = _owned(db, tenant_id, candidate_id)
    if row.doc_id and row.status in ("approved", "auto_learned"):
        raise ValueError("该候选已入库为知识文档，请先撤销再修改答案")
    row.answer_source = "operator"
    row.answer_draft = text[:2000]
    db.commit()
    return to_dict(row)


def _detach_and_remove_doc(db: Session, tenant_id: int, row: KnowledgeCandidate) -> bool:
    """解除候选对知识文档的引用，并删除该文档（同租户校验）。返回是否真删了。"""
    removed = False
    if row.doc_id:
        doc = db.get(KnowledgeDoc, row.doc_id)
        if doc and doc.tenant_id == tenant_id:
            db.delete(doc)
            removed = True
        row.doc_id = None
    row.auto_learned = False
    return removed


def reject_candidate(db: Session, tenant_id: int, candidate_id: int) -> dict:
    """拒绝候选：标记 rejected（人工终态），并回收它已生成的知识文档。

    为什么必须回收：已采纳（approved）的候选若只改状态，文档会留在知识库里，
    候选却显示 rejected —— 审计无法从文档追溯到"它已被人工否决"，形成
    "已否决的知识仍在被检索"的静默污染。回收后 reject 与 revoke 语义收敛：
    两者都表达"这条线索不应作为知识存在"。
    """
    row = _owned(db, tenant_id, candidate_id)
    removed = _detach_and_remove_doc(db, tenant_id, row)
    row.status = "rejected"
    db.commit()
    out = to_dict(row)
    out["doc_removed"] = removed
    return out


def revoke_candidate(db: Session, tenant_id: int, candidate_id: int) -> dict:
    """撤销：删除已入库文档并标记 rejected（红线：自动学习必须可撤销）。"""
    row = _owned(db, tenant_id, candidate_id)
    removed = _detach_and_remove_doc(db, tenant_id, row)
    row.status = "rejected"
    db.commit()
    out = to_dict(row)
    out["doc_removed"] = removed
    return out


def list_candidates(db: Session, tenant_id: int, status: str = "",
                    min_hits: int = 0, limit: int = 100) -> list[dict]:
    q = db.query(KnowledgeCandidate).filter(KnowledgeCandidate.tenant_id == tenant_id)
    if status:
        q = q.filter(KnowledgeCandidate.status == status)
    if min_hits:
        q = q.filter(KnowledgeCandidate.hit_count >= min_hits)
    rows = (q.order_by(KnowledgeCandidate.hit_count.desc(),
                       KnowledgeCandidate.last_seen_at.desc())
            .limit(max(1, min(500, limit))).all())
    return [to_dict(r) for r in rows]


def _owned(db: Session, tenant_id: int, candidate_id: int) -> KnowledgeCandidate:
    row = db.get(KnowledgeCandidate, candidate_id)
    if not row or row.tenant_id != tenant_id:
        raise ValueError("候选不存在")
    return row


def to_dict(row: KnowledgeCandidate) -> dict:
    return {
        "id": row.id, "question_text": row.question_text, "intent": row.intent,
        "hit_count": row.hit_count, "answer_source": row.answer_source,
        "answer_draft": row.answer_draft, "status": row.status,
        "doc_id": row.doc_id, "auto_learned": row.auto_learned,
        "conversation_id": row.conversation_id,
        "last_seen_at": row.last_seen_at.strftime("%Y-%m-%d %H:%M:%S") if row.last_seen_at else "",
        "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "",
    }
