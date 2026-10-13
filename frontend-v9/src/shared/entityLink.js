/**
 * 实体深链构造纯函数（蓝图 §6.3，包 1 P0 共享组件 EntityLink 纯函数下沉）。
 *
 * 生成站内白名单深链：workspace_context + object_type + object_id + store_id?
 * + workflow_run_id? + step_code? + return_to + return_filters。
 * return_to 限站内白名单；无权限对象点击→/403（不渲染敏感数据）。
 */

/** 站内路径白名单前缀（return_to 限这些前缀）。 */
const WHITELIST_PREFIXES = [
  '/app', '/console', '/factory', '/403', '/404',
]

/**
 * 校验路径是否在站内白名单内（return_to / 深链 target 安全校验）。
 *
 * @param {string} path 目标路径。
 * @returns {boolean}
 */
export function isWhitelistedPath(path) {
  if (typeof path !== 'string' || !path.startsWith('/')) return false
  return WHITELIST_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix + '/'))
}

/**
 * 构建实体深链 path。
 *
 * 蓝图 §6.3 约定：/app/{objectType}/{objectId}?store_id=&workflow_run_id=&step_code=&return_to=&return_filters=
 * 参数详情路由（/:id）已路由化，此处仅构造 query 深链。
 *
 * @param {object} p
 * @param {string} p.objectType 对象类型（'product'|'listing'|'order'|'launch'...）。
 * @param {string|number} p.objectId 对象 ID。
 * @param {string} [p.storeId] 店铺 ID。
 * @param {string} [p.workflowRunId] 工作流运行 ID。
 * @param {string} [p.stepCode] 步骤码。
 * @param {string} [p.returnTo] 返回路径（限站内白名单）。
 * @param {string} [p.returnFilters] 返回时恢复筛选（JSON 字符串）。
 * @returns {string} 完整 path（含 query string）。
 */
export function buildEntityLink({
  objectType = '', objectId = '', storeId = '',
  workflowRunId = '', stepCode = '', returnTo = '', returnFilters = '',
} = {}) {
  if (!objectType || !objectId) return '/404'
  const base = `/app/${objectType}/${objectId}`
  const params = []
  if (storeId) params.push(`store_id=${encodeURIComponent(String(storeId))}`)
  if (workflowRunId) params.push(`workflow_run_id=${encodeURIComponent(String(workflowRunId))}`)
  if (stepCode) params.push(`step_code=${encodeURIComponent(String(stepCode))}`)
  if (returnTo && isWhitelistedPath(returnTo)) {
    params.push(`return_to=${encodeURIComponent(returnTo)}`)
  }
  if (returnFilters) params.push(`return_filters=${encodeURIComponent(returnFilters)}`)
  return params.length ? `${base}?${params.join('&')}` : base
}

/**
 * 构建列表页深链（带筛选参数）。
 *
 * @param {object} p
 * @param {string} p.basePath 列表页 path（如 /app/products）。
 * @param {object} [p.query] 额外 query 参数。
 * @returns {string}
 */
export function buildListLink(basePath = '/app', query = {}) {
  if (!isWhitelistedPath(basePath)) return '/404'
  const params = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
  return params.length ? `${basePath}?${params.join('&')}` : basePath
}
