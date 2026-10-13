import { describe, expect, it } from 'vitest'
import {
  SOURCING_TABS,
  splitSourcingTab,
  filterSourcing,
  flag1688Gap,
} from '../../src/shared/sourcingView'

/**
 * SU-01 货源发现纯函数测试：
 * - 三个来源 Tab 分列（1688/工厂/手动）
 * - 1688 未接标记（§7#7）
 * - 筛选（SKU/成本币种/MOQ/交期）
 */

describe('SOURCING_TABS', () => {
  it('defines 3 tabs in fixed order with 1688 marked apiGap', () => {
    expect(SOURCING_TABS).toHaveLength(3)
    expect(SOURCING_TABS.map((t) => t.key)).toEqual(['1688', 'factory', 'manual'])
    expect(SOURCING_TABS[0].apiGap).toBe(true)
    expect(SOURCING_TABS[1].apiGap).toBe(false)
    expect(SOURCING_TABS[2].apiGap).toBe(false)
  })

  it('1688 hint is user-visible copy not "Sales"', () => {
    const hint = SOURCING_TABS[0].hint
    expect(hint).toContain('1688 未接入')
    expect(hint).toContain('手动添加')
  })
})

describe('splitSourcingTab', () => {
  const items = [
    { id: 1, source: 'factory', name: 'F1' },
    { id: 2, source: 'manual', name: 'M1' },
    { id: 3, name: 'Legacy' }, // 缺 source → 归 manual
  ]

  it('factory tab returns only factory items', () => {
    const view = splitSourcingTab(items, 'factory')
    expect(view.apiGap).toBe(false)
    expect(view.items.map((i) => i.id)).toEqual([1])
  })

  it('manual tab returns manual + legacy items (source defaults to manual)', () => {
    const view = splitSourcingTab(items, 'manual')
    expect(view.apiGap).toBe(false)
    expect(view.items.map((i) => i.id).sort()).toEqual([2, 3])
  })

  it('1688 tab is always empty with apiGap flag (no fake data)', () => {
    const view = splitSourcingTab(items, '1688')
    expect(view.apiGap).toBe(true)
    expect(view.items).toEqual([])
    expect(view.hint).toContain('1688 未接入')
  })

  it('unknown tab falls back to factory without apiGap', () => {
    const view = splitSourcingTab(items, 'weird-key')
    expect(view.apiGap).toBe(false)
  })
})

describe('filterSourcing', () => {
  const items = [
    { id: 1, skus: ['A-01', 'B-02'], cost_currency: 'CNY', moq: 10, ship_days: 5 },
    { id: 2, skus: ['B-01'], cost_currency: 'USD', moq: 100, ship_days: 30 },
    { id: 3, skus: [], cost_currency: 'CNY', moq: 1000, ship_days: 7 },
  ]

  it('filters by SKU substring (case-insensitive)', () => {
    expect(filterSourcing(items, { sku: 'a-' }).map((i) => i.id)).toEqual([1])
    expect(filterSourcing(items, { sku: 'b-' }).map((i) => i.id)).toEqual([1, 2])
  })

  it('filters by cost currency exact match', () => {
    expect(filterSourcing(items, { costCurrency: 'USD' }).map((i) => i.id)).toEqual([2])
  })

  it('filters by MOQ upper bound (exclusive = not greater-than)', () => {
    expect(filterSourcing(items, { moqMax: 100 }).map((i) => i.id)).toEqual([1, 2])
    expect(filterSourcing(items, { moqMax: 50 }).map((i) => i.id)).toEqual([1])
  })

  it('filters by ship days upper bound', () => {
    expect(filterSourcing(items, { shipDaysMax: 10 }).map((i) => i.id)).toEqual([1, 3])
  })

  it('composes all filters', () => {
    expect(filterSourcing(items, { costCurrency: 'CNY', moqMax: 100, shipDaysMax: 30 }).map((i) => i.id))
      .toEqual([1])
  })

  it('empty/null inputs return empty array, no throw', () => {
    expect(filterSourcing(null, {})).toEqual([])
    expect(filterSourcing([], { sku: 'x' })).toEqual([])
  })
})

describe('flag1688Gap', () => {
  it('returns fixed apiGap marker for user-visible hint', () => {
    const flag = flag1688Gap()
    expect(flag.apiGap).toBe(true)
    expect(flag.hint).toContain('1688 未接入')
  })
})
