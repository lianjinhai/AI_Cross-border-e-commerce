import api from '../../shared/api/client'

/**
 * refunds 域（契约 §4.2）：对应 backend/app/routers/refunds.py（前缀 /refunds）。
 * 状态机：pending → approved/rejected；approved → returned（退货退款）→ refunded。
 * 发起退款支持从订单页预填 order_id（路由 query 透传）。
 */

/** 退款单列表：GET /refunds → {items[], total}。 */
export async function fetchRefunds({ status, page } = {}) {
  return (await api.get('/refunds', {
    params: { status, page_num: page },
  })).data
}

/** 退款单详情：GET /refunds/{id} → 退款单 DTO。 */
export async function fetchRefund(id) {
  return (await api.get(`/refunds/${id}`)).data
}

/** 发起退款：POST /refunds {order_id, type, qty, amount?, reason, restock} → DTO。 */
export async function createRefund(data = {}) {
  return (await api.post('/refunds', data)).data
}

/** 审核动作：PUT /refunds/{id}/status {status: approved|rejected, note} → DTO。 */
export async function updateRefundStatus(id, { status, note = '' } = {}) {
  return (await api.put(`/refunds/${id}/status`, { status, note })).data
}

/** 退货入库：POST /refunds/{id}/return_receive → {restocked}（回补库存件数）。 */
export async function receiveReturn(id) {
  return (await api.post(`/refunds/${id}/return_receive`, {})).data
}

/** 执行退款：POST /refunds/{id}/refund → DTO（订单联动为已退款）。 */
export async function executeRefund(id) {
  return (await api.post(`/refunds/${id}/refund`, {})).data
}
