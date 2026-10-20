import api from '../../shared/api/client'

/**
 * actions 域（契约 §4.2）：对应 backend/app/routers/actions.py（独立前缀 /actions）。
 * ApprovalPanel 统一消费；执行回执含成功/失败态，失败可重试。
 *
 * S3：列表支持「全部」类型/状态 + 服务端分页总数（不再由前端按状态各查一页拼接）；
 * 新增单条详情与回执查询，刷新/重进页面可恢复同一 Action。
 */

/** 动作列表：GET /actions?action_type&status&page_num&page_size → {items[], total, page_num, page_size}。 */
export async function fetchActions({ status, type, page, pageSize } = {}) {
  return (await api.get('/actions', {
    params: {
      status: status || undefined,
      action_type: type || undefined,
      page_num: page || 1,
      page_size: pageSize || undefined,
    },
  })).data
}

/** 单条详情：GET /actions/{id}（含证据/预期影响/状态/时间线）。 */
export async function fetchAction(id) {
  return (await api.get(`/actions/${id}`)).data
}

/** 执行回执：GET /actions/{id}/result → {status, outcome, terminal, executed_at}。 */
export async function fetchActionResult(id) {
  return (await api.get(`/actions/${id}/result`)).data
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
