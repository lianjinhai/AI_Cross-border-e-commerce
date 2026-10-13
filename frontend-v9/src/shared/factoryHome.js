/**
 * 工厂门户首页纯函数（蓝图 R1 包 3 · FP-01 本厂待办，§B.3 / 差距 §2.10）。
 *
 * FP-01：/factory 首页（重定向目标）—— 本厂待办（报价 N 条 / 备货 N 个 / 贴标 N 次）
 * + 我方 SKU 侧栏。待办数据源 factory_network portal 端点**未核** →
 * 未接入时一律落"暂无任务"空态，禁止编造待办计数、禁止渲染卖家财务字段。
 *
 * 组件（FactoryHome.vue）只消费本模块纯函数。
 */

/** 待办分组（蓝图 §5.18 顶部任务条三类）。 */
export const TODO_GROUPS = [
  { code: 'quote', label: '报价' },
  { code: 'stocking', label: '备货' },
  { code: 'labeling', label: '贴标' },
]

/**
 * 待办数据可用判定：仅当门户端点显式返回 todos 数组才视为已接入。
 * 缺字段 / 空响应 → 未接入（不据此推计数，避免误报）。
 * @param {object} [portalMe] fetchPortalMe 返回体（{supplier, todos?...}）。
 * @returns {boolean}
 */
export function hasTodoSource(portalMe) {
  return Boolean(portalMe && Array.isArray(portalMe.todos) && portalMe.todos.length >= 0
    && Object.prototype.hasOwnProperty.call(portalMe, 'todos'))
}

/**
 * 待办分组计数（仅统计有数据的组；缺数据源返回全 0 且标记未接入）。
 * @param {object} [portalMe]
 * @returns {{quote:number, stocking:number, labeling:number, total:number, connected:boolean}}
 */
export function todoCounts(portalMe) {
  const empty = { quote: 0, stocking: 0, labeling: 0, total: 0, connected: false }
  if (!hasTodoSource(portalMe)) return empty
  const counts = { quote: 0, stocking: 0, labeling: 0 }
  for (const item of portalMe.todos) {
    const kind = item?.kind || item?.group || ''
    if (Object.prototype.hasOwnProperty.call(counts, kind)) counts[kind] += 1
  }
  const total = counts.quote + counts.stocking + counts.labeling
  return { ...counts, total, connected: true }
}

/**
 * 首页主态（11 态码）：未接数据源 → EMPTY_NEW（暂无任务）；加载 → LOADING；
 * 出错 → ERROR；有数据 → ready。
 * @param {boolean} loading
 * @param {boolean} hasError
 * @param {object} [counts] todoCounts 结果。
 * @returns {string}
 */
export function homeStateCode(loading, hasError, counts = {}) {
  if (loading) return 'LOADING'
  if (hasError) return 'ERROR'
  if (counts.connected && counts.total > 0) return 'ready'
  return 'EMPTY_NEW'
}

/**
 * 首页空态文案（"暂无任务"语境，集中于此不页面自写）。
 * @returns {{title:string, detail:string}}
 */
export function emptyHomeCopy() {
  return {
    title: '暂无任务',
    detail: '本厂待办（报价/备货/贴标）数据源尚未接入；接入后这里会显示待处理数量。',
  }
}

/**
 * 我方 SKU 侧栏行数（只收工厂身份绑定 DTO；不渲染卖家平台核价/底价/GMV/利润）。
 * @param {Array} [items]
 * @returns {number}
 */
export function skuSidebarCount(items) {
  return Array.isArray(items) ? items.length : 0
}
