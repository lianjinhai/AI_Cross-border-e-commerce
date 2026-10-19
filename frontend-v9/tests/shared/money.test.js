import { describe, it, expect } from 'vitest'
import { renderMoney, isMissing, moneyTag, BASE_CURRENCY } from '../../src/shared/money'

/**
 * 金额口径（B3 修正）：本位币 CNY 不需要汇率，
 * 缺 fxDate 时只有外币才标「汇率未知」——给 CNY 标是假缺项。
 */
describe('renderMoney 汇率口径', () => {
  it('本位币 CNY 缺 fxDate 不标汇率未知', () => {
    expect(BASE_CURRENCY).toBe('CNY')
    const s = renderMoney({ value: 5, currency: 'CNY' })
    expect(s).toBe('5.00 CNY')
    expect(s).not.toContain('汇率')
  })

  it('外币缺 fxDate 仍标汇率未知（不得静默换算）', () => {
    expect(renderMoney({ value: 3, currency: 'USD' })).toBe('3.00 USD · 汇率未知')
  })

  it('有 fxDate 时显式标注基准日', () => {
    expect(renderMoney({ value: 5, currency: 'CNY', fxDate: '2026-10-01' }))
      .toBe('5.00 CNY · 汇率 2026-10-01')
  })

  it('小写币种同样按本位币处理', () => {
    expect(renderMoney({ value: 5, currency: 'cny' })).toBe('5.00 cny')
  })

  it('缺值不渲染 0', () => {
    expect(renderMoney({ value: null, currency: 'CNY' })).toBe('—')
    expect(renderMoney({})).toBe('—')
    expect(isMissing('')).toBe(true)
    expect(isMissing(0)).toBe(false)
    expect(moneyTag(true, true)).toBe('估算')
  })
})
