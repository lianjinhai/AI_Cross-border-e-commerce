import api from '../shared/api/client'

/**
 * 首页经营工作台数据层（UX-04a）：消费只读 BFF `/workbench/*`。
 *
 * 只读红线：本模块**只发 GET**，绝不发起任何写请求（post/put/delete/patch）——
 * 首页的职责是「展示 + 引导」，一切变更都必须在业务页经权限与审批流程完成。
 *
 * 纯函数集中在文件后半段，供 vitest 直测（组件只消费，不重复实现判定）。
 */

/** GET /workbench/todo：跨域待办（items + counts + sources）。 */
export async function loadTodo(params = {}) {
  return (await api.get('/workbench/todo', { params })).data
}

/** GET /workbench/overview：首页 6 问聚合（sections + signals + partial + sources）。 */
export async function loadOverview(params = {}) {
  return (await api.get('/workbench/overview', { params })).data
}

// ── 纯函数（vitest 直测） ────────────────────────────────────────────────

/** 待办类别固定顺序（与后端 items[].type 一致）。 */
export const TODO_TYPES = ['launch', 'action', 'alert', 'review']

/** 严重度展示（与后端 severity 取值域一致）。 */
export const SEVERITY_TAG = { high: 'danger', mid: 'warning', low: 'info' }

/** 按 type 分组（`count`=条目数、`total`=该组待办数量之和）；未知类型排在已知之后。 */
export function todoGroups(items = []) {
  const list = Array.isArray(items) ? items : []
  const types = []
  for (const item of list) {
    const type = item?.type
    if (type && !types.includes(type)) types.push(type)
  }
  types.sort((a, b) => {
    const ia = TODO_TYPES.indexOf(a)
    const ib = TODO_TYPES.indexOf(b)
    return (ia === -1 ? TODO_TYPES.length : ia) - (ib === -1 ? TODO_TYPES.length : ib)
  })
  return types.map((type) => {
    const group = list.filter((item) => item?.type === type)
    return {
      type,
      count: group.length,
      total: group.reduce((sum, item) => sum + Number(item?.count ?? 0), 0),
      items: group,
    }
  })
}

/**
 * 单人画像（derived，非权威）：由 `signals` 启发式推导 A/B/C/D/F。
 *
 * 关键判别位（`has_sales_shop` / `has_factory`）缺失或非布尔 → `GENERIC`（**不猜**）；
 * `signals` 为 null/非对象 → `GENERIC`。画像只用于首页内容侧重，**不得作为准入依据**。
 */
export function resolvePersona(signals) {
  if (!signals || typeof signals !== 'object') return 'GENERIC'
  if (typeof signals.has_sales_shop !== 'boolean' || typeof signals.has_factory !== 'boolean') {
    return 'GENERIC'
  }
  const hasShop = signals.has_sales_shop === true
    || (typeof signals.sales_shop_count === 'number' && signals.sales_shop_count > 0)
  const hasFactory = signals.has_factory === true
    || (typeof signals.factory_match_count === 'number' && signals.factory_match_count > 0)
  const hasOrders = typeof signals.order_count_30d === 'number' && signals.order_count_30d > 0
  const manyMembers = typeof signals.member_count === 'number' && signals.member_count > 1
  if (!hasShop && !hasFactory) return manyMembers ? 'F' : 'A'
  if (hasFactory && !hasShop) return 'C'
  if (hasFactory && hasShop && !hasOrders) return 'B'
  return 'D'
}

/** 空段判定：数组 / 含 items|total|count 的对象 / 普通对象。 */
export function isEmptySection(section) {
  if (section === null || section === undefined) return true
  if (Array.isArray(section)) return section.length === 0
  if (typeof section === 'object') {
    if (Array.isArray(section.items)) return section.items.length === 0
    if (typeof section.total === 'number') return section.total === 0
    if (typeof section.count === 'number') return section.count === 0
    return Object.keys(section).length === 0
  }
  return false
}

/**
 * 段状态：`error`（无数据 + 对应源失败）/ `empty` / `partial`（有数据 + 整体部分可用）/ `ready`。
 */
export function sectionState(section, partial = false, sources = {}) {
  if (isEmptySection(section)) {
    return Object.values(sources || {}).includes('failed') ? 'error' : 'empty'
  }
  return partial ? 'partial' : 'ready'
}

/** 失败的数据源名列表（供 PartialDataBanner 明示哪些源不可用）。 */
export function missingSources(sources = {}) {
  return Object.entries(sources || {})
    .filter(([, state]) => state === 'failed')
    .map(([name]) => name)
}

/** `signals` 中不可得（null）的键列表，供横幅补充说明。 */
export function missingSignals(signals = {}) {
  return Object.entries(signals || {})
    .filter(([, value]) => value === null || value === undefined)
    .map(([name]) => name)
}
