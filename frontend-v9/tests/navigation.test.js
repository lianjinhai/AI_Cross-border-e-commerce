import { describe, expect, it } from 'vitest'
import {
  CONSOLE_DOMAINS,
  FACTORY_DOMAINS,
  WORKSPACE_DOMAINS,
  buildDomains,
  filterDomainsByPaths,
  whitelistForRole,
  NON_OWNER_HIDDEN_PATHS,
} from '../src/shared/navigation/filter'

/**
 * V9 三空间导航结构与角色可见性过滤的纯函数回归。
 * 平移自 frontend/tests/navigation.test.js：测试模式/断言粒度不变，
 * 路径按契约 §3.2 映射到 /app|/console|/factory 前缀（NAVIGATION 冻结文档 §1）。
 * 项目未装 @vue/test-utils，故只测纯模块（沿用现有测试风格）。
 */
const pathsOf = (domains) => domains.flatMap((d) => d.children.map((c) => c.path)).sort()

const ALL_BUSINESS_PATHS = [
  '/app', '/app/tasks',
  '/app/market/discovery', '/app/market/candidates',
  '/app/products', '/app/products/assets',
  '/app/listings', '/app/launch',
  '/app/compliance', '/app/compliance/approvals',
  '/app/supply/sourcing', '/app/supply/suppliers', '/app/supply/matching', '/app/supply/purchases',
  '/app/channels', '/app/channels/shops',
  '/app/orders', '/app/fulfillment', '/app/refunds', '/app/support', '/app/settlements',
  '/app/pricing', '/app/ads', '/app/risk/alerts', '/app/optimization/experiments',
  '/app/analytics/bi', '/app/analytics/finance', '/app/analytics/landed-cost', '/app/analytics/forecast',
  '/app/ai/actions', '/app/ai/workflows', '/app/ai/agent-runs', '/app/ai/knowledge', '/app/ai/decisions',
].sort()

describe('WORKSPACE_DOMAINS', () => {
  it('defines the frozen 8 first-level domains', () => {
    expect(WORKSPACE_DOMAINS).toHaveLength(8)
    expect(WORKSPACE_DOMAINS.map((d) => d.key)).toEqual([
      'workbench', 'discovery', 'supply', 'channel', 'orders', 'optimize', 'finance', 'ai',
    ])
  })

  it('each domain exposes {key,label,icon,children[]}', () => {
    for (const d of WORKSPACE_DOMAINS) {
      expect(typeof d.key).toBe('string')
      expect(typeof d.label).toBe('string')
      expect(typeof d.icon).toBe('string')
      expect(Array.isArray(d.children)).toBe(true)
      for (const c of d.children) {
        expect(typeof c.path).toBe('string')
        expect(c.path.startsWith('/')).toBe(true)
      }
    }
  })

  it('every workspace path lives under the /app prefix (contract §3.2)', () => {
    for (const p of pathsOf(WORKSPACE_DOMAINS)) {
      expect(p.startsWith('/app')).toBe(true)
    }
  })
})

describe('CONSOLE / FACTORY trees', () => {
  it('console tree splits the old /platform-admin into 4 pages + R1 包 3 新增 3 项', () => {
    expect(pathsOf(CONSOLE_DOMAINS)).toEqual([
      '/console/adapters', '/console/ai-resources', '/console/audit',
      '/console/maintenance', '/console/overview', '/console/rules', '/console/tenants',
    ])
  })

  it('factory tree exposes home + products + R1 包 3 新增 stocking/fulfillment/capability', () => {
    expect(pathsOf(FACTORY_DOMAINS)).toEqual([
      '/factory', '/factory/capability', '/factory/fulfillment',
      '/factory/products', '/factory/stocking',
    ])
  })
})

describe('buildDomains — role visibility', () => {
  it('OWNER with member admin sees all 8 domains and every business path', () => {
    const domains = buildDomains({ roleKey: 'OWNER', canManageMembers: true })
    expect(domains).toHaveLength(8)
    expect(pathsOf(domains)).toEqual(ALL_BUSINESS_PATHS)
  })

  it('OWNER without member admin still sees all business paths (settings 已下沉账户菜单)', () => {
    // settings 已不在 WORKSPACE_DOMAINS，OWNER 无 canManageMembers 时 paths 不含 /app/settings/*
    // 但仍可访问全部 8 域业务路径（agent-runs 无 requiresOwner 标注，对 OWNER 可见）
    const paths = pathsOf(buildDomains({ roleKey: 'OWNER', canManageMembers: false }))
    expect(paths).toContain('/app/ai/actions')
    expect(paths).toContain('/app/ai/agent-runs')
    expect(paths).not.toContain('/app/settings/team')
  })

  it.each(['OPERATOR', 'READ_ONLY'])('%s hides Owner-only paths and compliance approvals', (roleKey) => {
    const paths = pathsOf(buildDomains({ roleKey }))
    // settings 已下沉，非 OWNER 无 /app/settings/*；compliance/approvals 仍对 OPERATOR 隐藏
    expect(paths).not.toContain('/app/compliance/approvals')
    const expected = ALL_BUSINESS_PATHS.filter(
      (p) => !NON_OWNER_HIDDEN_PATHS.has(p),
    )
    expect(paths).toEqual(expected)
  })

  it('drops domains that become empty after filtering (OPERATOR loses empty domains)', () => {
    const domains = buildDomains({ roleKey: 'OPERATOR' })
    // 8 域中 OPERATOR 可见的域数（NON_OWNER_HIDDEN 仅 compliance/approvals）
    // workbench/discovery/supply/channel/orders/optimize/finance/ai → 8 域，
    // 但 discovery 域的 compliance/approvals 被隐藏后 discovery 仍有其他子项 → 仍保留
    expect(domains).toHaveLength(8)
  })

  it('COMPLIANCE keeps only the 6 whitelisted paths and drops empty domains', () => {
    const domains = buildDomains({ roleKey: 'COMPLIANCE' })
    expect(pathsOf(domains)).toEqual(
      ['/app', '/app/analytics/bi', '/app/listings', '/app/compliance', '/app/compliance/approvals', '/app/launch'].sort(),
    )
    // 命中 workbench / discovery / finance 三个域（旧 home/product/analytics → 新 workbench/discovery/finance）
    expect(domains).toHaveLength(3)
  })

  it('PLATFORM_ADMIN (not impersonating) gets the console tree only', () => {
    const domains = buildDomains({ roleKey: 'PLATFORM_ADMIN' })
    expect(domains).toBe(CONSOLE_DOMAINS)
    expect(pathsOf(domains)).toContain('/console/overview')
    expect(pathsOf(domains)).toContain('/console/audit')
  })

  it('PLATFORM_ADMIN while impersonating falls back to the workspace tree (non-owner)', () => {
    const paths = pathsOf(buildDomains({ roleKey: 'PLATFORM_ADMIN', isImpersonating: true }))
    expect(paths).toContain('/app')
    expect(paths).not.toContain('/app/settings/team')
  })

  it('FACTORY_COLLABORATOR gets the factory domain only', () => {
    const domains = buildDomains({ roleKey: 'FACTORY_COLLABORATOR' })
    expect(domains).toBe(FACTORY_DOMAINS)
    expect(pathsOf(domains)).toEqual([
      '/factory', '/factory/capability', '/factory/fulfillment',
      '/factory/products', '/factory/stocking',
    ])
  })

  it('non-OWNER roles never see Owner-only settings paths (settings 已下沉)', () => {
    expect(pathsOf(buildDomains({ roleKey: 'OPERATOR' }))).not.toContain('/app/settings/team')
    expect(pathsOf(buildDomains({ roleKey: 'READ_ONLY' }))).not.toContain('/app/settings/ai')
  })

  it('treats an unknown role like a non-owner (hidden admin entries)', () => {
    const paths = pathsOf(buildDomains({ roleKey: '' }))
    expect(paths).not.toContain('/app/settings/ai')
    expect(paths).not.toContain('/app/settings/team')
  })
})

describe('whitelistForRole — 与 buildDomains 同源（禁止双事实源）', () => {
  it('produces the same leaf set buildDomains renders', () => {
    for (const [roleKey, canManageMembers] of [
      ['OWNER', true], ['OWNER', false], ['OPERATOR', false], ['COMPLIANCE', false],
      ['FACTORY_COLLABORATOR', false], ['', false],
    ]) {
      const domains = buildDomains({ roleKey, canManageMembers })
      expect([...whitelistForRole({ roleKey, canManageMembers })].sort()).toEqual(pathsOf(domains))
    }
  })

  it('console tree for PLATFORM_ADMIN, factory tree for FACTORY_COLLABORATOR', () => {
    expect([...whitelistForRole({ roleKey: 'PLATFORM_ADMIN' })].sort()).toEqual(pathsOf(CONSOLE_DOMAINS))
    expect([...whitelistForRole({ roleKey: 'FACTORY_COLLABORATOR' })].sort()).toEqual(
      ['/factory', '/factory/capability', '/factory/fulfillment', '/factory/products', '/factory/stocking'],
    )
  })
})

describe('filterDomainsByPaths', () => {
  it('keeps only whitelisted children and drops empty domains', () => {
    const domains = [
      { key: 'a', label: 'A', icon: 'I', children: [{ path: '/x', label: 'X', icon: 'I' }] },
      { key: 'b', label: 'B', icon: 'I', children: [{ path: '/y', label: 'Y', icon: 'I' }] },
    ]
    const filtered = filterDomainsByPaths(domains, ['/x'])
    expect(filtered).toHaveLength(1)
    expect(filtered[0].key).toBe('a')
    expect(filtered[0].children.map((c) => c.path)).toEqual(['/x'])
  })

  it('does not mutate the input domains', () => {
    const domains = [
      { key: 'a', label: 'A', icon: 'I', children: [{ path: '/x', label: 'X', icon: 'I' }] },
    ]
    const snapshot = JSON.stringify(domains)
    filterDomainsByPaths(domains, [])
    expect(JSON.stringify(domains)).toBe(snapshot)
  })
})
