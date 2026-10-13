import api from '../../shared/api/client'

/**
 * finance 域（契约 §4.2）：对应 backend/app/routers/finance.py（前缀 /finance）。
 * 财务事实工作台：汇率 / 订单行与费用 / 平台结算对账。
 * 行录入均为行内编辑表格（V9 取消 3 个录入弹窗）。
 */

/** 汇率列表：GET /finance/fx → {items[]}。 */
export async function fetchFxRates() {
  return (await api.get('/finance/fx')).data
}

/** 新增汇率：POST /finance/fx {base_currency, rate, effective_at, ...}。 */
export async function createFxRate(data = {}) {
  return (await api.post('/finance/fx', data)).data
}

/** 订单财务明细：GET /finance/orders/{id}/detail → {order, lines[], fees[]}。 */
export async function fetchOrderFinance(orderId) {
  return (await api.get(`/finance/orders/${orderId}/detail`)).data
}

/** 新增订单行：POST /finance/orders/{id}/lines → 明细。 */
export async function createOrderLine(orderId, data = {}) {
  return (await api.post(`/finance/orders/${orderId}/lines`, data)).data
}

/** 新增订单费用：POST /finance/orders/{id}/fees → 明细。 */
export async function createOrderFee(orderId, data = {}) {
  return (await api.post(`/finance/orders/${orderId}/fees`, data)).data
}

/** 平台结算对账：GET /finance/settlement-reconciliation → {items[], unreconciled}。 */
export async function fetchReconciliation() {
  return (await api.get('/finance/settlement-reconciliation')).data
}

/** 录入/更新平台结算单：POST /finance/platform-settlements（幂等保存）。 */
export async function savePlatformSettlement(data = {}) {
  return (await api.post('/finance/platform-settlements', data)).data
}
