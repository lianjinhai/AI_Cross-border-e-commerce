import { describe, expect, it } from 'vitest'
import {
  DQ_GAPS,
  countDataQualityGaps,
  dataQualityRows,
  forecastCommercialGate,
  forecastSectionState,
} from '../../src/shared/forecastView'

/**
 * BI-02 预测与数据质量纯函数测试：
 * - 数据质量缺项统计（缺汇率/缺费用/缺成本/来源混合）
 * - 商用门槛（预测端点未核 §7#10 → 仅参考）
 * - 11 态映射（NOT_CONFIGURED / PARTIAL_DATA / ready）
 */

const ORDERS = [
  { id: 1, fx: null, fees: [], lines: [{ cost: 3 }], source: 'real' },
  { id: 2, fx: '2025-01-01', fees: [{ fee: 2 }], lines: [{ cost: null }], source: 'demo' },
  { id: 3, fx: '2025-01-02', fees: [{ fee: 1 }], lines: [{ cost: 4 }], source: 'real' },
]

describe('DQ_GAPS', () => {
  it('covers the 4 canonical gap categories in fixed order', () => {
    expect(DQ_GAPS.map((g) => g.key)).toEqual(['fx_missing', 'fee_missing', 'cost_missing', 'source_mixed'])
  })
})

describe('countDataQualityGaps', () => {
  it('counts per-order gaps: fx/fee/cost', () => {
    const counts = countDataQualityGaps(ORDERS)
    expect(counts.fx_missing).toBe(1)      // 订单 1 缺 fx
    expect(counts.fee_missing).toBe(1)     // 订单 1 费用为空
    expect(counts.cost_missing).toBe(1)     // 订单 2 行缺 cost
  })

  it('flags source_mixed globally when 2+ sources exist', () => {
    const counts = countDataQualityGaps(ORDERS)
    expect(counts.source_mixed).toBe(3)    // 命中时为列表长度（全局判定，不逐单累加）
  })

  it('no mixed-source flag when all orders share one source', () => {
    const single = [{ fx: null, fees: [], lines: [{ cost: 1 }], source: 'real' }]
    expect(countDataQualityGaps(single).source_mixed).toBe(0)
  })

  it('handles empty/null input without throwing', () => {
    const counts = countDataQualityGaps(null)
    expect(Object.values(counts)).toEqual([0, 0, 0, 0])
  })
})

describe('dataQualityRows', () => {
  it('joins gap definitions with counts for rendering', () => {
    const rows = dataQualityRows(ORDERS)
    expect(rows).toHaveLength(4)
    expect(rows[0]).toMatchObject({ key: 'fx_missing', count: 1 })
  })
})

describe('forecastCommercialGate', () => {
  it('is reference-only while the model endpoint is unverified (§7#10)', () => {
    expect(forecastCommercialGate({}).label).toBe('仅参考')
    expect(forecastCommercialGate({ modelEndpointAvailable: false }).isCommercialReady).toBe(false)
  })

  it('becomes commercial only when the endpoint is verified', () => {
    expect(forecastCommercialGate({ modelEndpointAvailable: true }).label).toBe('商用')
  })
})

describe('forecastSectionState', () => {
  it('NOT_CONFIGURED while the forecast endpoint is unverified', () => {
    expect(forecastSectionState({})).toBe('NOT_CONFIGURED')
  })

  it('PARTIAL_DATA when ready but data-quality gaps exist', () => {
    expect(forecastSectionState({ modelEndpointAvailable: true, orders: ORDERS })).toBe('PARTIAL_DATA')
  })

  it('ready when verified and no gaps', () => {
    const clean = [{ fx: '2025-01-01', fees: [{ fee: 1 }], lines: [{ cost: 3 }], source: 'real' }]
    expect(forecastSectionState({ modelEndpointAvailable: true, orders: clean })).toBe('ready')
  })
})
