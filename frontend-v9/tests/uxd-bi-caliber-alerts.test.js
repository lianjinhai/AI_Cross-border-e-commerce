import { describe, expect, it } from 'vitest'
import {
  BI_METRIC_CALIBERS, ESTIMATED_PROFIT_NOTE, SETTLED_CALIBER_NOTE,
  formatMetricValue, metricCardList,
} from '../src/shared/biCaliber'
import { ALERT_TARGETS, alertTarget } from '../src/features/optimization/alertTargets'

/**
 * UX-D 口径与深链纯函数锁定：
 * - BI 五个易混口径（GMV/净收入/贡献利润/结算到账/估算利润）说明必须存在且互斥；
 * - 缺失指标不伪造数值卡；
 * - 告警 9 条规则全部有「去处理」深链。
 */
describe('bi caliber dictionary', () => {
  it('documents the five easily-confused calibers', () => {
    const keys = BI_METRIC_CALIBERS.map((m) => m.key)
    expect(keys).toEqual(expect.arrayContaining(['gmv', 'net_revenue', 'contribution_profit']))
    expect(SETTLED_CALIBER_NOTE).toContain('结算到账')
    expect(SETTLED_CALIBER_NOTE).toContain('净收入')
    expect(ESTIMATED_PROFIT_NOTE).toContain('估算利润')
    expect(ESTIMATED_PROFIT_NOTE).toContain('贡献利润')
  })

  it('only renders metrics actually returned by backend (no fabricated zeros)', () => {
    const cards = metricCardList({ gmv: 120, contribution_profit: null, orders: 5 })
    const keys = cards.map((c) => c.key)
    expect(keys).toContain('gmv')
    expect(keys).not.toContain('contribution_profit') // null 值不渲染
    expect(keys).not.toContain('net_revenue') // 未返回的键不渲染
    expect(cards.find((c) => c.key === 'gmv').display).toBe('$120')
  })

  it('formats money keys with $ and passes others through', () => {
    expect(formatMetricValue('gmv', 1.5)).toBe('$1.5')
    expect(formatMetricValue('refund_rate', 0.12)).toBe('0.12')
    expect(formatMetricValue('gmv', null)).toBe('—')
  })

  it('keeps caliber and distinction text on every metric', () => {
    for (const metric of BI_METRIC_CALIBERS) {
      expect(metric.caliber.length).toBeGreaterThan(8)
      expect(metric.distinction.length).toBeGreaterThan(8)
    }
  })
})

describe('alert deep-link targets', () => {
  it('maps all nine backend default rules to the correct domain page', () => {
    expect(Object.keys(ALERT_TARGETS)).toHaveLength(9)
    expect(alertTarget('stockout_risk')).toEqual({ path: '/app/supply/purchases', label: '去生成采购单' })
    expect(alertTarget('price_below_floor').path).toBe('/app/pricing')
    expect(alertTarget('fx_volatility').path).toBe('/app/analytics/finance')
    expect(alertTarget('shipping_degraded').path).toBe('/app/orders')
    expect(alertTarget('refund_spike').path).toBe('/app/refunds')
    expect(alertTarget('listing_stale').path).toBe('/app/listings')
    expect(alertTarget('ads_burning').path).toBe('/app/ads')
    expect(alertTarget('supplier_delay').path).toBe('/app/supply/suppliers')
    expect(alertTarget('policy_changed').path).toBe('/app/listings')
  })

  it('returns null for unknown rule keys (no guessed deep link)', () => {
    expect(alertTarget('unknown_rule')).toBeNull()
    expect(alertTarget(undefined)).toBeNull()
  })
})
