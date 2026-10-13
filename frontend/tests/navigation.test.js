import { describe, expect, it } from 'vitest'
import {
  BUSINESS_DOMAINS,
  FACTORY_DOMAINS,
  PLATFORM_DOMAINS,
  buildDomains,
  filterDomainsByPaths,
} from '../src/composables/navigation'

/**
 * UX-02：11 域导航结构与角色可见性过滤的纯函数回归。
 * 项目未装 @vue/test-utils，故只测 composable（沿用现有测试风格）。
 */
const pathsOf = (domains) => domains.flatMap((d) => d.children.map((c) => c.path)).sort()

const ALL_BUSINESS_PATHS = [
  '/dashboard', '/discovery', '/products', '/listings', '/launch',
  '/compliance-workbench', '/compliance', '/suppliers', '/shops', '/orders',
  '/settlements', '/refunds', '/support', '/pricing', '/ads', '/alerts',
  '/bi', '/finance', '/knowledge', '/ai-decisions', '/workflows', '/settings', '/users',
].sort()

describe('BUSINESS_DOMAINS', () => {
  it('defines the frozen 11 first-level domains', () => {
    expect(BUSINESS_DOMAINS).toHaveLength(11)
    expect(BUSINESS_DOMAINS.map((d) => d.key)).toEqual([
      'home', 'market', 'product', 'supply', 'channel', 'fulfill',
      'aftersale', 'optimize', 'analytics', 'aiops', 'admin',
    ])
  })

  it('each domain exposes {key,label,icon,children[]}', () => {
    for (const d of BUSINESS_DOMAINS) {
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
})

describe('buildDomains — role visibility', () => {
  it('OWNER with member admin sees all 11 domains and every business path', () => {
    const domains = buildDomains({ roleKey: 'OWNER', canManageMembers: true })
    expect(domains).toHaveLength(11)
    expect(pathsOf(domains)).toEqual(ALL_BUSINESS_PATHS)
  })

  it('OWNER without member admin still sees settings but not users', () => {
    const paths = pathsOf(buildDomains({ roleKey: 'OWNER', canManageMembers: false }))
    expect(paths).toContain('/settings')
    expect(paths).not.toContain('/users')
  })

  it.each(['OPERATOR', 'READ_ONLY'])('%s hides /settings, /users, /compliance-workbench', (roleKey) => {
    const paths = pathsOf(buildDomains({ roleKey }))
    expect(paths).not.toContain('/settings')
    expect(paths).not.toContain('/users')
    expect(paths).not.toContain('/compliance-workbench')
    const expected = ALL_BUSINESS_PATHS.filter(
      (p) => !['/settings', '/users', '/compliance-workbench'].includes(p),
    )
    expect(paths).toEqual(expected)
  })

  it('drops domains that become empty after filtering (OPERATOR loses the admin domain)', () => {
    const domains = buildDomains({ roleKey: 'OPERATOR' })
    expect(domains.map((d) => d.key)).not.toContain('admin')
    // 11 域去掉仅含隐藏项的 admin 域 → 10
    expect(domains).toHaveLength(10)
  })

  it('COMPLIANCE keeps only the 6 whitelisted paths and drops empty domains', () => {
    const domains = buildDomains({ roleKey: 'COMPLIANCE' })
    expect(pathsOf(domains)).toEqual(
      ['/compliance-workbench', '/dashboard', '/bi', '/listings', '/compliance', '/launch'].sort(),
    )
    // 命中 home / product / analytics 三个域
    expect(domains).toHaveLength(3)
  })

  it('PLATFORM_ADMIN gets the platform domain only', () => {
    const domains = buildDomains({ roleKey: 'PLATFORM_ADMIN' })
    expect(domains).toBe(PLATFORM_DOMAINS)
    expect(pathsOf(domains)).toContain('/platform-admin')
    expect(pathsOf(domains)).toContain('/platform-admin?tab=audit')
  })

  it('FACTORY_COLLABORATOR gets the factory domain only', () => {
    const domains = buildDomains({ roleKey: 'FACTORY_COLLABORATOR' })
    expect(domains).toBe(FACTORY_DOMAINS)
    expect(pathsOf(domains)).toEqual(['/factory-portal'])
  })

  it('keeps /users only when canManageMembers is true', () => {
    expect(pathsOf(buildDomains({ roleKey: 'OWNER', canManageMembers: true }))).toContain('/users')
    expect(pathsOf(buildDomains({ roleKey: 'OWNER', canManageMembers: false }))).not.toContain('/users')
    expect(pathsOf(buildDomains({ roleKey: 'OPERATOR' }))).not.toContain('/users')
  })

  it('treats an unknown role like a non-owner (hidden admin entries)', () => {
    const paths = pathsOf(buildDomains({ roleKey: '' }))
    expect(paths).not.toContain('/settings')
    expect(paths).not.toContain('/users')
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
