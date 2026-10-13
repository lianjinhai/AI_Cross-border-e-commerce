import { beforeEach, describe, expect, it } from 'vitest'
import {
  canAdmin,
  canApprove,
  canWrite,
  currentUser,
  defaultLanding,
  identityFrom,
  routeRedirect,
} from '../src/permissions/permissions'

/**
 * 权限/路由分流回归（平移自 frontend/tests/permissions.test.js）。
 * 断言结构与判定顺序语义逐条保留，路径按契约 §3.2 映射到新前缀：
 *   /login→/console/login、/dashboard→/app、/platform-admin→/console/overview、
 *   /factory-portal→/factory/products、/orders→/app/orders、
 *   /users→/app/settings/team、/settings→/app/settings/ai、
 *   /compliance-workbench→/app/compliance/approvals、/bi→/app/analytics/bi 等。
 */
const access = (role, path, options = {}) => routeRedirect({
  path,
  authenticated: options.authenticated ?? true,
  user: role ? { role } : null,
  impersonating: options.impersonating ?? false,
})

/**
 * Phase 1.8 / D24：legacy `erp_user` **不再授予任何权限**（写权限 fail-closed）。
 * 本组只锁「不授予」这一半；另一半由 permissions-can.test.js 的 Context 路径覆盖。
 */
describe('role capability policy (legacy grants nothing)', () => {
  beforeEach(() => localStorage.clear())

  it.each([
    'admin', 'owner', 'operator', 'viewer', 'compliance_approver', 'supplier', 'superadmin',
  ])('legacy %s grants no capability while the context is unavailable', (role) => {
    localStorage.setItem('erp_user', JSON.stringify({ role }))
    expect(canWrite()).toBe(false)
    expect(canAdmin()).toBe(false)
    expect(canApprove()).toBe(false)
  })

  it('fails closed when persisted identity is corrupted', () => {
    localStorage.setItem('erp_user', '{bad json')
    expect(currentUser()).toBeNull()
    expect(canWrite()).toBe(false)
  })
})

describe('executable role journeys', () => {
  it('sends an anonymous visitor to login', () => {
    expect(access(null, '/app/orders', { authenticated: false })).toBe('/console/login')
    expect(access(null, '/console/login', { authenticated: false })).toBeNull()
  })

  it('keeps supplier accounts inside the factory workspace', () => {
    expect(defaultLanding({ role: 'supplier' })).toBe('/factory/products')
    expect(access('supplier', '/factory/products')).toBeNull()
    expect(access('supplier', '/app/orders')).toBe('/factory/products')
    expect(access('supplier', '/console/overview')).toBe('/app')
  })

  it('keeps compliance approvers in read-and-review pages', () => {
    for (const path of ['/app/compliance/approvals', '/app', '/app/analytics/bi', '/app/listings', '/app/compliance']) {
      expect(access('compliance_approver', path)).toBeNull()
    }
    for (const path of ['/app/orders', '/app/analytics/finance', '/app/settings/ai', '/app/settings/team']) {
      expect(access('compliance_approver', path)).toBe('/app/compliance/approvals')
    }
  })

  /**
   * 上线中心（/app/launch 前缀白名单）：合规员可只读进入列表与详情，
   * 但前缀匹配**不得**放宽其它路径（如 /app/orders 仍被弹回；/app/launching 形近拒绝）。
   */
  it('lets compliance approvers read the launch center by prefix, without widening other paths', () => {
    expect(access('compliance_approver', '/app/launch')).toBeNull()
    expect(access('compliance_approver', '/app/launch/42')).toBeNull()
    expect(access('compliance_approver', '/app/launching')).toBe('/app/compliance/approvals')
    expect(access('compliance_approver', '/app/orders')).toBe('/app/compliance/approvals')
  })

  it('allows tenant admins to manage tenant settings but not the platform console', () => {
    expect(access('admin', '/app/settings/team')).toBeNull()
    expect(access('admin', '/app/settings/ai')).toBeNull()
    expect(access('admin', '/console/overview')).toBe('/app')
  })

  it.each(['operator', 'viewer'])('%s cannot enter tenant administration', (role) => {
    expect(access(role, '/app/settings/team')).toBe('/app')
    expect(access(role, '/app/settings/ai')).toBe('/app')
    expect(access(role, '/app/orders')).toBeNull()
  })

  it('isolates a platform superadmin until tenant impersonation begins', () => {
    expect(defaultLanding({ role: 'superadmin' })).toBe('/console/overview')
    expect(access('superadmin', '/app/orders')).toBe('/console/overview')
    expect(access('superadmin', '/console/overview')).toBeNull()
    expect(access('superadmin', '/app/orders', { impersonating: true })).toBeNull()
    expect(access('superadmin', '/console/overview', { impersonating: true })).toBe('/app')
  })

  it('lets authenticated users reach the error pages regardless of role', () => {
    for (const role of ['operator', 'compliance_approver', 'supplier']) {
      for (const path of ['/404', '/403', '/500']) {
        expect(access(role, path)).toBeNull()
      }
    }
  })
})

/**
 * 路由分流改吃 Workspace Context（新枚举行为固化，判定顺序平移）。
 */
describe('workspace context routing', () => {
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
    expect(viaContext(ctx('OWNER'), '/app/settings/team')).toBeNull()
    expect(viaContext(ctx('OWNER'), '/app/settings/ai')).toBeNull()
    expect(viaContext(ctx('OWNER'), '/console/overview')).toBe('/app')
    expect(defaultLanding(null, false, ctx('OWNER'))).toBe('/app')
  })

  it('keeps OPERATOR and READ_ONLY out of tenant administration', () => {
    for (const role of ['OPERATOR', 'READ_ONLY']) {
      expect(viaContext(ctx(role), '/app/settings/team')).toBe('/app')
      expect(viaContext(ctx(role), '/app/settings/ai')).toBe('/app')
      expect(viaContext(ctx(role), '/app/orders')).toBeNull()
    }
  })

  it('restricts COMPLIANCE to the whitelisted review pages', () => {
    for (const path of ['/app/compliance/approvals', '/app', '/app/analytics/bi', '/app/listings', '/app/compliance']) {
      expect(viaContext(ctx('COMPLIANCE'), path)).toBeNull()
    }
    for (const path of ['/app/orders', '/app/analytics/finance', '/app/settings/team']) {
      expect(viaContext(ctx('COMPLIANCE'), path)).toBe('/app/compliance/approvals')
    }
    expect(defaultLanding(null, false, ctx('COMPLIANCE'))).toBe('/app/compliance/approvals')
  })

  it('keeps FACTORY_COLLABORATOR inside the factory portal', () => {
    const factory = ctx('FACTORY_COLLABORATOR', 'FACTORY', { workspace_id: 3 })
    expect(viaContext(factory, '/factory/products')).toBeNull()
    expect(viaContext(factory, '/app/orders')).toBe('/factory/products')
    expect(viaContext(factory, '/console/overview')).toBe('/app')
    expect(defaultLanding(null, false, factory)).toBe('/factory/products')
  })

  it('sends PLATFORM_ADMIN to the platform console, and to /app once impersonating', () => {
    const platform = ctx('PLATFORM_ADMIN', 'PLATFORM', { workspace_id: null })
    expect(viaContext(platform, '/app/orders')).toBe('/console/overview')
    expect(viaContext(platform, '/console/overview')).toBeNull()
    expect(defaultLanding(null, false, platform)).toBe('/console/overview')
    // 代客进入租户后：Context 的 is_impersonating 必须让平台账号当普通租户看
    const impersonated = ctx('OPERATOR', 'MEMBERSHIP', { is_impersonating: true })
    expect(viaContext(impersonated, '/app/orders')).toBeNull()
    expect(viaContext(impersonated, '/console/overview')).toBe('/app')
  })

  it('trusts context is_impersonating over a missing localStorage marker', () => {
    // 后端已透传 is_impersonating；前端不再只能靠 localStorage 判断
    const impersonated = ctx('OPERATOR', 'MEMBERSHIP', { is_impersonating: true })
    expect(identityFrom({ context: impersonated }).impersonating).toBe(true)
    expect(identityFrom({ context: ctx('OPERATOR') }).impersonating).toBe(false)
  })

  it('falls back to legacy identity when the context is unavailable', () => {
    // Context 不可用（网络抖动 / 后端 5xx / 未登录）时仍必须能正确分流。
    const identity = identityFrom({ user: { role: 'supplier' } })
    expect(identity.fromContext).toBe(false)
    expect(identity.source).toBe('LEGACY_FALLBACK')
    expect(identity.role).toBe('FACTORY_COLLABORATOR')
    expect(access('supplier', '/factory/products')).toBeNull()
  })

  it('normalizes legacy and new role enums to the same decision', () => {
    // 同一个人经 legacy 与 Context 两条路径必须得到一致结果
    for (const [legacy, modern] of [
      ['admin', 'OWNER'], ['operator', 'OPERATOR'], ['viewer', 'READ_ONLY'],
      ['compliance_approver', 'COMPLIANCE'], ['superadmin', 'PLATFORM_ADMIN'],
      ['supplier', 'FACTORY_COLLABORATOR'],
    ]) {
      for (const path of ['/app/orders', '/app/settings/team', '/console/overview', '/factory/products']) {
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
 *      管理员进不去设置页、合规审批员反被放行到订单页（越权）。
 *   2. `user` 压过 `context` → 代客进入租户后仍被当平台账号放行到控制台。
 */
describe('guard argument contract', () => {
  beforeEach(() => localStorage.clear())

  const ctx = (role, source = 'MEMBERSHIP', extra = {}) => ({
    user_id: 1, workspace_id: 10, role, source, is_impersonating: false, ...extra,
  })

  it('lets context win when both user and context are passed', () => {
    // 平台账号代客进入租户：Context 是 OPERATOR，legacy 仍是 superadmin
    const impersonated = ctx('OPERATOR', 'MEMBERSHIP', { is_impersonating: true })
    expect(routeRedirect({
      path: '/console/overview', authenticated: true,
      user: { role: 'superadmin' }, context: impersonated,
    })).toBe('/app')
    // 租户 OWNER 即使带着陈旧的 legacy viewer，也必须能进 /app/settings/team
    expect(routeRedirect({
      path: '/app/settings/team', authenticated: true,
      user: { role: 'viewer' }, context: ctx('OWNER'),
    })).toBeNull()
  })

  it('uses the legacy fallback when context is unavailable', () => {
    // 守卫必须始终传 `user`：Context 缺失时它是唯一的身份来源。
    const guardArgs = (legacyRole) => ({
      path: '/factory/products', authenticated: true,
      user: { role: legacyRole }, context: null,
    })
    expect(routeRedirect(guardArgs('supplier'))).toBeNull()
    expect(routeRedirect({ ...guardArgs('admin'), path: '/app/settings/team' })).toBeNull()
    expect(routeRedirect({ ...guardArgs('compliance_approver'), path: '/app/orders' })).toBe('/app/compliance/approvals')
  })

  it('falls back to /app when neither source provides a role', () => {
    // 守卫漏传 user 且 Context 为空时：不得放行受保护页面
    expect(routeRedirect({
      path: '/app/settings/team', authenticated: true, user: undefined, context: null,
    })).toBe('/app')
  })

  it('routes /console/login through context-aware default landing', () => {
    // /console/login 分支必须透传 context，否则平台账号登录后会被送到 /app
    expect(routeRedirect({
      path: '/console/login', authenticated: true, context: ctx('PLATFORM_ADMIN', 'PLATFORM'),
    })).toBe('/console/overview')
    expect(routeRedirect({
      path: '/console/login', authenticated: true,
      context: ctx('FACTORY_COLLABORATOR', 'FACTORY'),
    })).toBe('/factory/products')
  })
})
