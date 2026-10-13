/**
 * 数据真实性标签（蓝图 §6.5，包 1 P0 横切）。
 *
 * 8 种标签——不要用全站单一"已同步"混淆真实性。
 * 金额必带字段（币种/汇率基准日/估算状态）由 moneyLabel() 产出。
 * 部署环境标签（合同测试/演示）由 envTag() 判定，部署层注入 window.__ERP_ENV__。
 */

/** 八类数据标签（§6.5）。 */
export const DATA_TAGS = {
  OFFICIAL_VERIFIED:  { tag: 'OFFICIAL_VERIFIED',  label: '官方平台已核验',     tone: 'success' },
  API_UNVERIFIED:     { tag: 'API_UNVERIFIED',     label: '平台API已返回待业务验证', tone: 'info' },
  MANUAL_UNVERIFIED:  { tag: 'MANUAL_UNVERIFIED',  label: '人工录入未核验',     tone: 'warning' },
  EXTERNAL_IMPORT:    { tag: 'EXTERNAL_IMPORT',    label: '外部导入',          tone: 'info' },
  CONTRACT_TEST:      { tag: 'CONTRACT_TEST',      label: '合同测试',          tone: 'neutral' },
  DEMO:               { tag: 'DEMO',               label: '演示',              tone: 'neutral' },
  AI_ESTIMATED:       { tag: 'AI_ESTIMATED',       label: 'AI估算',            tone: 'warning' },
  UNKNOWN:            { tag: 'UNKNOWN',            label: '数据未知',          tone: 'neutral' },
}

/** 标签码集合（便于断言/遍历）。 */
export const DATA_TAG_CODES = Object.keys(DATA_TAGS)

/**
 * 取某标签定义（未知码回 UNKNOWN）。
 * @param {string} code 标签码（DATA_TAGS 的 key）。
 * @returns {{tag:string, label:string, tone:string}}
 */
export function tagInfo(code) {
  return DATA_TAGS[code] || DATA_TAGS.UNKNOWN
}

/**
 * 金额必带字段（币种/汇率基准日/估算状态）—— MoneyValue 消费。
 * 缺 fxDate 显"汇率未知"；estimated 优先于 settled。
 *
 * @param {object} p
 * @param {string} [p.currency] 币种（如 USD/CNY/EUR）。
 * @param {string} [p.fxDate]   汇率基准日（如 2025-01-01）。
 * @param {boolean} [p.estimated] 是否估算。
 * @param {boolean} [p.settled]  是否已结算。
 * @returns {string} 展示串（如 "USD · 汇率 2025-01-01 · 估算"）。
 */
export function moneyLabel({ currency = '', fxDate = '', estimated = false, settled = false } = {}) {
  const parts = [currency, fxDate ? `汇率 ${fxDate}` : '汇率未知']
  if (estimated) parts.push('估算')
  else if (settled) parts.push('已结算')
  return parts.filter(Boolean).join(' · ')
}

/**
 * 部署环境标签常显判定（合同测试/演示环境，部署层注入 window.__ERP_ENV__）。
 * PROD/缺省 → null（不常显）。
 *
 * @returns {{tag:string,label:string,tone:string}|null}
 */
export function envTag() {
  const env = (typeof window !== 'undefined' && window.__ERP_ENV__) || 'PROD'
  if (env === 'CONTRACT_TEST') return DATA_TAGS.CONTRACT_TEST
  if (env === 'DEMO') return DATA_TAGS.DEMO
  return null
}
