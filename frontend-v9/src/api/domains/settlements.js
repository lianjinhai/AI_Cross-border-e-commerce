import api from '../../shared/api/client'

/**
 * settlements 域（契约 §4.2）：对应 backend/app/routers/settlements.py（前缀 /settlements）。
 * 状态机：pending（对账中）→ confirmed（已确认）→ paid（已付款）。
 * 应付账龄（summary）与供应商页/财务入口同口径（同一端点）。
 */

/** 结算单列表：GET /settlements → {items[], total}。 */
export async function fetchSettlements({ status, page } = {}) {
  return (await api.get('/settlements', {
    params: { status, page_num: page },
  })).data
}

/** 应付账龄总览：GET /settlements/summary → {items[]}（按供应商）。 */
export async function fetchPayableSummary() {
  return (await api.get('/settlements/summary')).data
}

/** 生成对账单：POST /settlements/generate {supplier_id} → 结算单 DTO。 */
export async function generateSettlement(supplierId) {
  return (await api.post('/settlements/generate', { supplier_id: supplierId })).data
}

/** 状态流转：PUT /settlements/{id} {status: confirmed|paid, note?}（非法流转后端 409）。 */
export async function updateSettlement(id, { status, note = '' } = {}) {
  return (await api.put(`/settlements/${id}`, { status, note })).data
}
