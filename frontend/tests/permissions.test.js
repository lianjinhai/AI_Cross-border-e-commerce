import { beforeEach, describe, expect, it } from 'vitest'
import {
  canAdmin,
  canApprove,
  canWrite,
  currentUser,
  defaultLanding,
  identityFrom,
  routeRedirect,
} from '../src/permissions'

const access = (role, path, options = {}) => routeRedirect({
  path,
  authenticated: options.authenticated ?? true,
  user: role ? { role } : null,
  impersonating: options.impersonating ?? false,
})

describe('role capability policy', () => {
  beforeEach(() => localStorage.clear())

  it.each([
    ['admin', true, true, true],
    ['operator', true, false, false],
    ['viewer', false, false, false],
    ['compliance_approver', false, false, true],
    ['supplier', false, false, false],
    ['superadmin', true, true, true],
  ])('%s capabilities remain explicit', (role, write, admin, approve) => {
    localStorage.setItem('erp_user', JSON.stringify({ role }))
    expect(canWrite()).toBe(write)
    expect(canAdmin()).toBe(admin)
    expect(canApprove()).toBe(approve)
  })

  it('fails closed when persisted identity is corrupted', () => {
    localStorage.setItem('erp_user', '{bad json')
    expect(currentUser()).toBeNull()
    expect(canWrite()).toBe(false)
  })
})

describe('executable role journeys', () => {
  it('sends an anonymous visitor to login', () => {
    expect(access(null, '/orders', { authenticated: false })).toBe('/login')
    expect(access(null, '/login', { authenticated: false })).toBeNull()
  })

  it('keeps supplier accounts inside the factory workspace', () => {
    expect(defaultLanding({ role: 'supplier' })).toBe('/factory-portal')
    expect(access('supplier', '/factory-portal')).toBeNull()
    expect(access('supplier', '/orders')).toBe('/factory-portal')
    expect(access('supplier', '/platform-admin')).toBe('/dashboard')
  })

  it('keeps compliance approvers in read-and-review pages', () => {
    for (const path of ['/compliance-workbench', '/dashboard', '/bi', '/listings', '/compliance']) {
      expect(access('compliance_approver', path)).toBeNull()
    }
    for (const path of ['/orders', '/finance', '/settings', '/users']) {
      expect(access('compliance_approver', path)).toBe('/compliance-workbench')
    }
  })

  it('allows tenant admins to manage tenant settings but not the platform console', () => {
    expect(access('admin', '/users')).toBeNull()
    expect(access('admin', '/settings')).toBeNull()
    expect(access('admin', '/platform-admin')).toBe('/dashboard')
  })

  it.each(['operator', 'viewer'])('%s cannot enter tenant administration', (role) => {
    expect(access(role, '/users')).toBe('/dashboard')
    expect(access(role, '/settings')).toBe('/dashboard')
    expect(access(role, '/orders')).toBeNull()
  })

  it('isolates a platform superadmin until tenant impersonation begins', () => {
    expect(defaultLanding({ role: 'superadmin' })).toBe('/platform-admin')
    expect(access('superadmin', '/orders')).toBe('/platform-admin')
    expect(access('superadmin', '/platform-admin')).toBeNull()
    expect(access('superadmin', '/orders', { impersonating: true })).toBeNull()
    expect(access('superadmin', '/platform-admin', { impersonating: true })).toBe('/dashboard')
  })
})

/**
 * Phase 1.8：路由分流改吃 Workspace Context。
 *
 * 为什么必须单独测：此前 `routeRedirect` 只认 legacy 小写角色（`admin`/`supplier`），
 * 新枚举（`OWNER`/`FACTORY_COLLABORATOR`）传入会被当成未知角色——平台账号与
 * 工厂账号的路由会**静默错乱**（进错页或死循环重定向）。这组用例固化新枚举行为。
 */
describe('Phase 1.8 workspace context routing', () => {
  beforeEach(() => localStorage.clear())

  /** 用 Context 走一次路由决策（模拟守卫：context 优先）。 */
  const viaContext = (ctx, path, opts = {}) => routeRedirect({
    path,
    authenticated: opts.authenticated ?? true,
    context: ctx,
    impersonating: opts.impersonating ?? false,
  })

  const ctx = (role, source = 'MEMBERSHIP', extra = {}) => ({
    user_id: 1, workspace_id: 10, role, source, is_impersonating: false, ...extra,
  })

  it('routes OWNER (new enum) exactly like the legacy admin role', () => {
    expect(viaContext(ctx('OWNER'), '/users')).toBeNull()
    expect(viaContext(ctx('OWNER'), '/settings')).toBeNull()
    expect(viaContext(ctx('OWNER'), '/platform-admin')).toBe('/dashboard')
    expect(defaultLanding(null, false, ctx('OWNER'))).toBe('/dashboard')
  })

  it('keeps OPERATOR and READ_ONLY out of tenant administration', () => {
    for (const role of ['OPERATOR', 'READ_ONLY']) {
      expect(viaContext(ctx(role), '/users')).toBe('/dashboard')
      expect(viaContext(ctx(role), '/settings')).toBe('/dashboard')
      expect(viaContext(ctx(role), '/orders')).toBeNull()
    }
  })

  it('restricts COMPLIANCE to the four review pages', () => {
    for (const path of ['/compliance-workbench', '/dashboard', '/bi', '/listings', '/compliance']) {
      expect(viaContext(ctx('COMPLIANCE'), path)).toBeNull()
    }
    for (const path of ['/orders', '/finance', '/users']) {
      expect(viaContext(ctx('COMPLIANCE'), path)).toBe('/compliance-workbench')
    }
    expect(defaultLanding(null, false, ctx('COMPLIANCE'))).toBe('/compliance-workbench')
  })

  it('keeps FACTORY_COLLABORATOR inside the factory portal', () => {
    const factory = ctx('FACTORY_COLLABORATOR', 'FACTORY', { workspace_id: 3 })
    expect(viaContext(factory, '/factory-portal')).toBeNull()
    expect(viaContext(factory, '/orders')).toBe('/factory-portal')
    expect(viaContext(factory, '/platform-admin')).toBe('/dashboard')
    expect(defaultLanding(null, false, factory)).toBe('/factory-portal')
  })

  it('sends PLATFORM_ADMIN to the platform console, and to /dashboard once impersonating', () => {
    const platform = ctx('PLATFORM_ADMIN', 'PLATFORM', { workspace_id: null })
    expect(viaContext(platform, '/orders')).toBe('/platform-admin')
    expect(viaContext(platform, '/platform-admin')).toBeNull()
    expect(defaultLanding(null, false, platform)).toBe('/platform-admin')
    // 代客进入租户后：Context 的 is_impersonating 必须让平台账号当普通租户看
    const impersonated = ctx('OPERATOR', 'MEMBERSHIP', { is_impersonating: true })
    expect(viaContext(impersonated, '/orders')).toBeNull()
    expect(viaContext(impersonated, '/platform-admin')).toBe('/dashboard')
  })

  it('trusts context is_impersonating over a missing localStorage marker', () => {
    // 后端已透传 is_impersonating；前端不再只能靠 localStorage 判断
    const impersonated = ctx('OPERATOR', 'MEMBERSHIP', { is_impersonating: true })
    expect(identityFrom({ context: impersonated }).impersonating).toBe(true)
    expect(identityFrom({ context: ctx('OPERATOR') }).impersonating).toBe(false)
  })

  it('falls back to legacy identity when the context is unavailable', () => {
    // Context 不可用（网络抖动 / 后端 5xx / 未登录）时仍必须能正确分流。
    // 注：G-3 之后工厂账号已能取到 Context（source=FACTORY），此用例覆盖的是
    // 通用的「Context 缺失」兜底，不再特指工厂场景。
    const identity = identityFrom({ user: { role: 'supplier' } })
    expect(identity.fromContext).toBe(false)
    expect(identity.source).toBe('LEGACY_FALLBACK')
    expect(identity.role).toBe('FACTORY_COLLABORATOR')
    expect(access('supplier', '/factory-portal')).toBeNull()
  })

  it('normalizes legacy and new role enums to the same decision', () => {
    // 同一个人经 legacy 与 Context 两条路径必须得到一致结果
    for (const [legacy, modern] of [
      ['admin', 'OWNER'], ['operator', 'OPERATOR'], ['viewer', 'READ_ONLY'],
      ['compliance_approver', 'COMPLIANCE'], ['superadmin', 'PLATFORM_ADMIN'],
      ['supplier', 'FACTORY_COLLABORATOR'],
    ]) {
      for (const path of ['/orders', '/users', '/platform-admin', '/factory-portal']) {
        expect(viaContext(ctx(modern), path)).toBe(access(legacy, path))
      }
      expect(defaultLanding(null, false, ctx(modern)))
        .toBe(defaultLanding({ role: legacy }))
    }
  })
})

/**
 * 守卫传参契约（回归）：路由守卫会**同时**传 `user`（legacy 兜底）与 `context`
 * （权威源）。两条真实缺陷由此固化：
 *   1. 守卫漏传 `user` → 兜底分支拿到空角色 → 工厂账号进不去门户、
 *      管理员进不去 `/users`、合规审批员反被放行到 `/orders`（越权）。
 *   2. `user` 压过 `context` → 代客进入租户后仍被当平台账号放行到 `/platform-admin`。
 */
describe('Phase 1.8 guard argument contract', () => {
  beforeEach(() => localStorage.clear())

  const ctx = (role, source = 'MEMBERSHIP', extra = {}) => ({
    user_id: 1, workspace_id: 10, role, source, is_impersonating: false, ...extra,
  })

  it('lets context win when both user and context are passed', () => {
    // 平台账号代客进入租户：Context 是 OPERATOR，legacy 仍是 superadmin
    const impersonated = ctx('OPERATOR', 'MEMBERSHIP', { is_impersonating: true })
    expect(routeRedirect({
      path: '/platform-admin', authenticated: true,
      user: { role: 'superadmin' }, context: impersonated,
    })).toBe('/dashboard')
    // 租户 OWNER 即使带着陈旧的 legacy viewer，也必须能进 /users
    expect(routeRedirect({
      path: '/users', authenticated: true,
      user: { role: 'viewer' }, context: ctx('OWNER'),
    })).toBeNull()
  })

  it('uses the legacy fallback when context is unavailable', () => {
    // 守卫必须始终传 `user`：Context 缺失时它是唯一的身份来源。
    // （G-3 之前工厂账号恒无 Context；现在该分支覆盖的是请求失败等场景。）
    const guardArgs = (legacyRole) => ({
      path: '/factory-portal', authenticated: true,
      user: { role: legacyRole }, context: null,
    })
    expect(routeRedirect(guardArgs('supplier'))).toBeNull()
    expect(routeRedirect({ ...guardArgs('admin'), path: '/users' })).toBeNull()
    expect(routeRedirect({ ...guardArgs('compliance_approver'), path: '/orders' })).toBe('/compliance-workbench')
  })

  it('falls back to dashboard when neither source provides a role', () => {
    // 守卫漏传 user 且 Context 为空时：不得放行受保护页面
    expect(routeRedirect({
      path: '/users', authenticated: true, user: undefined, context: null,
    })).toBe('/dashboard')
  })

  it('routes /login through context-aware default landing', () => {
    // /login 分支必须透传 context，否则平台账号登录后会被送到 /dashboard
    expect(routeRedirect({
      path: '/login', authenticated: true, context: ctx('PLATFORM_ADMIN', 'PLATFORM'),
    })).toBe('/platform-admin')
    expect(routeRedirect({
      path: '/login', authenticated: true,
      context: ctx('FACTORY_COLLABORATOR', 'FACTORY'),
    })).toBe('/factory-portal')
  })
})
