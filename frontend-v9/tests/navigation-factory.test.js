import { describe, expect, it } from 'vitest'
import { FACTORY_DOMAINS, CONSOLE_DOMAINS } from '../src/shared/navigation/filter'

/**
 * 工厂/控制台导航树新增子项 path 回归（蓝图 R1 包 3 · §A.2 / §B.3）。
 *
 * 红线：包 3 扩展 factory/console 两树——FP 首页/备货/履约/供货能力 +
 * PC-03/04/05；path 全部不冲突 302 查表（均为 /factory|/console 深层子路径）。
 */
const pathsOf = (domains) => domains.flatMap((d) => d.children.map((c) => c.path)).sort()

describe('factory-navigation 新增子项', () => {
  const factoryPaths = pathsOf(FACTORY_DOMAINS)

  it('新增 /factory（首页，重定向目标）', () => {
    expect(factoryPaths).toContain('/factory')
  })

  it('保留既有 /factory/products 主入口（拆出 capability 后仍是主入口）', () => {
    expect(factoryPaths).toContain('/factory/products')
  })

  it('新增 /factory/stocking（待接入只读）', () => {
    expect(factoryPaths).toContain('/factory/stocking')
  })

  it('新增 /factory/fulfillment（待接入占位）', () => {
    expect(factoryPaths).toContain('/factory/fulfillment')
  })

  it('新增 /factory/capability（由 FactoryProducts 拆分）', () => {
    expect(factoryPaths).toContain('/factory/capability')
  })

  it('工厂树完整叶子集合（5 项，排序后）', () => {
    expect(factoryPaths).toEqual([
      '/factory', '/factory/capability', '/factory/fulfillment',
      '/factory/products', '/factory/stocking',
    ])
  })

  it('工厂树所有子项含 path/label/icon 且以 /factory 前缀', () => {
    for (const d of FACTORY_DOMAINS) {
      for (const c of d.children) {
        expect(typeof c.path).toBe('string')
        expect(typeof c.label).toBe('string')
        expect(typeof c.icon).toBe('string')
        expect(c.path.startsWith('/factory')).toBe(true)
      }
    }
  })
})

describe('console-navigation 新增子项（PC-03/04/05）', () => {
  const consolePaths = pathsOf(CONSOLE_DOMAINS)

  it('新增 /console/adapters（PC-03 Adapter 认证中心）', () => {
    expect(consolePaths).toContain('/console/adapters')
  })

  it('新增 /console/rules（PC-04 数据源与规则）', () => {
    expect(consolePaths).toContain('/console/rules')
  })

  it('新增 /console/ai-resources（PC-05 AI 资源与成本）', () => {
    expect(consolePaths).toContain('/console/ai-resources')
  })

  it('保留既有 4 项（overview/tenants/audit/maintenance）', () => {
    for (const p of ['/console/overview', '/console/tenants', '/console/audit', '/console/maintenance']) {
      expect(consolePaths).toContain(p)
    }
  })

  it('控制台树完整叶子集合（7 项，排序后）', () => {
    expect(consolePaths).toEqual([
      '/console/adapters', '/console/ai-resources', '/console/audit',
      '/console/maintenance', '/console/overview', '/console/rules', '/console/tenants',
    ])
  })
})
