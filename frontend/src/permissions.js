import {
  contextRole,
  hasPermission,
} from './workspace'

/**
 * Phase 1.8 身份模型说明（重要，改代码前先读）。
 *
 * 身份有两个来源，优先级严格如下：
 *   1. **Workspace Context**（目标态）：来自 `GET /api/me/workspace-context`，
 *      `role` 是大写新枚举（OWNER/OPERATOR/READ_ONLY/COMPLIANCE/
 *      PLATFORM_ADMIN/FACTORY_COLLABORATOR），`source` 标明来源。
 *      **这是权限判定的唯一权威源。**
 *   2. **legacy localStorage `erp_user`**（兜底）：仅在 Context 不可用时使用，
 *      **只用于路由分流与展示**（`roleKey`/`identityFrom`/`routeRedirect`/
 *      `defaultLanding`），**不再授予任何权限**。
 *
 * 为什么必须保留 legacy 兜底（不能全删）：
 *   - **Context 请求失败**（网络抖动/后端 5xx）时用户至少还能被送到自己的首页，
 *     而不是被弹到无权访问的 `/dashboard`。平台管理员（→ `/platform-admin`）
 *     与工厂账号（→ `/factory-portal`）尤其依赖这一点。
 *   - **工厂账号**：G-3 之后 `app/auth.py` 已放行 `/api/me/workspaces` 与
 *     `/api/me/workspace-context`（只读），工厂账号**能**取到 Context
 *     （`source=FACTORY`、`role=FACTORY_COLLABORATOR`）。但 `/switch` 仍被拒
 *     ——工厂的活动 Workspace 由 `SupplierPortalMember` 唯一确定，无可切换项。
 *
 * 为什么写权限必须 fail-closed（不回退 legacy 角色名单）：
 *   `erp_user` 存在 localStorage，改一行就能伪造 `role`（实测 viewer→admin 即可
 *   让写按钮出现）。用它授予写权限，等于把「界面是否显示写操作」交给可篡改输入。
 *   后端仍独立鉴权（`require_write` 只放行 admin/operator；实测 viewer 写商品
 *   403、进平台总览 403），所以前端只做「不制造假授权界面」：Context 拿不到时
 *   按**只读降级**。路由兜底保留、权限兜底删除，是权衡后的分工（见
 *   docs/DECISIONS.md D24）。
 *
 * 下面两个导出是**唯一允许读 legacy 角色的地方**，新增代码禁止再读
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
 * 能力判断：Context 权限目录是唯一权威源；Context 不可用时**一律 false**。
 *
 * 为什么 fail-closed（A′，见 docs/DECISIONS.md D24）：Context 请求可能失败
 * （网络抖动、后端 5xx、F5 刷新瞬间），此时**不授予任何写权限**，退化为只读
 * 界面。旧实现回退 legacy 角色名单，等于让可篡改的 `localStorage.erp_user`
 * 决定写按钮是否出现（实测 viewer→admin 即可让写按钮显示）——前端不该制造
 * 这种假授权。代价是 Context 故障期写按钮消失，属预期的只读降级。
 */
export const canWrite = () => hasPermission('order:write') ?? false
export const canAdmin = () => hasPermission('workspace:member:admin') ?? false
export const canApprove = () => hasPermission('compliance:approve') ?? false

/**
 * 按权限 key 判断能力（页面按钮级权限的统一入口）。
 *
 * 权威事实源是**后端** `workspace_context.ROLE_PERMISSIONS`：它经
 * `GET /api/me/workspace-context` 下发 `permissions[]`，此处**只做查询**，
 * 不重新定义角色-权限矩阵（那会造成双事实源漂移，
 * 见 docs/角色权限体系梳理方案.md §7-修正 8）。
 *
 * key 命名见 docs/页面操作权限对照表.md（如 product:write / listing:write /
 * settlement:write / compliance:check / supply:write）。
 *
 * Context 不可用时（请求失败、未登录）**一律返回 false**（fail-closed，D24）：
 * 前端不再用 legacy 角色推导权限，避免「改 localStorage 就出现写按钮」。
 * 真实写操作后端仍会独立鉴权，故这里只影响按钮可见性。
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
 *
 * 用途**仅限路由分流与展示**（Layout 菜单、角色标签、`routeRedirect`）。
 * 禁止用它推导权限——权限一律走 `can()` / `hasPermission()`（D24）。
 */
export const roleKey = () => contextRole() || LEGACY_ROLE_MAP[role().toLowerCase()] || (role() ? 'READ_ONLY' : '')

/**
 * 工厂伙伴判断：走 `roleKey()`（Context 优先 + legacy 兜底）。
 * 不再直接读 `localStorage.erp_user.role`——那是文件头禁止的用法。
 */
export const isSupplier = () => roleKey() === 'FACTORY_COLLABORATOR'

const APPROVER_PATHS = new Set(['/compliance-workbench', '/dashboard', '/bi', '/listings', '/compliance'])
// 前缀白名单：合规员可进 /launch 与后续的 /launch/:id（上线中心只读可见）；
// 其余路径仍**精确匹配**，不得放宽既有语义（R12）。
const APPROVER_PREFIX_PATHS = ['/launch']
const isApproverPath = (path) => APPROVER_PATHS.has(path)
  || (typeof path === 'string'
    && APPROVER_PREFIX_PATHS.some((prefix) => path === prefix || path.startsWith(`${prefix}/`)))
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
  if (userRole === 'COMPLIANCE' && !isApproverPath(path)) return '/compliance-workbench'
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
