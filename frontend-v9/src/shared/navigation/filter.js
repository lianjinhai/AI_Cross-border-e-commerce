/**
 * 角色过滤（契约 §2.3 → 蓝图 R1 P0 扩展）：菜单树与路由白名单的**唯一事实源**。
 *
 * 平移 frontend/src/composables/navigation.js 的纯函数组织与语义，路径映射为
 * `/app|/console|/factory` 前缀（FRONTEND_V9_NAVIGATION.md §5）：
 * - PLATFORM_ADMIN(非代客) → console 树；FACTORY_COLLABORATOR → factory 树；
 * - COMPLIANCE → 白名单过滤（/app、/app/analytics/bi、/app/listings*、
 *   /app/compliance*、/app/launch*）；
 * - 非 OWNER 隐藏 /app/settings/*、/app/compliance/approvals；
 * - OWNER 全量（/app/settings/team 需 canManageMembers）。
 *
 * `whitelistForRole` 与 `buildDomains` 同源产出：菜单过滤用 Set 精确匹配叶子，
 * 路由守卫用 `isPathAllowedForRole`（同一份规则 + 前缀语义），禁止另建第二事实源。
 *
 * 蓝图 R1 新增：buildDomains 增 persona 参数（新手域抑制，视觉层不改路由守卫白名单）。
 */
import { WORKSPACE_DOMAINS } from './workspace-navigation'
import { CONSOLE_DOMAINS } from './console-navigation'
import { FACTORY_DOMAINS } from './factory-navigation'

export { WORKSPACE_DOMAINS, CONSOLE_DOMAINS, FACTORY_DOMAINS }

/** COMPLIANCE 侧栏叶子精确白名单（与 buildDomains 同源；path 集语义不变）。 */
export const COMPLIANCE_ALLOWED_PATHS = new Set([
  '/app',
  '/app/analytics/bi',
  '/app/listings',
  '/app/compliance',
  '/app/compliance/approvals',
  '/app/launch',
])

/** COMPLIANCE 前缀白名单：详情路由（/:id）随父级放行，前缀必须带尾斜杠防形近路径（R12 语义平移）。 */
const COMPLIANCE_PREFIX_PATHS = ['/app/listings/', '/app/compliance/', '/app/launch/']

/** 非 OWNER 隐藏路径（NON_OWNER_HIDDEN_PATHS 语义映射到新前缀）。 */
export const NON_OWNER_HIDDEN_PATHS = new Set([
  '/app/settings/ai',
  '/app/settings/team',
  '/app/compliance/approvals',
])

/** 仅 OWNER 可见/可进（requiresOwner 路由守卫与菜单过滤共用）。 */
export const OWNER_ONLY_PATHS = new Set(['/app/settings/team'])

/** requiresOwner 路由前缀（守卫用；/app/settings/* 整组仅 OWNER）。 */
export const OWNER_ONLY_PREFIX = '/app/settings/'

/** 展平所有域的叶子路径。 */
function allChildPaths(domains) {
  return domains.flatMap((domain) => domain.children.map((child) => child.path))
}

/**
 * 按路径白名单过滤域：仅保留 `allowedPaths` 内的子项；空域丢弃。
 * 纯函数——不修改入参，返回新的域/子项对象。
 *
 * @param {Array} domains 域数组。
 * @param {Set<string>|string[]} allowedPaths 允许保留的 path 集合。
 * @returns {Array} 过滤后的新数组。
 */
export function filterDomainsByPaths(domains, allowedPaths) {
  const allowed = allowedPaths instanceof Set ? allowedPaths : new Set(allowedPaths)
  return domains
    .map((domain) => ({
      ...domain,
      children: domain.children.filter((child) => allowed.has(child.path)),
    }))
    .filter((domain) => domain.children.length > 0)
}

/**
 * 角色可见叶子路径集合（菜单过滤与守卫的共同上游）。
 *
 * @param {object} p
 * @param {string} [p.roleKey=''] 新角色枚举（大写，Context 优先）。
 * @param {boolean} [p.canManageMembers=false] 是否可见「用户与角色」（canAdmin）。
 * @param {boolean} [p.isImpersonating=false] 代客中：平台管理员临时按普通租户处理。
 * @returns {Set<string>} 该角色侧栏可见的叶子 path 集合。
 */
export function whitelistForRole({ roleKey = '', canManageMembers = false, isImpersonating = false } = {}) {
  if (roleKey === 'PLATFORM_ADMIN' && !isImpersonating) {
    return new Set(allChildPaths(CONSOLE_DOMAINS))
  }
  if (roleKey === 'FACTORY_COLLABORATOR') {
    return new Set(allChildPaths(FACTORY_DOMAINS))
  }
  if (roleKey === 'COMPLIANCE') {
    return new Set(COMPLIANCE_ALLOWED_PATHS)
  }
  if (roleKey !== 'OWNER') {
    // 非 OWNER（含代客中的平台管理员/未知角色）：隐藏管理入口与合规工作台。
    return new Set(allChildPaths(WORKSPACE_DOMAINS).filter((p) => !NON_OWNER_HIDDEN_PATHS.has(p)))
  }
  // OWNER：全量；「用户与角色」仅在具备成员管理权限时保留。
  if (!canManageMembers) {
    return new Set(allChildPaths(WORKSPACE_DOMAINS).filter((p) => !OWNER_ONLY_PATHS.has(p)))
  }
  return new Set(allChildPaths(WORKSPACE_DOMAINS))
}

/**
 * 路由守卫用白名单判定（COMPLIANCE 前缀语义在此统一实现，权限模块直接复用）。
 * 非 COMPLIANCE 角色的空间约束（仅 /console/*、仅 /factory/*）由
 * permissions.routeRedirect 的空间规则处理，本函数对其返回 true（不做二次收紧，
 * 避免 requiresOwner/空间规则与白名单双重拦截产生竞态）。
 *
 * @param {string} roleKey 角色枚举。
 * @param {string} path 目标路径（不含 query）。
 * @returns {boolean} 是否放行。
 */
export function isPathAllowedForRole(roleKey, path) {
  if (roleKey !== 'COMPLIANCE') return true
  if (COMPLIANCE_ALLOWED_PATHS.has(path)) return true
  return typeof path === 'string' && COMPLIANCE_PREFIX_PATHS.some((prefix) => path.startsWith(prefix))
}

/** requiresOwner 判定（守卫与菜单同源）：/app/settings/* 整组仅 OWNER。 */
export function isOwnerOnlyPath(path) {
  return typeof path === 'string' && path.startsWith(OWNER_ONLY_PREFIX)
}

/**
 * 按角色构造可见域数组（契约 §2.3 签名 → 蓝图 R1 增 persona 参数）。
 *
 * 新手域抑制（蓝图 §2.1）：GUIDED 模式仅展开与画像相关的域，PROFESSIONAL 全量展开。
 * 抑制仅是**视觉层**，whitelistForRole / 路由守卫白名单不变，服务端仍双重限制权限。
 *
 * @param {object} p
 * @param {string} [p.roleKey=''] 新角色枚举（大写，Context 优先）。
 * @param {boolean} [p.canManageMembers=false] 是否可见「用户与角色」。
 * @param {boolean} [p.isImpersonating=false] 代客中：平台管理员临时进入租户 Workspace 视图。
 * @param {string} [p.persona=''] 新手画像（A/B/C；PROFESSIONAL/未知 → 全量 8 域）。
 * @returns {Array} 该角色应见的域数组。
 */
export function buildDomains({ roleKey = '', canManageMembers = false, isImpersonating = false, persona = '' } = {}) {
  if (roleKey === 'PLATFORM_ADMIN' && !isImpersonating) return CONSOLE_DOMAINS
  if (roleKey === 'FACTORY_COLLABORATOR') return FACTORY_DOMAINS
  // 1) 角色白名单过滤（既有逻辑不变，服务端双重限制仍然生效）
  const allowed = whitelistForRole({ roleKey, canManageMembers, isImpersonating })
  let domains = filterDomainsByPaths(WORKSPACE_DOMAINS, allowed)
  // 2) 新手域抑制（仅 WORKSPACE 视觉层；PLATFORM_ADMIN/FACTORY 树不适用）
  if (persona) domains = suppressDomainsByPersona(domains, persona)
  return domains
}

/**
 * persona → 保留域 key 映射；未知 persona / PROFESSIONAL → 返回全量 domains。
 * 画像 A(个人新手) → workbench / discovery / channel
 * 画像 B(有货源)   → A + supply / orders
 * 画像 C(有团队)   → A + orders / ai
 * PROFESSIONAL / 未知 persona → 全量 8 域
 */
export const PERSONA_DOMAINS = {
  A: ['workbench', 'discovery', 'channel'],
  B: ['workbench', 'discovery', 'supply', 'channel', 'orders'],
  C: ['workbench', 'discovery', 'channel', 'orders', 'ai'],
}

/**
 * 按 persona 抑制域（纯函数，视觉层不改路由守卫白名单）。
 * @param {Array} domains 角色过滤后的域数组。
 * @param {string} persona 画像码。
 * @returns {Array} 抑制后的域数组。
 */
export function suppressDomainsByPersona(domains, persona) {
  const keep = PERSONA_DOMAINS[persona]
  if (!keep) return domains // PROFESSIONAL / 未知 → 全量
  return domains.filter((d) => keep.includes(d.key))
}
