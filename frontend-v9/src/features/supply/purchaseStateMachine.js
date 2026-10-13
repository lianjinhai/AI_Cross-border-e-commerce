/**
 * 采购单状态机纯函数（UX-D #12 拆分页）：与 backend/app/routers/purchases.py
 * update_po 的 allowed 映射对齐；draft 提交前需供应商尽调通过（后端 409 拦截）。
 */

/** 状态文案/标签色（沿用旧 Suppliers.vue PO_STATUS，文案一字未改）。 */
export const PO_STATUS = {
  draft: { text: '草稿', tag: 'info' },
  submitted: { text: '已提交', tag: 'warning' },
  received: { text: '已入库', tag: 'success' },
  cancelled: { text: '已取消', tag: 'danger' },
}

/** 主链（图示）：草稿 → 已提交 → 已入库；取消为旁路终态。 */
export const PO_MAIN_FLOW = ['draft', 'submitted', 'received']

/** 合法流转表（= purchases.py update_po allowed 映射）。 */
export const PO_TRANSITIONS = {
  draft: ['submitted', 'cancelled'],
  submitted: ['received', 'cancelled'],
  received: [],
  cancelled: [],
}

export function canTransition(from, to) {
  return Boolean(from && to) && (PO_TRANSITIONS[from] || []).includes(to)
}

export function poStatusTag(status) {
  const known = PO_STATUS[status]
  return known ? { type: known.tag, label: known.text } : { type: 'info', label: status }
}

/**
 * 行内可用动作（按钮显隐）。
 * @returns {Array<{action: 'submit'|'receive'|'cancel', label: string, type: string}>}
 */
export function poActions(status = '') {
  if (status === 'draft') {
    return [
      { action: 'submit', label: '提交', type: 'primary' },
      { action: 'receive', label: '收货入库', type: 'success' },
      { action: 'cancel', label: '取消', type: 'danger' },
    ]
  }
  if (status === 'submitted') {
    return [
      { action: 'receive', label: '收货入库', type: 'success' },
      { action: 'cancel', label: '取消', type: 'danger' },
    ]
  }
  return []
}
