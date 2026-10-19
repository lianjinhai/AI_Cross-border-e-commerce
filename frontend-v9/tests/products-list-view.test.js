import { describe, expect, it } from 'vitest'
import { stageFromSignals, primaryAction } from '../src/shared/productsListView'

/**
 * B3 商品池阶段派生（衍生设计，无原型底图）：
 * - signals 缺失 → UNKNOWN / 「—」
 * - 阶梯：未接货源 → 货源就绪 → 渠道准备中
 * - 主动作路径随阶段变化
 */

describe('stageFromSignals', () => {
  it('signals 缺失渲染 UNKNOWN / 「—」', () => {
    expect(stageFromSignals(null)).toEqual({ key: 'UNKNOWN', label: '—', tone: 'neutral' })
    expect(stageFromSignals(undefined)).toEqual({ key: 'UNKNOWN', label: '—', tone: 'neutral' })
    expect(stageFromSignals({})).toEqual({ key: 'UNKNOWN', label: '—', tone: 'neutral' })
  })

  it('offers_count=0 → 未接货源（琥珀）', () => {
    const s = stageFromSignals({ offers_count: 0, channels_count: 0 })
    expect(s.key).toBe('NO_SOURCE')
    expect(s.label).toBe('未接货源')
    expect(s.tone).toBe('warning')
  })

  it('offers>0 且 channels=0 → 货源就绪', () => {
    const s = stageFromSignals({ offers_count: 3, channels_count: 0 })
    expect(s.key).toBe('SOURCE_READY')
    expect(s.label).toBe('货源就绪')
    expect(s.tone).toBe('success')
  })

  it('channels>0 → 渠道准备中', () => {
    const s = stageFromSignals({ offers_count: 3, channels_count: 2 })
    expect(s.key).toBe('CHANNEL_PREPARING')
    expect(s.label).toBe('渠道准备中')
    expect(s.tone).toBe('info')
  })
})

describe('primaryAction', () => {
  it('未接货源 → 去比选 → /app/supply/matching?product_id={id}', () => {
    const a = primaryAction({ offers_count: 0, channels_count: 0 }, 42)
    expect(a.label).toBe('去比选')
    expect(a.path).toBe('/app/supply/matching?product_id=42')
  })

  it('货源就绪 → 查看经营中心 → /app/products/{id}', () => {
    const a = primaryAction({ offers_count: 2, channels_count: 0 }, 7)
    expect(a.label).toBe('查看经营中心')
    expect(a.path).toBe('/app/products/7')
  })

  it('渠道准备中 → 查看经营中心', () => {
    const a = primaryAction({ offers_count: 2, channels_count: 1 }, 9)
    expect(a.label).toBe('查看经营中心')
    expect(a.path).toBe('/app/products/9')
  })

  it('signals 缺失 → 不编造阶段 → 默认走查看经营中心（避免指向不存在的比选）', () => {
    const a = primaryAction(null, 5)
    expect(a.label).toBe('查看经营中心')
    expect(a.path).toBe('/app/products/5')
  })
})
