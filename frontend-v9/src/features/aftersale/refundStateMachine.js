/**
 * 退款状态机纯函数（UX-D #17）：与 backend/app/routers/refunds.py 的动作约束对齐。
 * pending → approved/rejected；approved → returned（仅退货退款）→ refunded；
 * rejected 为终态。非法跳转由后端 400 拒绝，前端只渲染可达动作与时间线。
 */

/** 状态文案/标签色（沿用旧 Refunds.vue STATUS，文案一字未改）。 */
export const REFUND_STATUS = {
  pending: { text: '待审核', tag: 'warning' },
  approved: { text: '已同意', tag: 'primary' },
  returned: { text: '已退货', tag: 'info' },
  refunded: { text: '已退款', tag: 'success' },
  rejected: { text: '已拒绝', tag: 'danger' },
}

/** 类型文案。 */
export const REFUND_TYPE = { refund_only: '退款不退货', return_refund: '退货退款' }

export function refundStatusTag(status) {
  const known = REFUND_STATUS[status]
  return known ? { type: known.tag, label: known.text } : { type: 'info', label: status }
}

/**
 * 当前状态可执行的动作（按钮显隐 = 状态机可视化的一部分）。
 * @returns {Array<{action: string, label: string, type: string}>}
 */
export function refundActions(refund = {}) {
  const { status = '', type = 'refund_only' } = refund
  if (status === 'pending') {
    return [
      { action: 'approve', label: '同意', type: 'primary' },
      { action: 'reject', label: '拒绝', type: 'danger' },
    ]
  }
  if (status === 'approved' && type === 'return_refund') {
    return [{ action: 'receive', label: '退货入库', type: 'warning' }]
  }
  if (status === 'approved' || status === 'returned') {
    return [{ action: 'refund', label: '执行退款', type: 'success' }]
  }
  return []
}

/**
 * 退款时间线（AuditTimeline 步骤）。仅按当前状态推导已到达/未到达，
 * 不伪造中间时间；拒绝为错误态终局。
 */
export function refundTimeline(refund = {}) {
  const { status = '', type = 'refund_only', created_at: createdAt = '' } = refund
  const isReturn = type === 'return_refund'
  const steps = [
    { key: 'created', label: '买家申请 / 发起退款', state: 'done', time: createdAt },
    { key: 'review', label: '审核（同意 / 拒绝）', state: 'pending' },
  ]
  if (isReturn) steps.push({ key: 'returned', label: '退货入库', state: 'pending' })
  steps.push({ key: 'refunded', label: '执行退款到账', state: 'pending' })

  const doneUpTo = { pending: 0, approved: 1, returned: 2, refunded: isReturn ? 3 : 2 }
  const reached = doneUpTo[status] ?? 0
  steps.forEach((step, i) => { if (i <= reached && i > 0) step.state = 'done' })
  if (status === 'rejected') {
    steps[1].state = 'error'
    steps.slice(2).forEach((s) => { s.state = 'pending' })
  }
  return steps
}
