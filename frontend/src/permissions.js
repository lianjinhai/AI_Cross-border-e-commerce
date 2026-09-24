import {
  contextRole,
  contextSource,
  hasPermission,
} from './workspace'

/**
 * Phase 1.8 身份模型说明（重要，改代码前先读）。
 *
 * 身份有两个来源，优先级严格如下：
 *   1. **Workspace Context**（目标态）：来自 `GET /api/me/workspace-context`，
 *      `role` 是大写新枚举（OWNER/OPERATOR/READ_ONLY/COMPLIANCE/
 *      PLATFORM_ADMIN/FACTORY_COLLABORATOR），`source` 标明来源。
 *   2. **legacy localStorage `erp_user`**（兜底）：仅在 Context 不可用时使用。
 *
 * 为什么必须保留 legacy 兜底（不能全删）：
 *   - **工厂账号拿不到 Context**：`app/auth.py` 的路径门禁只放行
 *     `/api/factory-network/portal/*` 与 `/api/auth/me`，`/api/me/*` 一律 403
 *     （既有契约，`test_workspace_context_api.py` 已固化）。工厂账号的 Context
 *     永远为空，删掉兜底会让工厂门户直接不可用。
 *   - **Context 请求失败**（网络抖动/后端 5xx）时用户至少还能用。
 *   兜底的存在由 `tests/permissions.test.js` 的 legacy 用例固化。
 *
 * 下面三个常量是**唯一允许读 legacy 角色的地方**，新增代码禁止再读
 * `localStorage.erp_user.role`。
 */
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
 * 能力判断：Context 权限目录优先，Context 不可用时回退 legacy 角色。
 *
 * 为什么保留回退而不是直接 fail-closed：工厂账号拿不到 Context（见文件头
 * 说明），直接 fail-closed 会让工厂门户的所有按钮消失。回退分支与
 * `LEGACY_ROLE_MAP` 一起，构成 Phase 1.8 之后**唯一**允许的 legacy 依赖点；
 * 待工厂门户单独规划 Context 入口后，这几处可一并删除。
 */
export const canWrite = () => hasPermission('order:write') ?? ['admin', 'operator', 'superadmin'].includes(role())
export const canAdmin = () => hasPermission('workspace:member:admin') ?? ['admin', 'superadmin'].includes(role())
export const canApprove = () => hasPermission('compliance:approve') ?? ['admin', 'compliance_approver', 'superadmin'].includes(role())

/**
 * 按权限 key 判断能力（页面按钮级权限的统一入口）。
 *
 * 权威事实源是**后端** `workspace_context.ROLE_PERMISSIONS`：它经
 * `GET /api/me/workspace-context` 下发 `permissions[]`，此处只做查询 +
 * legacy 兜底映射——**前端不重新定义角色-权限矩阵**（那会造成双事实源漂移，
 * 见 docs/角色权限体系梳理方案.md §7-修正 8）。
 *
 * key 命名见 docs/页面操作权限对照表.md（如 product:write / listing:write /
 * settlement:write / compliance:check / supply:write）。
 *
 * Context 不可用时（工厂账号、请求失败）按 `LEGACY_ROLE_MAP` 推导的角色
 * 回退到 `LEGACY_CAPABILITIES`，保证工厂门户等场景按钮不消失。
 */
const LEGACY_CAPABILITIES = {
  OWNER: ['product:write', 'supply:write', 'listing:write', 'order:write', 'finance:write',
    'purchase:write', 'settlement:write', 'refund:write', 'ai:write', 'workspace:write',
    'workspace:member:admin', 'compliance:approve', 'compliance:check'],
  OPERATOR: ['product:write', 'supply:write', 'listing:write', 'order:write', 'finance:write',
    'purchase:write', 'settlement:write', 'refund:write', 'ai:write', 'workspace:write',
    'compliance:check'],
  COMPLIANCE: ['compliance:approve', 'compliance:check'],
  FACTORY_COLLABORATOR: ['supply:write'],
}

export function can(capability) {
  const fromContext = hasPermission(capability)
  if (fromContext !== null) return fromContext
  return (LEGACY_CAPABILITIES[roleKey()] || []).includes(capability)
}

/** 任一能力满足即通过（用于「多个写操作任一有权」的场景）。 */
export function canAny(...capabilities) {
  return capabilities.some((c) => can(c))
}

/** 新角色枚举（大写）：有 Context 用 Context，否则由 legacy role 映射。 */
export const roleKey = () => contextRole() || LEGACY_ROLE_MAP[role().toLowerCase()] || (role() ? 'READ_ONLY' : '')

/**
 * 工厂伙伴判断：走 `roleKey()`（Context 优先 + legacy 兜底）。
 * 不再直接读 `localStorage.erp_user.role`——那是文件头禁止的用法。
 */
export const isSupplier = () => roleKey() === 'FACTORY_COLLABORATOR'

/** 平台管理员本尊判断（代客态不算本尊）。 */
export const isSuperadmin = () => roleKey() === 'PLATFORM_ADMIN'
  && !localStorage.getItem('erp_impersonating')

/** Context 来源（MEMBERSHIP / LEGACY_FALLBACK / PLATFORM / FACTORY），无 Context 为 null。 */
export const workspaceSource = () => contextSource()

const APPROVER_PATHS = new Set(['/compliance-workbench', '/dashboard', '/bi', '/listings', '/compliance'])
const ADMIN_PATHS = new Set(['/users', '/settings'])

/**
 * Phase 1.8：由 Context（优先）或 legacy（兜底）构造路由分流用的身份。
 *
 * 返回的对象与旧版 `user` 参数**结构兼容**（都有 `role`），但 `role` 的取值域
 * 从「小写 legacy 角色」升级为「新枚举优先 + legacy 兜底」，因此
 * `routeRedirect` 内部用 `normalizeIdentity()` 归一化后再判断。
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
 *
 * 为什么不能写成「`user.role` 非空就用 user」：路由守卫同时传 `user`（兜底用）
 * 与 `context`（权威源）时，那种写法会让 legacy 压过 Context——平台管理员在
 * Context 里是租户 OPERATOR，却会被按 `superadmin` 放行到 `/platform-admin`。
 */
function resolveIdentity({ user, impersonating = false, context = null }) {
  if (context) return normalizeIdentity(identityFrom({ user, impersonating, context }))
  if (user && user.fromContext) return normalizeIdentity({ ...user, impersonating })
  return normalizeIdentity(identityFrom({ user, impersonating }))
}

/**
 * Central route policy. Returning null means the requested path is allowed;
 * otherwise the returned path is the safe workspace landing page.
 *
 * Phase 1.8：入参 `user` 兼容两种形态——旧的 `{role:'admin'}`（legacy 小写）
 * 与新的 `identityFrom()` 产物（新枚举大写）。两者都由 `normalizeIdentity()`
 * 归一到大写枚举后判断，因此调用方无需关心自己拿的是哪种。
 *
 * 传参优先级：`context` > `user.fromContext` > `user`（legacy）。守卫会同时传
 * `user`（兜底）与 `context`（权威），必须保证 Context 胜出。
 */
export function routeRedirect({ path, authenticated, user, impersonating = false, context = null }) {
  if (path === '/login') return authenticated ? defaultLanding(user, impersonating, context) : null
  if (!authenticated) return '/login'

  const identity = resolveIdentity({ user, impersonating, context })
  const userRole = identity.role
  const impersonatingNow = identity.impersonating

  if (userRole === 'PLATFORM_ADMIN' && !impersonatingNow) {
    return path === '/platform-admin' ? null : '/platform-admin'
  }
  if (path === '/platform-admin') return '/dashboard'
  if (userRole === 'FACTORY_COLLABORATOR') return path === '/factory-portal' ? null : '/factory-portal'
  if (path === '/factory-portal') return '/dashboard'
  if (userRole === 'COMPLIANCE' && !APPROVER_PATHS.has(path)) return '/compliance-workbench'
  if (ADMIN_PATHS.has(path) && userRole !== 'OWNER') return '/dashboard'
  return null
}

export function defaultLanding(user, impersonating = false, context = null) {
  const identity = resolveIdentity({ user, impersonating, context })
  if (identity.role === 'PLATFORM_ADMIN' && !identity.impersonating) return '/platform-admin'
  if (identity.role === 'FACTORY_COLLABORATOR') return '/factory-portal'
  if (identity.role === 'COMPLIANCE') return '/compliance-workbench'
  return '/dashboard'
}
