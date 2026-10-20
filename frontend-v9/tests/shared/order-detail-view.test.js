import { describe, it, expect } from 'vitest'
import {
  detailWarnings, feeLabel, feeTotalsText, purchaseTotalsText, refundTotalText,
} from '../../src/shared/orderDetailView'

const detail = () => ({
  order: { id: 1, external_no: 'SO1', currency: 'USD', amount: 120, cost: 70,
           profit: 50, shop_id: 9, product_id: 3, source: 'import' },
  fees: { items: [], total_by_currency: { USD: 20.5 } },
  purchases: { items: [{ id: 1, po_no: 'PO1' }], total_by_currency: { CNY: 90 } },
  refunds: [{ id: 1, amount: 30 }, { id: 2, amount: 10 }],
  fulfillment: { tracking_no: 'SF1', tracking_available: false,
                 note: '物流轨迹未接入：仅回单号，不展示轨迹或到达时间' },
  totals: { currency: 'USD', mixed_currency: true },
})

describe('费用与采购汇总', () => {
  it('费用按币种汇总，不混币种', () => {
    expect(feeTotalsText(detail())).toBe('USD 20.50')
    expect(feeTotalsText({ fees: { total_by_currency: {} } })).toBe('—')
    expect(feeTotalsText(null)).toBe('—')
  })

  it('采购汇总保留 CNY 口径（不与订单金额合并）', () => {
    expect(purchaseTotalsText(detail())).toBe('CNY 90.00')
    expect(purchaseTotalsText({})).toBe('—')
  })

  it('未知费用类型回显原值，不臆造中文名', () => {
    expect(feeLabel('commission')).toBe('平台佣金')
    expect(feeLabel('mystery_fee')).toBe('mystery_fee')
    expect(feeLabel('')).toBe('未分类费用')
  })

  it('退款合计按订单币种展示原始金额', () => {
    expect(refundTotalText(detail())).toBe('USD 40.00')
    expect(refundTotalText({ refunds: [] })).toBe('—')
  })
})

describe('口径与缺口提示', () => {
  it('混合币种必须提示不可相加', () => {
    const texts = detailWarnings(detail()).map((w) => w.text)
    expect(texts.some((t) => t.includes('不可相加'))).toBe(true)
  })

  it('轨迹未接入用服务端原因，不编造到达时间', () => {
    const warning = detailWarnings(detail()).find((w) => w.text.includes('轨迹'))
    expect(warning.level).toBe('info')
    expect(warning.text).toContain('未接入')
  })

  it('没有关联采购时明确「不代表未采购」', () => {
    const d = detail()
    d.purchases = { items: [], total_by_currency: {} }
    const texts = detailWarnings(d).map((w) => w.text)
    expect(texts.some((t) => t.includes('不代表未采购'))).toBe(true)
  })

  it('未绑定店铺/商品时给出警告', () => {
    const d = detail()
    d.order.shop_id = null
    d.order.product_id = null
    const levels = detailWarnings(d).filter((w) => w.level === 'warning').map((w) => w.text)
    expect(levels.some((t) => t.includes('未绑定店铺'))).toBe(true)
    expect(levels.some((t) => t.includes('未绑定商品'))).toBe(true)
  })

  it('空详情返回空提示', () => {
    expect(detailWarnings(null)).toEqual([])
  })
})
