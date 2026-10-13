import { describe, expect, it } from 'vitest'
import {
  compareCandidates,
  missingForGrossProfit,
  costAndGrossAssumption,
  profitLabel,
} from '../../src/shared/matchingView'

/**
 * SU-04 货源匹配纯函数测试：
 * - 候选对比（price/moq/ship_days 优劣判定）
 * - 缺物流费/税费 → 禁当真利润（isAssumption）
 * - 不同币种缺汇率日 → fxUnknown
 */

describe('compareCandidates', () => {
  it('picks the cheaper candidate on price', () => {
    const rows = compareCandidates({ price: 10, moq: 10, ship_days: 7 }, { price: 12, moq: 10, ship_days: 7 })
    expect(rows.find((r) => r.field === 'price').winner).toBe('a')
  })

  it('reports unknown when both sides miss the field', () => {
    const rows = compareCandidates({}, {})
    expect(rows.every((r) => r.winner === 'unknown')).toBe(true)
  })

  it('picks the side that has the value when the other misses it', () => {
    const rows = compareCandidates({ moq: 5 }, { moq: null })
    expect(rows.find((r) => r.field === 'moq').winner).toBe('a')
  })
})

describe('missingForGrossProfit', () => {
  it('lists 缺物流费/缺税费 when absent', () => {
    const gaps = missingForGrossProfit({ logisticsCost: null, taxCost: null })
    expect(gaps).toContain('缺物流费')
    expect(gaps).toContain('缺税费')
  })

  it('flags missing fx day only when currencies differ', () => {
    expect(missingForGrossProfit({ currency: 'CNY', analysisCurrency: 'USD', fxDate: '' })).toContain('缺汇率日')
    expect(missingForGrossProfit({ currency: 'USD', analysisCurrency: 'USD', fxDate: '' })).not.toContain('缺汇率日')
  })

  it('no gaps when everything is present', () => {
    expect(missingForGrossProfit({ logisticsCost: 5, taxCost: 1, currency: 'USD', analysisCurrency: 'USD' }))
      .toEqual([])
  })
})

describe('costAndGrossAssumption', () => {
  it('computes total cost and profit when all inputs are known and same currency', () => {
    const view = costAndGrossAssumption({
      unitPrice: 10, qty: 2, logisticsCost: 5, taxCost: 1, sellPrice: 40, currency: 'USD', analysisCurrency: 'USD',
    })
    expect(view.totalCost).toBe(26)
    expect(view.profit).toBe(14)
    expect(view.isAssumption).toBe(false)
    expect(view.fxUnknown).toBe(false)
  })

  it('forbids real profit when logistics cost is missing (gaps + assumption)', () => {
    const view = costAndGrossAssumption({
      unitPrice: 10, logisticsCost: null, taxCost: 1, sellPrice: 40, currency: 'USD',
    })
    expect(view.profit).toBeNull()
    expect(view.isAssumption).toBe(true)
    expect(view.gaps).toContain('缺物流费')
  })

  it('marks assumption when cross-currency lacks fx date', () => {
    const view = costAndGrossAssumption({
      unitPrice: 10, logisticsCost: 5, taxCost: 1, sellPrice: 40,
      currency: 'CNY', analysisCurrency: 'USD', fxDate: '',
    })
    expect(view.fxUnknown).toBe(true)
    expect(view.isAssumption).toBe(true)
  })

  it('clears the fx assumption once the fx date is provided', () => {
    const view = costAndGrossAssumption({
      unitPrice: 10, logisticsCost: 5, taxCost: 1, sellPrice: 40,
      currency: 'CNY', analysisCurrency: 'USD', fxDate: '2025-01-01',
    })
    expect(view.fxUnknown).toBe(false)
    expect(view.isAssumption).toBe(false)
  })
})

describe('profitLabel', () => {
  it('renders "—" for null profit and the assumption suffix when flagged', () => {
    expect(profitLabel({ profit: null, isAssumption: false })).toBe('—')
    expect(profitLabel({ profit: 14, isAssumption: true })).toContain('假设')
    expect(profitLabel({ profit: 14, isAssumption: false })).toBe('14.00')
  })
})
