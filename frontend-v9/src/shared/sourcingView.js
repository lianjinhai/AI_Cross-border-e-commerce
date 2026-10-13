/**
 * 货源发现（SU-01）纯函数模块。
 *
 * 三个来源 Tab：1688 / 工厂（私域） / 手动供应商。
 * 1688 端点未核（§7#7）→ Tab 明示"未接入，手动添加可用"；工厂/手动供应商走 suppliers.js 真实数据。
 * 筛选：SKU / 成本币种 / MOQ / 交期。
 */

/** 来源 Tab 定义（顺序即渲染顺序；1688 恒首，明示未接入不作 Sales 标签）。 */
export const SOURCING_TABS = [
  { key: '1688', label: '1688', apiGap: true, hint: '1688 未接入，手动添加供应商可用' },
  { key: 'factory', label: '私域工厂', apiGap: false, hint: '' },
  { key: 'manual', label: '手动供应商', apiGap: false, hint: '' },
]

/**
 * 分列某来源 Tab 的供应商/工厂列表（纯函数，便于测试）。
 * 1688 Tab 恒空 + 待接入标记；factory/manual 依 source 字段分列。
 *
 * @param {Array} items suppliers.js 返回的 items（含 source: 'factory'|'manual' 可选字段）。
 * @param {string} activeTab '1688'|'factory'|'manual'。
 * @returns {{ items: Array, apiGap: boolean, hint: string }} 该 Tab 的展示数据。
 */
export function splitSourcingTab(items = [], activeTab = 'factory') {
  const tab = SOURCING_TABS.find((t) => t.key === activeTab) || SOURCING_TABS[1]
  if (tab.apiGap) {
    // 1688 端点未核（§7#7）→ 不渲染假数据，空列 + 待接入标记
    return { items: [], apiGap: true, hint: tab.hint }
  }
  const list = Array.isArray(items) ? items : []
  return {
    items: list.filter((i) => (i?.source || 'manual') === tab.key),
    apiGap: false,
    hint: tab.hint,
  }
}

/**
 * 应用筛选（SKU/成本币种/MOQ/交期）— 纯函数（不做任何 API 调用）。
 * 字段对齐 suppliers 明细：`skus`/`cost_currency`/`moq`/`ship_days`。
 *
 * @param {Array} items 供应商/工厂列表。
 * @param {object} filter { sku, costCurrency, moqMax, shipDaysMax } 各项缺省/空串=不过滤。
 * @returns {Array} 过滤后列表（新数组）。
 */
export function filterSourcing(items = [], filter = {}) {
  if (!Array.isArray(items)) return []
  const { sku = '', costCurrency = '', moqMax = null, shipDaysMax = null } = filter
  return items.filter((i) => {
    if (!i) return false
    if (sku) {
      const skus = Array.isArray(i.skus) ? i.skus : []
      if (!skus.some((s) => String(s || '').toLowerCase().includes(String(sku).toLowerCase()))) return false
    }
    if (costCurrency && i.cost_currency && i.cost_currency !== costCurrency) return false
    if (moqMax != null && i.moq != null && i.moq > Number(moqMax)) return false
    if (shipDaysMax != null && i.ship_days != null && i.ship_days > Number(shipDaysMax)) return false
    return true
  })
}

/**
 * 1688 未接标记判定（纯函数，返回明示文案）。
 * @returns {{apiGap:boolean, hint:string}}
 */
export function flag1688Gap() {
  return { apiGap: true, hint: '1688 未接入，手动添加供应商可用' }
}
