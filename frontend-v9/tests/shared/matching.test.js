import { describe, expect, it } from 'vitest'
import {
  compareCandidates,
  missingForGrossProfit,
  costAndGrossAssumption,
  costingResultView,
  profitLabel,
  normalizeOffer,
  offerId,
  sourceVerificationTags,
  buildInquiryCopy,
  lowestInStockOffer,
  stockLabel,
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

describe('offerId', () => {
  it('reads nested/flat id forms, falls back to null', () => {
    expect(offerId({ id: 7 })).toBe(7)
    expect(offerId({ offer_id: 11 })).toBe(11)
    expect(offerId({ supplier: { id: 3 } })).toBeNull()
    expect(offerId({})).toBeNull()
    expect(offerId({ id: '' })).toBeNull()
  })
})

describe('normalizeOffer (防御式：新嵌套 + 旧扁平)', () => {
  it('解包新契约嵌套 supplier', () => {
    const o = normalizeOffer({
      id: 5, price: 12.5, currency: 'USD', moq: 50, ship_days: 14, in_stock: 200,
      valid_until: '2026-12-31', source_kind: 'official', verification_status: 'verified',
      supplier: { id: 9, name: 'Acme', region: 'CN', supplier_type: 'factory', rating: 4.5 },
      is_selected: true,
    })
    expect(o.id).toBe(5)
    expect(o.supplier.name).toBe('Acme')
    expect(o.supplier.supplier_type).toBe('factory')
    expect(o.is_selected).toBe(true)
  })

  it('回退到旧扁平字段（无 supplier 对象）', () => {
    const o = normalizeOffer({ supplier_name: 'Old', price: 8, currency: 'CNY', moq: 10, ship_days: 7 })
    expect(o.supplier.name).toBe('Old')
    expect(o.currency).toBe('CNY')
    expect(o.is_selected).toBe(false)
  })

  it('缺失字段不臆造（留空）', () => {
    const o = normalizeOffer({})
    expect(o.price).toBeNull()
    expect(o.valid_until).toBe('')
    expect(o.source_kind).toBe('')
    expect(o.supplier.name).toBe('')
  })
})

describe('sourceVerificationTags (诚实边界)', () => {
  it('未核验/爬取 → 待核实（琥珀）', () => {
    expect(sourceVerificationTags('official', 'unverified').verification).toEqual({ label: '待核实', tone: 'warning' })
    expect(sourceVerificationTags('scraped', 'scraped').verification).toEqual({ label: '待核实', tone: 'warning' })
    expect(sourceVerificationTags('', '').verification).toEqual({ label: '待核实', tone: 'warning' })
  })

  it('已核验 → success（非琥珀）', () => {
    expect(sourceVerificationTags('official', 'verified').verification).toEqual({ label: '已核验', tone: 'success' })
  })

  it('来源类型映射', () => {
    expect(sourceVerificationTags('official', 'verified').source).toEqual({ label: '官方', tone: 'success' })
    expect(sourceVerificationTags('api', 'verified').source).toEqual({ label: 'API', tone: 'info' })
    expect(sourceVerificationTags('manual', 'verified').source).toEqual({ label: '人工', tone: 'warning' })
    expect(sourceVerificationTags('scraped', 'verified').source).toEqual({ label: '爬取', tone: 'warning' })
    expect(sourceVerificationTags('weird', 'verified').source).toEqual({ label: 'weird', tone: 'neutral' })
  })
})

describe('buildInquiryCopy (复制，非发送)', () => {
  it('汇总商品 + 经营条件 + 要求 + 意向报价，含不代发送说明', () => {
    const text = buildInquiryCopy({
      product: { id: 3, title: 'LED Strip' },
      profile: { targetMarket: 'US', budget: '¥5000', risk: '中' },
      requirements: { targetSellPrice: 19.9, marketCurrency: 'USD' },
      offer: normalizeOffer({
        price: 8, currency: 'USD', moq: 50, ship_days: 14, valid_until: '2026-12-31',
        supplier: { name: 'Acme' },
      }),
    })
    expect(text).toContain('LED Strip')
    expect(text).toContain('目标市场=US')
    expect(text).toContain('目标售价=19.9 USD')
    expect(text).toContain('Acme')
    expect(text).toContain('不代发送')
  })

  it('未选定报价时如实写"未选定"，不臆造', () => {
    const text = buildInquiryCopy({ product: { id: 1, title: 'X' }, offer: null })
    expect(text).toContain('未选定（成本试算将自动取最低在库报价）')
  })

  it('缺经营条件/要求写"待补"', () => {
    const text = buildInquiryCopy({ product: {}, profile: {}, requirements: {}, offer: null })
    expect(text).toContain('经营条件（会话内参考，仅本页）：待补')
    expect(text).toContain('采购要求：待补')
  })
})

describe('lowestInStockOffer', () => {
  it('取最低在库报价', () => {
    const offers = [
      normalizeOffer({ price: 10, in_stock: 5 }),
      normalizeOffer({ price: 7, in_stock: 3 }),
      normalizeOffer({ price: 20, in_stock: 0 }),
    ]
    const best = lowestInStockOffer(offers)
    expect(best.price).toBe(7)
  })

  it('无在库报价返回 null', () => {
    expect(lowestInStockOffer([normalizeOffer({ price: 10, in_stock: 0 })])).toBeNull()
    expect(lowestInStockOffer([])).toBeNull()
  })
})

describe('costingResultView（后端 costing 口径，B3 任务三）', () => {
  const CALC = {
    offer_id: 7, purchase_cost: 71.0, logistics_cost: 12.0, cost_total_cny: 95.3,
    price: 19.99, profit: 6.6, margin: 0.33, currency: 'USD', fx: 7.12,
    hs_code: '9405', destination_country: 'US', landed_cost_applied: true,
    warehouse_id: 3,
  }

  it('选定与引擎一致 → isUserSelected，无回退警告', () => {
    const v = costingResultView(CALC, 7)
    expect(v.offerId).toBe(7)
    expect(v.isUserSelected).toBe(true)
    expect(v.selectedIgnored).toBe(false)
    expect(v.basisNote).toContain('用户选定')
    expect(v.gaps).toEqual([])
    expect(v.isAssumption).toBe(false)
    expect(v.totalCostCny).toBe(95.3)
  })

  it('选定与引擎不一致 → 显式回退标注（绝不允许无提示回退）', () => {
    const v = costingResultView(CALC, 9)
    expect(v.isUserSelected).toBe(false)
    expect(v.selectedIgnored).toBe(true)
    expect(v.basisNote).toContain('已选定报价未被采用')
  })

  it('未选定 → 自动最低在库价；无 offer_id 响应 → null（待核算）', () => {
    expect(costingResultView(CALC, null).basisNote).toBe('自动最低在库价')
    expect(costingResultView({ ...CALC, offer_id: null }, null)).toBeNull()
    expect(costingResultView(null, null)).toBeNull()
  })

  it('缺项诚实入 gaps：未提供目的国/无 HS/未绑仓 → isAssumption', () => {
    const v = costingResultView({ ...CALC, landed_cost_applied: false, hs_code: '', warehouse_id: null }, 7)
    expect(v.gaps).toHaveLength(3)
    expect(v.isAssumption).toBe(true)
  })
})

describe('compareCandidates 币种口径（§5.13）', () => {
  it('不同币种不可直接比金额', () => {
    const rows = compareCandidates(
      normalizeOffer({ price: 20, currency: 'USD' }),
      normalizeOffer({ price: 100, currency: 'CNY' }),
    )
    const price = rows.find((r) => r.field === 'price')
    expect(price.winner).toBe('unknown')
    expect(price.detail).toContain('币种不同')
  })

  it('同币种正常比价；缺币种按原逻辑比较', () => {
    const same = compareCandidates(
      normalizeOffer({ price: 20, currency: 'CNY' }),
      normalizeOffer({ price: 100, currency: 'CNY' }),
    ).find((r) => r.field === 'price')
    expect(same.winner).toBe('a')

    const noCur = compareCandidates(
      normalizeOffer({ price: 20 }),
      normalizeOffer({ price: 100 }),
    ).find((r) => r.field === 'price')
    expect(noCur.winner).toBe('a')
  })
})

describe('costingResultView 状态与口径', () => {
  it('offer_state 由后端决定并映射为可读说明', () => {
    const v = costingResultView({
      offer_id: 7, offer_state: 'EXPIRED', offer_limits: ['报价已过期：可保留偏好与试算，不得据此对外报价或采购'],
      purchase_cost: 10, cost_total_cny: 30, currency: 'USD', margin: 0.2,
    }, 7)
    expect(v.offerState).toBe('EXPIRED')
    expect(v.isUserSelected).toBe(true)
    expect(v.basisNote).toContain('过期')
    expect(v.offerLimits.length).toBe(1)
  })

  it('无 shop_id 视为通用试算；有 shop_id 则非通用', () => {
    expect(costingResultView({ offer_id: 1 }).isGenericEstimate).toBe(true)
    expect(costingResultView({ offer_id: 1, shop_id: 9 }).isGenericEstimate).toBe(false)
  })

  it('选定失效（MISSING）明确提示回退', () => {
    const v = costingResultView({ offer_id: 3, offer_state: 'MISSING' }, 7)
    expect(v.selectedIgnored).toBe(true)
    expect(v.basisNote).toContain('自动最低在库价')
  })
})

describe('stockLabel 库存文案', () => {
  it('布尔事实翻译为在库/缺货，未知不臆造', () => {
    expect(stockLabel(true)).toBe('在库')
    expect(stockLabel(false)).toBe('缺货')
    expect(stockLabel(null)).toBe('—')
    expect(stockLabel(undefined)).toBe('—')
  })
})
