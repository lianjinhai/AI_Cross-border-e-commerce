/**
 * orderView 纯函数单测（B1 批次 P0 正确性）：
 *  - formatOrderMoney：币种必须真实，绝不静默回退 "$"，缺失金额不得 coerce 成 0.00。
 *  - orderShopLabel：店铺标签回退链 shop_name -> #shop_id -> "—"。
 */
import { describe, it, expect } from 'vitest'
import { formatOrderMoney, orderShopLabel } from '../src/shared/orderView'

describe('formatOrderMoney', () => {
  it('CNY 金额带 CNY 前缀并千分位', () => {
    expect(formatOrderMoney({ currency: 'CNY', amount: 1280 })).toBe('CNY 1,280.00')
  })

  it('USD 金额带 USD 前缀', () => {
    expect(formatOrderMoney({ currency: 'usd', amount: 12.5 })).toBe('USD 12.50')
  })

  it('金额缺失币种时返回 "—"，且绝不是 "$0.00"', () => {
    const r1 = formatOrderMoney({ amount: 1280 })
    const r2 = formatOrderMoney({ currency: '', amount: 1280 })
    const r3 = formatOrderMoney({ currency: null, amount: 1280 })
    for (const r of [r1, r2, r3]) {
      expect(r).toBe('—')
      expect(r).not.toBe('$0.00')
      expect(r).not.toContain('$')
    }
  })

  it('金额为 0 且币种有效时仍渲染 "CNY 0.00"（真实零值不被当作缺失）', () => {
    expect(formatOrderMoney({ currency: 'CNY', amount: 0 })).toBe('CNY 0.00')
  })

  it('金额缺失（null/undefined/空串/NaN）时不 coerce 成 0.00', () => {
    expect(formatOrderMoney({ currency: 'CNY', amount: null })).toBe('—')
    expect(formatOrderMoney({ currency: 'CNY', amount: undefined })).toBe('—')
    expect(formatOrderMoney({ currency: 'CNY', amount: '' })).toBe('—')
    expect(formatOrderMoney({ currency: 'CNY', amount: NaN })).toBe('—')
  })

  it('字符串数值按数字解析格式化', () => {
    expect(formatOrderMoney({ currency: 'USD', amount: '99.9' })).toBe('USD 99.90')
    expect(formatOrderMoney({ currency: 'CNY', amount: '0' })).toBe('CNY 0.00')
  })
})

describe('orderShopLabel', () => {
  it('优先用 shop_name', () => {
    expect(orderShopLabel({ shop_name: '深圳仓', shop_id: 7 })).toBe('深圳仓')
  })

  it('shop_name 缺失时回退到 #shop_id', () => {
    expect(orderShopLabel({ shop_id: 7 })).toBe('#7')
    expect(orderShopLabel({ shop_name: '', shop_id: 7 })).toBe('#7')
  })

  it('shop_name 与 shop_id 皆缺失时回退到 "—"', () => {
    expect(orderShopLabel({})).toBe('—')
    expect(orderShopLabel({ shop_name: '', shop_id: null })).toBe('—')
  })
})
