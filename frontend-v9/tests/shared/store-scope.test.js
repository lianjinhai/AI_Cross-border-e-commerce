import { describe, expect, it } from 'vitest'
import { filterSalesShops, toShellShop, isAllShops } from '../../src/shared/storeScope'

/**
 * 店铺 DTO 适配（B3 实测缺陷回归）：
 * `GET /shops` 返回 {shop_name, role}，壳内读 {name, type}。
 * 不映射 → 下拉框显示纯 id；不兼容 role → 1688 货源店铺混进销售店铺列表。
 */
describe('toShellShop 店铺 DTO 适配', () => {
  it('shop_name → name，role → type', () => {
    const s = toShellShop({ id: 13, shop_name: 'S2验收店A', role: 'sales', platform: 'shopee' })
    expect(s.name).toBe('S2验收店A')
    expect(s.type).toBe('sales')
    expect(s.id).toBe(13)
    expect(s.platform).toBe('shopee')
  })

  it('已是壳层形状时不覆盖', () => {
    const s = toShellShop({ id: 1, name: '甲', type: 'sales', shop_name: '乙', role: 'source' })
    expect(s.name).toBe('甲')
    expect(s.type).toBe('sales')
  })

  it('空值不抛错', () => {
    expect(toShellShop(null)).toBeNull()
    expect(toShellShop({ id: 2 }).name).toBe('')
  })
})

describe('filterSalesShops 销售店铺过滤', () => {
  const shops = [
    { id: 1, shop_name: '演示 1688 店铺', role: 'source' },
    { id: 13, shop_name: 'S2验收店A', role: 'sales' },
    { id: 14, shop_name: 'S2验收店B', role: 'sales' },
  ].map(toShellShop)

  it('剔除货源店铺，保留销售店铺', () => {
    const names = filterSalesShops(shops).map((s) => s.name)
    expect(names).toEqual(['S2验收店A', 'S2验收店B'])
  })

  it('只给 role 也不漏判', () => {
    expect(filterSalesShops([{ id: 2, role: 'source' }])).toHaveLength(0)
  })

  it('全部店铺判定', () => {
    expect(isAllShops('')).toBe(true)
    expect(isAllShops(null)).toBe(true)
    expect(isAllShops(13)).toBe(false)
  })
})
