/**
 * 金额展示纯函数（蓝图 §6.5，包 1 P0 共享组件 MoneyValue 纯函数下沉）。
 *
 * 规则：必显币种 + 汇率基准日 + 估算/已结算标签；缺值不渲染 0（显"—"）；缺 fxDate 显"汇率未知"。
 * 例外：本位币 CNY 不需要换算，"汇率未知"对它属假缺项，不标注（B3 口径修正）。
 */

/** 本位币：与后端 costing 的换算基准一致。 */
export const BASE_CURRENCY = 'CNY'

/**
 * 判定金额值是否缺失（不渲染 0）。
 * null/undefined/''/NaN → true。
 *
 * @param {*} value
 * @returns {boolean}
 */
export function isMissing(value) {
  if (value === null || value === undefined || value === '') return true
  if (typeof value === 'number' && Number.isNaN(value)) return true
  if (typeof value === 'string' && value.trim() === '') return true
  return false
}

/**
 * 渲染金额展示串。
 * 缺值 → "—"（不渲染 0）。
 * 有值 → "{formatted} {currency}"（如 "1,234.56 USD"）。
 *
 * @param {object} p
 * @param {number|string|null} p.value 金额值。
 * @param {string} [p.currency] 币种。
 * @param {string} [p.analysisCurrency] 分析币种（换算目标）。
 * @param {string} [p.fxDate] 汇率基准日。
 * @param {boolean} [p.estimated] 是否估算。
 * @param {string} [p.unit] 'unit'|'total'（影响标签文案，不影响格式）。
 * @returns {string} 展示串。
 */
export function renderMoney(p = {}) {
  const { value, currency = '', analysisCurrency = '', fxDate = '', estimated = false, unit = '' } = p
  if (isMissing(value)) return '—'
  const num = Number(value)
  if (Number.isNaN(num)) return '—'
  const formatted = num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  let result = `${formatted} ${currency || ''}`.trim()
  if (analysisCurrency && analysisCurrency !== currency) {
    result += `（分析口径：${analysisCurrency}）`
  }
  // 本位币（CNY）不需要汇率：给它标「汇率未知」是假缺项，会让人误以为成本不可算。
  if (fxDate) result += ` · 汇率 ${fxDate}`
  else if (currency && String(currency).toUpperCase() !== BASE_CURRENCY) result += ' · 汇率未知'
  if (estimated) result += ' · 估算'
  if (unit) result += ` · ${unit === 'unit' ? '单价' : '合计'}`
  return result
}

/**
 * 金额标签（估算/已结算）—— MoneyValue 角标用。
 *
 * @param {boolean} [estimated] 估算。
 * @param {boolean} [settled] 已结算。
 * @returns {string} '估算'|'已结算'|''
 */
export function moneyTag(estimated = false, settled = false) {
  if (estimated) return '估算'
  if (settled) return '已结算'
  return ''
}
