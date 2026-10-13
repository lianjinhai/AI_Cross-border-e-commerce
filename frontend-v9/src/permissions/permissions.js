import { contextRole, hasPermission } from '../shared/workspace'
import { isOwnerOnlyPath, isPathAllowedForRole } from '../shared/navigation/filter'

/**
 * 身份模型说明（改代码前先读；语义平移自 frontend/src/permissions.js，路径按
 * docs/FRONTEND_V9_CONTRACTS.md §3.2/§3.3 映射到 /app|/console|/factory 前缀）。
 *
 * 身份有两个来源，优先级严格如下：
 *   1. **Workspace Context**（目标态）：来自 `GET /api/me/workspace-context`，
 *      `role` 是大写新枚举（OWNER/OPERATOR/READ_ONLY/COMPLIANCE/
 *      PLATFORM_ADMIN/FACTORY_COLLABORATOR），`source` 标明来源。
 *      **这是权限判定的唯一权威源。**
 *   2. **legacy localStorage `erp_user`**（兜底）：仅在 Context 不可用时使用，
 *      **只用于路由分流与展示**（`roleKey`/`identityFrom`/`routeRedirect`/
 *      `defaultLanding`），**不再授予任何权限**（fail-closed，D24）。
 *
 * 为什么必须保留 legacy 兜底（不能全删）：Context 请求失败（网络抖动/后端 5xx）
 * 时用户至少还能被送到自己的首页。写权限必须 fail-closed：`erp_user` 在
 * localStorage 可被篡改，用它授予写权限等于制造假授权界面；后端仍独立鉴权。
 */

/** 全空间共用登录页（契约 §3.2：/login → /console/login）。 */
export const LOGIN_PATH = '/console/login'

/** 错误页：对所有已登录角色放行，避免守卫与错误页互相重定向死循环（契约 §3.3.3）。 */
export const ERROR_PATHS = new Set(['/404', '/403', '/500'])

/**
 * 角色枚举常量（与后端 workspace_context 角色域一一对应，值即各模块在用的
 * 字面量）：角色字符串一律从这里引用，禁止散落魔法字符串。
 */
export const ROLES = {
  OWNER: 'OWNER',
  OPERATOR: 'OPERATOR',
  READ_ONLY: 'READ_ONLY',
  COMPLIANCE: 'COMPLIANCE',
  PLATFORM_ADMIN: 'PLATFORM_ADMIN',
  FACTORY_COLLABORATOR: 'FACTORY_COLLABORATOR',
}

export const currentUser = () => {
  try { return JSON.parse(localStorage.getItem('erp_user') || 'null') }
  catch { return null }
}
export const role = () => currentUser()?.role || ''

const LEGACY_ROLE_MAP = {
  admin: 'OWNER',
  owner: 'OWNER',
  operator: 'OPERATOR',
  viewer: 'READ_ONLY',
  compliance_approver: 'COMPLIANCE',
  superadmin: 'PLATFORM_ADMIN',
  supplier: 'FACTORY_COLLABORATOR',
}

/**
 * 能力判断：Context 权限目录是唯一权威源；Context 不可用时**一律 false**。
 * fail-closed（D24）：前端不制造假授权界面，真实写操作后端仍独立鉴权。
 */
export const canWrite = () => hasPermission('order:write') ?? false
export const canAdmin = () => hasPermission('workspace:member:admin') ?? false
export const canApprove = () => hasPermission('compliance:approve') ?? false

/**
 * 按权限 key 判断能力（页面按钮级权限的统一入口）。
 * 权威事实源是后端 `workspace_context.ROLE_PERMISSIONS`（经 Context 下发
 * permissions[]），此处只做查询、不重新定义角色-权限矩阵（禁止双事实源）。
 */
export function can(capability) {
  const fromContext = hasPermission(capability)
  if (fromContext !== null) return fromContext
  return false
}

/** 任一能力满足即通过（用于「多个写操作任一有权」的场景）。 */
export function canAny(...capabilities) {
  return capabilities.some((c) => can(c))
}

/**
 * 新角色枚举（大写）：有 Context 用 Context，否则由 legacy role 映射。
 * 用途**仅限路由分流与展示**；禁止用它推导权限——权限一律走 `can()`（D24）。
 */
export const roleKey = () => contextRole() || LEGACY_ROLE_MAP[role().toLowerCase()] || (role() ? 'READ_ONLY' : '')

/** 工厂伙伴判断：走 roleKey()（Context 优先 + legacy 兜底）。 */
export const isSupplier = () => roleKey() === 'FACTORY_COLLABORATOR'

/**
 * 由 Context（优先）或 legacy（兜底）构造路由分流用的身份。
 * 返回结构与旧版兼容（都有 `role`），`role` 取值域为新枚举优先 + legacy 兜底。
 */
export function identityFrom({ user, impersonating = false, context = null } = {}) {
  if (context) {
    return {
      role: context.role || '',
      source: context.source || '',
      impersonating: Boolean(context.is_impersonating) || Boolean(impersonating),
      fromContext: true,
    }
  }
  return {
    role: LEGACY_ROLE_MAP[String(user?.role || '').toLowerCase()] || user?.role || '',
    source: 'LEGACY_FALLBACK',
    impersonating: Boolean(impersonating),
    fromContext: false,
  }
}

/** 把身份归一化成大写角色枚举（新枚举原样返回，legacy 走映射）。 */
function normalizeIdentity(identity) {
  if (!identity) return { role: '', impersonating: false }
  const raw = String(identity.role || '')
  const mapped = LEGACY_ROLE_MAP[raw.toLowerCase()] || raw.toUpperCase()
  return { role: mapped, impersonating: Boolean(identity.impersonating) }
}

/**
 * 统一身份解析入口：**Context 无条件优先**，legacy 仅在 Context 缺失时兜底。
 * 不能写成「user.role 非空就用 user」：那会让 legacy 压过 Context（历史缺陷）。
 */
function resolveIdentity({ user, impersonating = false, context = null }) {
  if (context) return normalizeIdentity(identityFrom({ user, impersonating, context }))
  if (user && user.fromContext) return normalizeIdentity({ ...user, impersonating })
  return normalizeIdentity(identityFrom({ user, impersonating }))
}

/** 是否命中空间前缀（/console、/console/login 等整组）。 */
const inConsole = (path) => path === '/console' || path.startsWith('/console/')
const inFactory = (path) => path === '/factory' || path.startsWith('/factory/')

/**
 * 统一路由分流策略（契约 §3.3.2，判定顺序平移、路径查 §3.2 表）。
 * 返回 null 表示放行；否则返回应重定向到的路径。
 *
 * 判定顺序（与旧版语义一一对应）：
 *   未登录 → /console/login；PLATFORM_ADMIN(非代客) → 仅 /console/*；
 *   非 PLATFORM_ADMIN 进入 /console/* → 逐出（/app）；
 *   FACTORY_COLLABORATOR → 仅 /factory/*；其余角色进入 /factory/* → /app；
 *   COMPLIANCE → 白名单外重定向落地页；requiresOwner(/app/settings/*) 且非 OWNER → /app；
 *   代客中放行该租户 Workspace 视图。
 * 错误页（/404 /403 /500）对所有已登录角色放行。
 */
export function routeRedirect({ path, authenticated, user, impersonating = false, context = null }) {
  if (path === LOGIN_PATH) return authenticated ? defaultLanding(user, impersonating, context) : null
  if (!authenticated) return LOGIN_PATH

  const identity = resolveIdentity({ user, impersonating, context })
  const userRole = identity.role
  const impersonatingNow = identity.impersonating

  if (ERROR_PATHS.has(path)) return null

  if (userRole === 'PLATFORM_ADMIN' && !impersonatingNow) {
    return inConsole(path) ? null : '/console/overview'
  }
  if (inConsole(path)) return '/app'
  if (userRole === 'FACTORY_COLLABORATOR') {
    return inFactory(path) ? null : '/factory/products'
  }
  if (inFactory(path)) return '/app'
  if (userRole === 'COMPLIANCE' && !isPathAllowedForRole('COMPLIANCE', path)) {
    return '/app/compliance/approvals'
  }
  if (isOwnerOnlyPath(path) && userRole !== 'OWNER') return '/app'
  return null
}

/** 登录成功分流（契约 §3.3.4）：超管→/console/overview、工厂→/factory/products、合规→/app/compliance/approvals、其余→/app。 */
export function defaultLanding(user, impersonating = false, context = null) {
  const identity = resolveIdentity({ user, impersonating, context })
  if (identity.role === 'PLATFORM_ADMIN' && !identity.impersonating) return '/console/overview'
  if (identity.role === 'FACTORY_COLLABORATOR') return '/factory/products'
  if (identity.role === 'COMPLIANCE') return '/app/compliance/approvals'
  return '/app'
}
