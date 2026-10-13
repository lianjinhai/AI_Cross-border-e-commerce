import { describe, expect, it } from 'vitest'
import {
  CONSOLE_DOMAINS,
  FACTORY_DOMAINS,
  WORKSPACE_DOMAINS,
  buildDomains,
  filterDomainsByPaths,
  whitelistForRole,
} from '../src/shared/navigation/filter'

/**
 * V9 三空间导航结构与角色可见性过滤的纯函数回归。
 * 平移自 frontend/tests/navigation.test.js：测试模式/断言粒度不变，
 * 路径按契约 §3.2 映射到 /app|/console|/factory 前缀（NAVIGATION 冻结文档 §1）。
 * 项目未装 @vue/test-utils，故只测纯模块（沿用现有测试风格）。
 */
const pathsOf = (domains) => domains.flatMap((d) => d.children.map((c) => c.path)).sort()

const ALL_BUSINESS_PATHS = [
  '/app', '/app/market/discovery', '/app/products', '/app/listings', '/app/launch',
  '/app/compliance', '/app/compliance/approvals', '/app/supply/suppliers',
  '/app/supply/purchases', '/app/channels/shops', '/app/orders', '/app/settlements',
  '/app/refunds', '/app/support', '/app/pricing', '/app/ads', '/app/risk/alerts',
  '/app/analytics/bi', '/app/analytics/finance', '/app/analytics/landed-cost',
  '/app/ai/workflows', '/app/ai/knowledge', '/app/ai/decisions',
  '/app/settings/ai', '/app/settings/team',
].sort()

describe('WORKSPACE_DOMAINS', () => {
  it('defines the frozen 11 first-level domains', () => {
    expect(WORKSPACE_DOMAINS).toHaveLength(11)
    expect(WORKSPACE_DOMAINS.map((d) => d.key)).toEqual([
      'home', 'market', 'product', 'supply', 'channel', 'fulfill',
      'aftersale', 'optimization', 'analytics', 'aiops', 'settings',
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
  it('console tree splits the old /platform-admin into 4 pages', () => {
    expect(pathsOf(CONSOLE_DOMAINS)).toEqual([
      '/console/audit', '/console/maintenance', '/console/overview', '/console/tenants',
    ])
  })

  it('factory tree exposes only the wired entry (2 pending integrations stay out)', () => {
    expect(pathsOf(FACTORY_DOMAINS)).toEqual(['/factory/products'])
  })
})

describe('buildDomains — role visibility', () => {
  it('OWNER with member admin sees all 11 domains and every business path', () => {
    const domains = buildDomains({ roleKey: 'OWNER', canManageMembers: true })
    expect(domains).toHaveLength(11)
    expect(pathsOf(domains)).toEqual(ALL_BUSINESS_PATHS)
  })

  it('OWNER without member admin still sees AI settings but not team settings', () => {
    const paths = pathsOf(buildDomains({ roleKey: 'OWNER', canManageMembers: false }))
    expect(paths).toContain('/app/settings/ai')
    expect(paths).not.toContain('/app/settings/team')
  })

  it.each(['OPERATOR', 'READ_ONLY'])('%s hides /app/settings/* and /app/compliance/approvals', (roleKey) => {
    const paths = pathsOf(buildDomains({ roleKey }))
    expect(paths).not.toContain('/app/settings/ai')
    expect(paths).not.toContain('/app/settings/team')
    expect(paths).not.toContain('/app/compliance/approvals')
    const expected = ALL_BUSINESS_PATHS.filter(
      (p) => !['/app/settings/ai', '/app/settings/team', '/app/compliance/approvals'].includes(p),
    )
    expect(paths).toEqual(expected)
  })

  it('drops domains that become empty after filtering (OPERATOR loses the settings domain)', () => {
    const domains = buildDomains({ roleKey: 'OPERATOR' })
    expect(domains.map((d) => d.key)).not.toContain('settings')
    // 11 域去掉仅含隐藏项的 settings 域 → 10
    expect(domains).toHaveLength(10)
  })

  it('COMPLIANCE keeps only the 6 whitelisted paths and drops empty domains', () => {
    const domains = buildDomains({ roleKey: 'COMPLIANCE' })
    expect(pathsOf(domains)).toEqual(
      ['/app', '/app/analytics/bi', '/app/listings', '/app/compliance', '/app/compliance/approvals', '/app/launch'].sort(),
    )
    // 命中 home / product / analytics 三个域
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
    expect(pathsOf(domains)).toEqual(['/factory/products'])
  })

  it('keeps /app/settings/team only when canManageMembers is true', () => {
    expect(pathsOf(buildDomains({ roleKey: 'OWNER', canManageMembers: true }))).toContain('/app/settings/team')
    expect(pathsOf(buildDomains({ roleKey: 'OWNER', canManageMembers: false }))).not.toContain('/app/settings/team')
    expect(pathsOf(buildDomains({ roleKey: 'OPERATOR' }))).not.toContain('/app/settings/team')
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
    expect([...whitelistForRole({ roleKey: 'FACTORY_COLLABORATOR' })]).toEqual(['/factory/products'])
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
