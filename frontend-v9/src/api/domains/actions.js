import api from '../../shared/api/client'

/**
 * actions 域（契约 §4.2）：对应 backend/app/routers/actions.py（独立前缀 /actions）。
 * ApprovalPanel 统一消费；执行回执含成功/失败态，失败可重试。
 */

/** 动作列表：GET /actions → {items[], total}。 */
export async function fetchActions({ status, type, page } = {}) {
  return (await api.get('/actions', {
    params: { status, action_type: type, page_num: page },
  })).data
}

/** 审批通过：POST /actions/{id}/approve → 审批回执。 */
export async function approve(id, data = {}) {
  return (await api.post(`/actions/${id}/approve`, data)).data
}

/** 审批拒绝：POST /actions/{id}/reject {note: reason} → 审批回执。 */
export async function reject(id, { reason = '' } = {}) {
  return (await api.post(`/actions/${id}/reject`, { note: reason })).data
}

/** 执行动作：POST /actions/{id}/execute → 执行回执（含成功/失败态，失败可重试）。 */
export async function execute(id) {
  return (await api.post(`/actions/${id}/execute`)).data
}
