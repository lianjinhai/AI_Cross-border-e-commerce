/**
 * 上线中心筛选保存视图（UX-C「创建上线向导化+筛选保存视图」）。
 *
 * 视图存 localStorage `v9_launch_views`（按租户无关；仅存筛选，不含分页）。
 * 纯函数接收 storage 注入，vitest 直测；UI 侧用默认 localStorage 调用。
 */

export const VIEWS_STORAGE_KEY = 'v9_launch_views'

/** 可保存的筛选键（与 launchCenter.listQuery 的服务端筛选字段一致，不含分页/含历史开关）。 */
const SAVABLE_KEYS = [
  'product_id', 'shop_id', 'platform', 'market', 'execution_status',
  'owner_user_id', 'mine', 'waiting_platform', 'blocked_only',
]

/** 只挑可保存键；空值剔除，保证视图语义干净。 */
export function sanitizeViewFilters(filters = {}) {
  const out = {}
  for (const key of SAVABLE_KEYS) {
    const value = filters[key]
    if (value === '' || value === null || value === undefined || value === false) continue
    out[key] = value
  }
  return out
}

/** 读取全部保存视图；存储损坏时返回空数组（fail-safe，不抛错）。 */
export function loadViews(storage = localStorage) {
  try {
    const raw = storage.getItem(VIEWS_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return []
    return parsed.filter((v) => v && typeof v.name === 'string' && typeof v.filters === 'object')
  } catch {
    return []
  }
}

/** 保存视图：同名覆盖（视图名即唯一键），最多保留 10 个。返回更新后的列表。 */
export function saveView(name, filters = {}, storage = localStorage) {
  const cleanName = String(name || '').trim()
  if (!cleanName) throw new Error('视图名不能为空')
  const views = loadViews(storage).filter((v) => v.name !== cleanName)
  views.unshift({ name: cleanName, filters: sanitizeViewFilters(filters) })
  const trimmed = views.slice(0, 10)
  storage.setItem(VIEWS_STORAGE_KEY, JSON.stringify(trimmed))
  return trimmed
}

/** 删除视图；返回更新后的列表（视图不存在时原样返回）。 */
export function deleteView(name, storage = localStorage) {
  const views = loadViews(storage).filter((v) => v.name !== name)
  storage.setItem(VIEWS_STORAGE_KEY, JSON.stringify(views))
  return views
}

/** 应用视图：返回该视图的筛选（干净副本）。 */
export function applyView(view = {}) {
  return { ...sanitizeViewFilters(view.filters || {}) }
}

/**
 * 应用视图到当前筛选（P2-1）：视图筛选合并到现有筛选上，
 * 返回**新对象**；视图未覆盖的键保留现值（含清空语义由视图侧显式存空串表达）。
 */
export function applyViewToFilters(current = {}, view = {}) {
  return { ...current, ...applyView(view) }
}
