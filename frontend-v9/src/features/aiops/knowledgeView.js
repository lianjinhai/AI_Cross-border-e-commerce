/**
 * 知识库视图模型（UX-E #21，纯函数）。
 * 候选状态机与按钮可见性判定对照 backend/app/services/knowledge_learning.py：
 * 无人工验证答案（answer_source=none）的候选永不可采纳（安全红线）。
 */

export const CANDIDATE_STATUS_LABELS = {
  pending: '待处理',
  approved: '已采纳',
  auto_learned: 'AI 已固化',
  rejected: '已拒绝',
}

export const CANDIDATE_STATUS_TYPES = {
  pending: 'info',
  approved: 'primary',
  auto_learned: 'success',
  rejected: 'danger',
}

export function candidateStatusLabel(status) {
  return CANDIDATE_STATUS_LABELS[status] || status
}

export function candidateStatusType(status) {
  return CANDIDATE_STATUS_TYPES[status] || 'info'
}

/** 文档来源文案（auto_learned / support_candidate 为后端真实写入值）。 */
export const DOC_SOURCE_LABELS = {
  auto_learned: 'AI 自动固化',
  support_candidate: '客服沉淀',
}

export function docSourceLabel(source) {
  return DOC_SOURCE_LABELS[source] || source || ''
}

/** 可补写答案：尚无人工验证答案（与旧页「补答案」按钮条件一致）。 */
export function canAnswer(candidate) {
  return candidate?.answer_source === 'none'
}

/** 可采纳：有人工验证答案且仍待处理（红线：无验证答案不可入库）。 */
export function canApprove(candidate) {
  return candidate?.answer_source === 'operator' && candidate?.status === 'pending'
}

/** 可撤销入库：已生成知识文档。 */
export function canRevoke(candidate) {
  return Boolean(candidate?.doc_id)
}

/** 可拒绝：未被拒绝过。 */
export function canReject(candidate) {
  return candidate?.status !== 'rejected'
}

/** 高频问题预警阈值（≥5 次标红，与旧页一致）。 */
export const HIT_WARN_THRESHOLD = 5

export function hitTagType(hitCount) {
  return hitCount >= HIT_WARN_THRESHOLD ? 'danger' : 'info'
}

/** 候选行动作集（供表格渲染决策，避免模板里堆条件）。 */
export function candidateActions(candidate) {
  return {
    answer: canAnswer(candidate),
    approve: canApprove(candidate),
    revoke: canRevoke(candidate),
    reject: canReject(candidate),
  }
}
