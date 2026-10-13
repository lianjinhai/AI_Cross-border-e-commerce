/**
 * 订单状态机纯函数（UX-D #16）：与 backend/app/routers/orders.py update_status 的
 * allowed 映射逐字对齐（唯一事实源在后端，前端只做预校验与图示，不做第二套放行逻辑）。
 */

/** 状态文案（沿用旧 Orders.vue statusLabel，文案一字未改）。 */
export const ORDER_STATUS_LABELS = {
  pending: '待支付',
  paid: '已付款',
  shipped: '已发货',
  delivered: '已签收',
  refunded: '已退款',
}

/** 合法流转表（= orders.py allowed 映射）。 */
export const ORDER_TRANSITIONS = {
  pending: ['paid', 'refunded'],
  paid: ['shipped', 'refunded'],
  shipped: ['delivered', 'refunded'],
  delivered: ['refunded'],
  refunded: [],
}

/** 主链（状态机图示用）：待支付 → 已付款 → 已发货 → 已签收；已退款为旁路终态。 */
export const ORDER_MAIN_FLOW = ['pending', 'paid', 'shipped', 'delivered']
export const ORDER_SIDE_STATUSES = ['refunded']

/** 是否允许 from → to 流转（未知状态一律 false，fail-closed）。 */
export function canTransition(from, to) {
  return Boolean(from && to) && (ORDER_TRANSITIONS[from] || []).includes(to)
}

/** 当前状态可选的下一个状态（下拉用，排除自身）。 */
export function nextStatusOptions(status) {
  return (ORDER_TRANSITIONS[status] || []).filter((s) => s !== status)
}

/**
 * 履约链（发货后下文图示）。物流轨迹能力后端未接入：shipped 步骤恒带
 * 「物流轨迹跟踪 · 待接入」标注，不放可点击入口（矩阵 #16 验收）。
 */
export function fulfillmentChain(status = '') {
  const chain = [
    { key: 'paid', label: '已付款', state: 'done' },
    { key: 'shipped', label: '已发货', state: 'pending', note: '物流轨迹跟踪 · 待接入' },
    { key: 'delivered', label: '已签收', state: 'pending' },
  ]
  const reached = ['paid', 'shipped', 'delivered'].indexOf(status)
  if (reached >= 0) {
    chain.forEach((step, i) => { step.state = i <= reached ? 'done' : 'pending' })
  }
  return chain
}

/**
 * 订单时间线（AuditTimeline 步骤）。后端仅 created_at/updated_at 可靠，
 * 未发生的步骤不伪造时间；发货步恒标注物流轨迹待接入。
 */
export function orderTimeline(order = {}) {
  const status = order.status || ''
  const steps = [
    { key: 'created', label: '订单创建', state: 'done', time: order.created_at || '' },
    { key: 'paid', label: '已付款', state: 'pending', description: '' },
    { key: 'shipped', label: '已发货', state: 'pending', description: '物流轨迹跟踪 · 待接入' },
    { key: 'delivered', label: '已签收', state: 'pending', description: '' },
  ]
  const reached = ORDER_MAIN_FLOW.indexOf(status)
  if (reached >= 0) {
    steps.forEach((step, i) => {
      if (i <= reached) step.state = 'done'
    })
    if (reached >= 1) steps[1].time = order.updated_at || ''
  }
  if (status === 'refunded') {
    steps.push({ key: 'refunded', label: '已退款', state: 'error', time: order.updated_at || '' })
  }
  return steps
}

/**
 * 解析后端 CSV 导入错误串为逐行报告（矩阵 #16：CSV 错误行列出原因）。
 * 后端格式：`第{ln}行({订单号|无订单号}): {原因}`；未匹配整行原样作为 reason。
 */
export function parseImportErrors(errors = []) {
  return (errors || []).map((raw) => {
    const matched = /^第(\d+)行\((.*)\):\s*(.*)$/.exec(String(raw || ''))
    if (!matched) return { row: null, orderNo: '', reason: String(raw || '') }
    return { row: Number(matched[1]), orderNo: matched[2], reason: matched[3] }
  })
}

/** CSV 导入格式提示（沿用旧 Orders.vue 文案）。 */
export const CSV_IMPORT_HINT = '表头需含：订单号(external_no)、金额(amount)；' +
  '可选 platform/status/qty/sku/country/buyer_name/created_at。按订单号去重。'
