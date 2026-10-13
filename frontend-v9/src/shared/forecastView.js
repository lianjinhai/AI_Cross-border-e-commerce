/**
 * 预测与数据质量（BI-02）纯函数模块。
 *
 * 预测端点未核（§7#10）→ 预测区"待接入"；数据质量区基于 finance.js/orders.js
 * 真实缺项统计（缺汇率 / 缺费用 / 缺成本 / 来源混合），未达商用门槛显"仅参考"。
 */

/** 数据质量四类缺项定义（顺序即渲染顺序）。 */
export const DQ_GAPS = [
  { key: 'fx_missing', label: '缺汇率', hint: '财务订单缺汇率行，跳汇率页补录' },
  { key: 'fee_missing', label: '缺费用', hint: '订单费用缺项，跳财务明细补录' },
  { key: 'cost_missing', label: '缺成本', hint: '订单行缺采购成本，跳采购单补齐' },
  { key: 'source_mixed', label: '来源混合', hint: '真实/演示/导入来源混杂，跳订单明细核对' },
]

/**
 * 统计某缺项在订单集内的命中数量（纯函数，不做 API）。
 * 判定规则：
 * - fx_missing：order.fx 为 null/undefined。
 * - fee_missing：order.fees 数组缺项（长度为 0）。
 * - cost_missing：order.lines 中缺 cost 字段的行数 > 0。
 * - source_mixed：order.source 属于 {'real','demo','import','mixed'} 中出现 2+ 种。
 *
 * @param {Array} orders 订单列表。
 * @returns {object} 缺项码 → 数量。
 */
export function countDataQualityGaps(orders = []) {
  const list = Array.isArray(orders) ? orders : []
  const counts = { fx_missing: 0, fee_missing: 0, cost_missing: 0, source_mixed: 0 }
  const sourceSet = new Set()
  for (const o of list) {
    if (!o) continue
    if (o.fx == null) counts.fx_missing += 1
    if (Array.isArray(o.fees) && o.fees.length === 0) counts.fee_missing += 1
    const lines = Array.isArray(o.lines) ? o.lines : []
    if (lines.some((l) => l && (l.cost == null))) counts.cost_missing += 1
    if (o.source) sourceSet.add(o.source)
  }
  // 来源混合为全局判定：2+ 种来源出现即为命中（不逐单累加，避免重复计数）
  if (sourceSet.size >= 2) counts.source_mixed = list.length
  return counts
}

/**
 * 缺项明细行（供 DataQualityBanner / 表格渲染）。
 * @returns {Array<{key,label,hint,count}>}
 */
export function dataQualityRows(orders = []) {
  const counts = countDataQualityGaps(orders)
  return DQ_GAPS.map((g) => ({ ...g, count: counts[g.key] }))
}

/**
 * 商用门槛判定：预测模型端点未核（§7#10）→ 永远 isCommercialReady=false；
 * 页面须显"仅参考"，禁自动采购。
 *
 * @param {object} p
 * @param {boolean} [p.modelEndpointAvailable] 预测模型端点是否已核（当前恒 false）。
 * @returns {{isCommercialReady:boolean, label:string}}
 */
export function forecastCommercialGate({ modelEndpointAvailable = false } = {}) {
  const isCommercialReady = Boolean(modelEndpointAvailable)
  return {
    isCommercialReady,
    label: isCommercialReady ? '商用' : '仅参考',
  }
}

/**
 * 11 态码映射：预测区缺端点 → NOT_CONFIGURED；数据质量有缺项 → PARTIAL_DATA；
 * 都齐 → ready。
 *
 * @param {object} p
 * @param {boolean} [p.modelEndpointAvailable]
 * @param {Array} [p.orders] 订单列表（用于数据质量）。
 * @returns {string} 'NOT_CONFIGURED' | 'PARTIAL_DATA' | 'ready'
 */
export function forecastSectionState({ modelEndpointAvailable = false, orders = [] } = {}) {
  const gate = forecastCommercialGate({ modelEndpointAvailable })
  const rows = dataQualityRows(orders)
  const dqDirty = rows.some((r) => r.count > 0)
  if (!gate.isCommercialReady) return 'NOT_CONFIGURED'
  if (dqDirty) return 'PARTIAL_DATA'
  return 'ready'
}
