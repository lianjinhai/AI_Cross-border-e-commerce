import { describe, expect, it } from 'vitest'
import {
  CONSOLE_DOMAINS,
  FACTORY_DOMAINS,
  WORKSPACE_DOMAINS,
  buildDomains,
  filterDomainsByPaths,
  whitelistForRole,
  NON_OWNER_HIDDEN_PATHS,
  COMPLIANCE_ALLOWED_PATHS,
} from '../src/shared/navigation/filter'
import {
  WORKSPACE_ENTRY_KEYS,
  WORKSPACE_COLLAPSIBLE_KEYS,
} from '../src/shared/navigation/types'

/**
 * V9 三空间导航结构与角色可见性过滤的纯函数回归。
 *
 * R3-2A：WORKSPACE 树由 8 域 26 项收敛为「4+1 入口」（mybiz/goods/orders/revenue/tools）。
 * 本文件同步更新断言：入口 key/label、tools 覆盖全部既有 path（**无遗漏**）、
 * 各角色可见项数、全树无重复 path。断言**不弱化**——旧「全业务路径集合」断言
 * 升级为「与 8 域时期逐条等价的 39 条 path 并集」，并额外校验分组归位与去重。
 * 控制台/工厂树与 filterDomainsByPaths 断言保持原样（不受本次收敛影响）。
 */
const pathsOf = (domains) => domains.flatMap((d) => d.children.map((c) => c.path)).sort()

/** 8 域时期全部 34 条业务 path + R3-2A 回归的 5 条 settings path = 39 条（收敛不减功能）。 */
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
  '/app/settings/workspace', '/app/settings/ai', '/app/settings/team',
  '/app/settings/credentials', '/app/settings/plan',
].sort()

/** 「全部工具」入口应收纳的低频/专业 path（8 域时期散落于 discovery/supply/channel/optimize/ai + settings）。 */
const TOOLS_PATHS = [
  '/app/supply/sourcing', '/app/supply/suppliers', '/app/supply/matching', '/app/supply/purchases',
  '/app/market/discovery', '/app/market/candidates',
  '/app/channels', '/app/channels/shops',
  '/app/listings', '/app/products/assets',
  '/app/ads', '/app/risk/alerts', '/app/optimization/experiments',
  '/app/ai/actions', '/app/ai/workflows', '/app/ai/agent-runs', '/app/ai/knowledge', '/app/ai/decisions',
  '/app/settings/workspace', '/app/settings/ai', '/app/settings/team',
  '/app/settings/credentials', '/app/settings/plan',
].sort()

describe('WORKSPACE_DOMAINS — R3-2A 4+1 入口结构', () => {
  it('defines exactly the 4 high-frequency entries + tools drawer', () => {
    expect(WORKSPACE_DOMAINS).toHaveLength(5)
    expect(WORKSPACE_DOMAINS.map((d) => d.key)).toEqual(WORKSPACE_ENTRY_KEYS)
    expect(WORKSPACE_ENTRY_KEYS).toEqual(['mybiz', 'goods', 'orders', 'revenue', 'tools'])
  })

  it('exposes the frozen 4+1 labels', () => {
    expect(WORKSPACE_DOMAINS.map((d) => d.label)).toEqual([
      '我的生意', '我的商品', '我的订单', '我的收益', '全部工具',
    ])
  })

  it('marks only the tools drawer as collapsible (el-sub-menu)', () => {
    expect(WORKSPACE_COLLAPSIBLE_KEYS).toEqual(['tools'])
    for (const d of WORKSPACE_DOMAINS) {
      expect(Boolean(d.collapsible)).toBe(WORKSPACE_COLLAPSIBLE_KEYS.includes(d.key))
    }
  })

  it('each entry exposes {key,label,icon,children[]} and every path is under /app', () => {
    for (const d of WORKSPACE_DOMAINS) {
      expect(typeof d.key).toBe('string')
      expect(typeof d.label).toBe('string')
      expect(typeof d.icon).toBe('string')
      expect(Array.isArray(d.children)).toBe(true)
      expect(d.children.length).toBeGreaterThan(0)
      for (const c of d.children) {
        expect(typeof c.path).toBe('string')
        expect(typeof c.label).toBe('string')
        expect(typeof c.icon).toBe('string')
        expect(c.path.startsWith('/app')).toBe(true)
      }
    }
  })

  it('groups the high-frequency entries exactly as specified', () => {
    const byKey = Object.fromEntries(WORKSPACE_DOMAINS.map((d) => [d.key, pathsOf([d])]))
    expect(byKey.mybiz).toEqual(['/app', '/app/tasks'])
    expect(byKey.goods).toEqual([
      '/app/compliance', '/app/compliance/approvals', '/app/launch', '/app/products',
    ])
    expect(byKey.orders).toEqual([
      '/app/fulfillment', '/app/orders', '/app/refunds', '/app/settlements', '/app/support',
    ])
    expect(byKey.revenue).toEqual([
      '/app/analytics/bi', '/app/analytics/finance', '/app/analytics/forecast',
      '/app/analytics/landed-cost', '/app/pricing',
    ])
  })

  it('the tools drawer covers every remaining legacy path (no page lost in the convergence)', () => {
    const tools = WORKSPACE_DOMAINS.find((d) => d.key === 'tools')
    expect(pathsOf([tools])).toEqual(TOOLS_PATHS)
  })

  it('the 4+1 union equals the full legacy business path set (39) with no duplicates', () => {
    const all = pathsOf(WORKSPACE_DOMAINS)
    expect(all).toEqual(ALL_BUSINESS_PATHS)
    expect(all).toHaveLength(39)
    expect(new Set(all).size).toBe(all.length) // 无重复 path
  })

  it('keeps the badge hints on the entries that have a live count source', () => {
    const badgeOf = (path) => WORKSPACE_DOMAINS
      .flatMap((d) => d.children).find((c) => c.path === path)?.badge
    expect(badgeOf('/app/tasks')).toBe('tasks')
    expect(badgeOf('/app/compliance/approvals')).toBe('approvals')
    expect(badgeOf('/app/ai/actions')).toBe('approvals')
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

describe('buildDomains — role visibility (R3-2A 4+1)', () => {
  it('OWNER with member admin sees all 5 entries and the full 39 business paths', () => {
    const domains = buildDomains({ roleKey: 'OWNER', canManageMembers: true })
    expect(domains).toHaveLength(5)
    expect(pathsOf(domains)).toEqual(ALL_BUSINESS_PATHS)
  })

  it('OWNER without member admin sees everything except /app/settings/team', () => {
    const paths = pathsOf(buildDomains({ roleKey: 'OWNER', canManageMembers: false }))
    expect(paths).toContain('/app/ai/agent-runs')
    expect(paths).toContain('/app/settings/workspace')
    expect(paths).not.toContain('/app/settings/team')
    expect(paths).toEqual(ALL_BUSINESS_PATHS.filter((p) => p !== '/app/settings/team'))
  })

  it.each(['OPERATOR', 'READ_ONLY'])('%s hides the whole /app/settings group and compliance approvals', (roleKey) => {
    const paths = pathsOf(buildDomains({ roleKey }))
    expect(paths).not.toContain('/app/compliance/approvals')
    for (const p of NON_OWNER_HIDDEN_PATHS) expect(paths).not.toContain(p)
    const expected = ALL_BUSINESS_PATHS.filter((p) => !NON_OWNER_HIDDEN_PATHS.has(p))
    expect(paths).toEqual(expected)
  })

  it('OPERATOR / READ_ONLY keep all 5 entries (every entry keeps non-empty children)', () => {
    for (const roleKey of ['OPERATOR', 'READ_ONLY']) {
      const domains = buildDomains({ roleKey })
      expect(domains.map((d) => d.key)).toEqual(WORKSPACE_ENTRY_KEYS)
      expect(domains.every((d) => d.children.length > 0)).toBe(true)
    }
  })

  it('COMPLIANCE keeps only the 6 frozen whitelist paths, mapped across 4 entries', () => {
    const domains = buildDomains({ roleKey: 'COMPLIANCE' })
    expect(pathsOf(domains)).toEqual(
      [...COMPLIANCE_ALLOWED_PATHS].sort(),
    )
    expect(pathsOf(domains)).toEqual(
      ['/app', '/app/analytics/bi', '/app/listings', '/app/compliance', '/app/compliance/approvals', '/app/launch'].sort(),
    )
    // 命中 mybiz / goods / revenue / tools 四个入口（orders 空 → 丢弃）
    expect(domains.map((d) => d.key)).toEqual(['mybiz', 'goods', 'revenue', 'tools'])
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

  it('non-OWNER roles never see any /app/settings/* path', () => {
    expect(pathsOf(buildDomains({ roleKey: 'OPERATOR' }))).not.toContain('/app/settings/team')
    expect(pathsOf(buildDomains({ roleKey: 'READ_ONLY' }))).not.toContain('/app/settings/ai')
    expect(pathsOf(buildDomains({ roleKey: 'READ_ONLY' }))).not.toContain('/app/settings/workspace')
  })

  it('treats an unknown role like a non-owner (hidden admin entries)', () => {
    const paths = pathsOf(buildDomains({ roleKey: '' }))
    expect(paths).not.toContain('/app/settings/ai')
    expect(paths).not.toContain('/app/settings/team')
  })

  it('suppresses entries by persona without touching the guard whitelist', () => {
    const full = buildDomains({ roleKey: 'OWNER', canManageMembers: true })
    const guided = buildDomains({ roleKey: 'OWNER', canManageMembers: true, persona: 'A' })
    expect(full.map((d) => d.key)).toEqual(WORKSPACE_ENTRY_KEYS)
    expect(guided.map((d) => d.key)).toEqual(['mybiz', 'goods', 'tools'])
    // persona 抑制是视觉层：白名单（守卫）不受影响
    expect([...whitelistForRole({ roleKey: 'OWNER', canManageMembers: true })].sort()).toEqual(pathsOf(full))
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

  it('non-owner whitelist equals the 39 business paths minus the hidden group (33)', () => {
    const wl = whitelistForRole({ roleKey: 'OPERATOR' })
    expect([...wl].sort()).toEqual(ALL_BUSINESS_PATHS.filter((p) => !NON_OWNER_HIDDEN_PATHS.has(p)))
    expect(wl.size).toBe(33)
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

  it('preserves the collapsible flag through filtering (tools drawer survives)', () => {
    const filtered = filterDomainsByPaths(WORKSPACE_DOMAINS, ['/app/listings'])
    expect(filtered).toHaveLength(1)
    expect(filtered[0].key).toBe('tools')
    expect(filtered[0].collapsible).toBe(true)
    expect(filtered[0].children.map((c) => c.path)).toEqual(['/app/listings'])
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
