/**
 * 核价报价轮次视图（M2-A）：把后端 `price_rounds` 行翻成可直接渲染的字段。
 *
 * 抽成纯函数的原因和其他批次一致：前端没有 @vue/test-utils，逻辑留在组件里就测不到。
 *
 * 三条不可让步的渲染口径：
 * 1. **金额必须带币种**：有 `currency` 就绑定，没有就显「—」。**禁止默认 `$`**——
 *    一个没有币种的金额，写上 `$` 就是凭空断言它是美元。
 * 2. **轮次是只增不改的历史**：这里只做展示，不提供任何「覆盖上一轮」的表达。
 * 3. **本地报价 ≠ 平台已核价**：`note` 与 `source` 必须能看出这是本地轮次，
 *    不能让界面读起来像「平台已经同意了」。
 */

export const ROUND_ACTION_LABELS = {
  REPORT: '申报报价',
  COUNTER: '还价',
  ACCEPT: '接受报价',
}

/** 金额 + 币种（无币种一律「—」，不给符号）。 */
export function roundMoney(value, currency) {
  const code = String(currency || '').trim().toUpperCase()
  if (!code) return '—'
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) {
    return `${code} —`
  }
  return `${code} ${Number(value)}`
}

/** 百分比渲染：后端毛利是 0-1 小数，空值显「—」。 */
export function roundPercent(value) {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

/**
 * 低价门禁文案：低于门槛时给出具体两个数字，达标时返回 null（不显示红条）。
 * 与后端 `_require_margin_ok` 用同一口径，前端不另算一遍毛利。
 */
export function priceGateMessage(margin, minMargin) {
  if (margin === null || margin === undefined || minMargin === null || minMargin === undefined) {
    return null
  }
  const current = Number(margin)
  const floor = Number(minMargin)
  if (Number.isNaN(current) || Number.isNaN(floor) || current >= floor) return null
  return `售价毛利 ${(current * 100).toFixed(1)}% 低于最低要求 ${(floor * 100).toFixed(1)}%，不能提交核价`
}

/** 单轮次视图模型。 */
export function roundView(row) {
  const action = String(row?.action || '').toUpperCase()
  const gate = row?.margin_ok === true
  return {
    id: row?.id ?? null,
    roundNo: row?.round_no ?? null,
    action,
    actionLabel: ROUND_ACTION_LABELS[action] || action || '—',
    priceText: roundMoney(row?.price, row?.currency),
    marginText: roundPercent(row?.margin),
    floorText: roundPercent(row?.min_margin),
    gateLabel: row?.margin_ok === true ? '过门槛' : row?.margin_ok === false ? '低于门槛' : '—',
    gateOk: gate,
    decisionLabel: String(row?.decision?.decision || '') === 'ACCEPT' ? '已接受' : '未决',
    by: row?.created_by ?? null,
    at: row?.created_at || '',
    source: '本地轮次',
  }
}

/** 列表视图模型：新→旧（后端已排序，这里不改顺序，只做映射）。 */
export function roundRows(rows) {
  if (!Array.isArray(rows)) return []
  return rows.map(roundView)
}

/** 页头汇总：总轮次、是否已有接受、最近一轮是否达标。 */
export function roundSummary(rows) {
  const list = Array.isArray(rows) ? rows : []
  const latest = list.length ? roundView(list[0]) : null
  return {
    total: list.length,
    accepted: list.some((row) => String(row?.decision?.decision || '') === 'ACCEPT'),
    latest,
    latestGateOk: latest ? latest.gateOk : null,
  }
}
