import { describe, expect, it } from 'vitest'
import {
  CATALOG_COLUMNS,
  CAPABILITY_COLUMNS,
  ALL_COLUMNS,
  columnGroup,
  splitCatalogRow,
  capabilityRequiresWrite,
} from '../src/shared/factoryCatalogSplit'

/**
 * 工厂目录拆分纯函数回归（蓝图 R1 包 3 · FP-02 catalog + FP-03 capability）。
 *
 * 由既有 FactoryProducts（/factory/products）按字段切分为商品主档（catalog）
 * 与供货能力（capability）两视图；主入口保留完整编辑，capability 只读。
 */
describe('列目录切分', () => {
  it('catalog 列 = 商品主档（不含报价/MOQ/币种/库存时效）', () => {
    expect(CATALOG_COLUMNS.map((c) => c.key)).toEqual(['factory_sku', 'title', 'category', 'status'])
  })

  it('capability 列 = 报价/MOQ/币种/库存时效', () => {
    expect(CAPABILITY_COLUMNS.map((c) => c.key)).toEqual([
      'currency', 'unit_price', 'moq', 'lead_days', 'monthly_capacity', 'available_qty',
    ])
  })

  it('全列 = catalog ∪ capability，无重复', () => {
    expect(ALL_COLUMNS).toHaveLength(CATALOG_COLUMNS.length + CAPABILITY_COLUMNS.length)
    expect(new Set(ALL_COLUMNS.map((c) => c.key)).size).toBe(ALL_COLUMNS.length)
  })
})

describe('columnGroup — 列归属判定', () => {
  it('factory_sku/status → catalog；unit_price/moq → capability', () => {
    expect(columnGroup('factory_sku')).toBe('catalog')
    expect(columnGroup('status')).toBe('catalog')
    expect(columnGroup('unit_price')).toBe('capability')
    expect(columnGroup('moq')).toBe('capability')
  })

  it('未知列 → null（不进任一视图，避免字段重复实现）', () => {
    expect(columnGroup('nonexistent')).toBeNull()
  })
})

describe('splitCatalogRow — 行拆分', () => {
  it('按列归属切出 catalog / capability 两个子行，各自保留 id', () => {
    const row = {
      id: 7, factory_sku: 'SKU-1', title: '产品A', category: '服装', status: 'active',
      currency: 'CNY', unit_price: 9.9, moq: 100, lead_days: 7, monthly_capacity: 500, available_qty: 200,
    }
    const { catalog, capability } = splitCatalogRow(row)
    expect(catalog.id).toBe(7)
    expect(catalog.factory_sku).toBe('SKU-1')
    expect(catalog.title).toBe('产品A')
    expect(catalog.status).toBe('active')
    // catalog 不应混入供货能力字段
    expect(catalog).not.toHaveProperty('unit_price')
    expect(catalog).not.toHaveProperty('moq')

    expect(capability.id).toBe(7)
    expect(capability.currency).toBe('CNY')
    expect(capability.unit_price).toBe(9.9)
    expect(capability.moq).toBe(100)
    expect(capability.lead_days).toBe(7)
    expect(capability).not.toHaveProperty('title')
    expect(capability).not.toHaveProperty('factory_sku')
  })

  it('空行 → 两个空对象（仅 id）', () => {
    const { catalog, capability } = splitCatalogRow({})
    expect(Object.keys(catalog)).toEqual([])
    expect(Object.keys(capability)).toEqual([])
  })

  it('未知字段丢弃（不落入任一视图）', () => {
    const { catalog, capability } = splitCatalogRow({ factory_sku: 'X', mystery_field: 1, id: 1 })
    expect(catalog).not.toHaveProperty('mystery_field')
    expect(capability).not.toHaveProperty('mystery_field')
  })
})

describe('capabilityRequiresWrite', () => {
  it('供货能力页需 supply:write 写权限（报价/MOQ/币种可维护）', () => {
    expect(capabilityRequiresWrite()).toBe(true)
  })
})
