/**
 * 结算单状态机纯函数（UX-D #18）：与 backend/app/routers/settlements.py 的
 * allowed 映射对齐（pending→confirmed→paid，paid 为终态不可再编辑）。
 */

/** 状态文案/标签色（沿用旧 Settlements.vue ST_STATUS）。 */
export const SETTLE_STATUS = {
  pending: { text: '对账中', tag: 'warning' },
  confirmed: { text: '已确认', tag: 'primary' },
  paid: { text: '已付款', tag: 'success' },
}

/** 主链（图示）：生成(pending) → 确认(confirmed) → 付款(paid)。 */
export const SETTLE_FLOW = ['pending', 'confirmed', 'paid']

/** 合法流转表（= settlements.py allowed 映射）。 */
export const SETTLE_TRANSITIONS = {
  pending: ['confirmed'],
  confirmed: ['paid'],
  paid: [],
}

export function canTransition(from, to) {
  return Boolean(from && to) && (SETTLE_TRANSITIONS[from] || []).includes(to)
}

/**
 * 当前状态可用的按钮（显隐即状态机图示的一部分）。
 * 已付款对账单无任何可操作按钮（不可再编辑，验收 #18-③）。
 */
export function settleActions(status = '') {
  if (status === 'pending') return [{ status: 'confirmed', label: '确认对账', type: 'primary' }]
  if (status === 'confirmed') return [{ status: 'paid', label: '标记已付款', type: 'success' }]
  return []
}

/** 状态标签解析（未知状态原样返回，info 色）。 */
export function settleStatusTag(status) {
  const known = SETTLE_STATUS[status]
  return known ? { type: known.tag, label: known.text } : { type: 'info', label: status }
}
