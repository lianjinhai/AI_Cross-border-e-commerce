import { describe, expect, it } from 'vitest'
import router from '../src/app/router'
import { LEGACY_REDIRECTS, legacyRedirectTarget } from '../src/app/router/legacy-redirects'

/**
 * 路由回归守卫（V9 版，平移自 frontend/tests/router.test.js 的守卫意图）：
 * 1. 后端能力必须在前端有可达入口（新路径全量注册，且懒加载）；
 * 2. 旧路径 302 映射表（契约 §3.2，30 条）全量挂接且目标正确；
 * 3. R8：/platform-admin 与 /platform-admin?tab=audit 同 path 异 query。
 */
const ALL_SPACE_ROUTES = [
  '/app', '/app/market/discovery', '/app/products', '/app/products/:id', '/app/listings',
  '/app/listings/:id', '/app/compliance', '/app/compliance/approvals', '/app/launch',
  '/app/launch/:id', '/app/channels/shops', '/app/supply/suppliers', '/app/supply/purchases',
  '/app/pricing', '/app/ads', '/app/orders', '/app/refunds', '/app/settlements',
  '/app/support', '/app/risk/alerts', '/app/analytics/bi', '/app/analytics/finance',
  '/app/analytics/landed-cost', '/app/ai/workflows', '/app/ai/knowledge',
  '/app/ai/decisions', '/app/settings/ai', '/app/settings/team',
  '/console/overview', '/console/tenants', '/console/audit', '/console/maintenance',
  '/factory/products',
]

const flatten = (routes, prefix = '') => routes.flatMap((r) => {
  const full = `${prefix}/${r.path}`.replace(/\/{2,}/g, '/')
  return [full, ...(r.children ? flatten(r.children, full) : [])]
})

const allPaths = () => flatten(router.options.routes)

const findRoute = (path) => {
  for (const r of router.options.routes) {
    if (r.path === path) return r
    const child = (r.children || []).find((c) => `${r.path}/${c.path}`.replace(/\/{2,}/g, '/') === path
      || (c.path === '' && r.path === path.replace(/\/$/, '')))
    if (child) return child
  }
  return undefined
}

describe('router coverage — 新空间路由', () => {
  it('registers every business page under the three spaces', () => {
    const paths = allPaths()
    const missing = ALL_SPACE_ROUTES.filter((p) => !paths.includes(p))
    expect(missing, `未注册的路由: ${missing.join(', ')}`).toEqual([])
  })

  it('lazy-loads every page so route-level code splitting keeps working', () => {
    const eager = router.options.routes
      .filter((r) => r.component && typeof r.component !== 'function')
      .concat(
        router.options.routes
          .flatMap((r) => r.children || [])
          .filter((c) => typeof c.component !== 'function' && !c.redirect),
      )
    expect(eager.map((r) => r.path ?? r), '以下路由未使用懒加载').toEqual([])
  })

  it('carries the frozen meta contract (space/domain/title) on page routes', () => {
    const shell = router.options.routes.find((r) => r.path === '/app')
    for (const child of shell.children) {
      expect(child.meta?.space).toBe('app')
      expect(typeof child.meta?.title).toBe('string')
      expect(typeof child.meta?.domain).toBe('string')
    }
    // requiresOwner 仅 /app/settings/*
    const settings = shell.children.filter((c) => c.meta?.requiresOwner)
    expect(settings.map((c) => c.path).sort()).toEqual(['settings/ai', 'settings/team'])
    // hidden 仅参数详情路由
    const hidden = shell.children.filter((c) => c.meta?.hidden)
    expect(hidden.map((c) => c.path).sort()).toEqual(['launch/:id', 'listings/:id', 'products/:id'])
  })
})

describe('legacy 302 mapping — 契约 §3.2（30 条，无孤儿）', () => {
  it('mounts every legacy path as a redirect route', () => {
    const paths = allPaths()
    const legacyFroms = [...new Set(LEGACY_REDIRECTS.map((r) => r.from.split('?')[0]))]
    const missing = legacyFroms.filter((p) => !paths.includes(p))
    expect(missing, `未挂接 302 的旧路径: ${missing.join(', ')}`).toEqual([])
  })

  it('resolves each legacy entry to its contracted target', () => {
    expect(legacyRedirectTarget({ path: '/login' })).toBe('/console/login')
    expect(legacyRedirectTarget({ path: '/' })).toBe('/app')
    expect(legacyRedirectTarget({ path: '/dashboard' })).toBe('/app')
    expect(legacyRedirectTarget({ path: '/discovery' })).toBe('/app/market/discovery')
    expect(legacyRedirectTarget({ path: '/products' })).toBe('/app/products')
    expect(legacyRedirectTarget({ path: '/listings' })).toBe('/app/listings')
    expect(legacyRedirectTarget({ path: '/compliance' })).toBe('/app/compliance')
    expect(legacyRedirectTarget({ path: '/compliance-workbench' })).toBe('/app/compliance/approvals')
    expect(legacyRedirectTarget({ path: '/launch' })).toBe('/app/launch')
    expect(legacyRedirectTarget({ path: '/shops' })).toBe('/app/channels/shops')
    expect(legacyRedirectTarget({ path: '/suppliers' })).toBe('/app/supply/suppliers')
    expect(legacyRedirectTarget({ path: '/factory-portal' })).toBe('/factory/products')
    expect(legacyRedirectTarget({ path: '/pricing' })).toBe('/app/pricing')
    expect(legacyRedirectTarget({ path: '/ads' })).toBe('/app/ads')
    expect(legacyRedirectTarget({ path: '/orders' })).toBe('/app/orders')
    expect(legacyRedirectTarget({ path: '/refunds' })).toBe('/app/refunds')
    expect(legacyRedirectTarget({ path: '/settlements' })).toBe('/app/settlements')
    expect(legacyRedirectTarget({ path: '/support' })).toBe('/app/support')
    expect(legacyRedirectTarget({ path: '/workflows' })).toBe('/app/ai/workflows')
    expect(legacyRedirectTarget({ path: '/knowledge' })).toBe('/app/ai/knowledge')
    expect(legacyRedirectTarget({ path: '/bi' })).toBe('/app/analytics/bi')
    expect(legacyRedirectTarget({ path: '/finance' })).toBe('/app/analytics/finance')
    expect(legacyRedirectTarget({ path: '/alerts' })).toBe('/app/risk/alerts')
    expect(legacyRedirectTarget({ path: '/ai-decisions' })).toBe('/app/ai/decisions')
    expect(legacyRedirectTarget({ path: '/users' })).toBe('/app/settings/team')
    expect(legacyRedirectTarget({ path: '/settings' })).toBe('/app/settings/ai')
  })

  it('passes through :id params and query on parameterized redirects', () => {
    expect(legacyRedirectTarget({ path: '/launch/42', params: { id: 42 } })).toBe('/app/launch/42')
    expect(legacyRedirectTarget({ path: '/orders', query: { page: '3' } }))
      .toEqual({ path: '/app/orders', query: { page: '3' } })
    expect(legacyRedirectTarget({ path: '/launch/7', query: { mine: 'true' } }))
      .toEqual({ path: '/app/launch/7', query: { mine: 'true' } })
  })

  it('falls through to 404 for unmapped legacy paths (no silent /app fallback)', () => {
    expect(legacyRedirectTarget({ path: '/no-such-legacy-page' })).toBeNull()
    expect(legacyRedirectTarget({ path: '/launching' })).toBeNull()
  })
})

describe('R8 — /platform-admin 同 path 异 query（契约 §3.2 #28）', () => {
  it('redirects plain /platform-admin to /console/overview', () => {
    expect(legacyRedirectTarget({ path: '/platform-admin', query: {} })).toBe('/console/overview')
  })

  it('redirects /platform-admin?tab=audit to /console/audit by explicitly judging to.query.tab', () => {
    expect(legacyRedirectTarget({ path: '/platform-admin', query: { tab: 'audit' } })).toBe('/console/audit')
    // 其它 tab 值不触发 audit 分支（query 子态语义废弃，仅 audit 历史深链兼容）
    expect(legacyRedirectTarget({ path: '/platform-admin', query: { tab: 'tenants' } })).toBe('/console/overview')
  })

  it('mounts /platform-admin as a function redirect (not a static target)', () => {
    const route = findRoute('/platform-admin')
    expect(route).toBeTruthy()
    expect(typeof route.redirect).toBe('function')
  })
})

describe('error pages — 契约 §3.3.3', () => {
  it('mounts /404 /403 /500 and a catch-all that lands on 404', () => {
    for (const p of ['/404', '/403', '/500']) {
      expect(findRoute(p)).toBeTruthy()
    }
    const catchAll = router.options.routes.find((r) => r.path === '/:pathMatch(.*)*')
    expect(catchAll?.redirect).toBe('/404')
  })
})
