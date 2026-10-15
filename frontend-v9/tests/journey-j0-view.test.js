import { describe, expect, it } from 'vitest'

import {
  J0_JOURNEY_KEY, J0_STEPS, J0_STEP_KEYS, MISSING_PLACEHOLDER,
  buildJourneyQuery, isJourneyActive, stepFromPath, stepIndex,
  deriveNextStep, derivePrevStep, identifyStartingPoint,
  credibilityTag, credibilityLabel, honestValue, stepCompletion,
} from '../src/shared/journeyJ0View'

describe('J0_STEPS 结构完整性', () => {
  it('恰好 5 步且 key 唯一有序', () => {
    expect(J0_STEPS).toHaveLength(5)
    expect(J0_STEP_KEYS).toEqual(['discovery', 'sourcing', 'cost', 'channel', 'prepare'])
  })

  it('journey key 固定为 j0', () => {
    expect(J0_JOURNEY_KEY).toBe('j0')
  })
})

describe('stepFromPath（当前步识别，含 also 前缀）', () => {
  it('精确命中 route', () => {
    expect(stepFromPath('/app/market/discovery')?.key).toBe('discovery')
    expect(stepFromPath('/app/analytics/landed-cost')?.key).toBe('cost')
    expect(stepFromPath('/app/market/candidates')?.key).toBe('prepare')
  })

  it('也接受不带前导斜杠的 path', () => {
    expect(stepFromPath('app/supply/sourcing')?.key).toBe('sourcing')
  })

  it('also 前缀命中（详情/子页归属主步）', () => {
    expect(stepFromPath('/app/market/opportunity/123')?.key).toBe('discovery')
    expect(stepFromPath('/app/supply/matching')?.key).toBe('sourcing')
    expect(stepFromPath('/app/channels/shops')?.key).toBe('channel')
    expect(stepFromPath('/app/pricing')?.key).toBe('cost')
  })

  it('不在链路返回 null', () => {
    expect(stepFromPath('/app')).toBeNull()
    expect(stepFromPath('/onboarding')).toBeNull()
    expect(stepFromPath('')).toBeNull()
  })
})

describe('buildJourneyQuery / isJourneyActive（上下文透传）', () => {
  it('始终带 journey=j0', () => {
    expect(buildJourneyQuery({})).toEqual({ journey: 'j0' })
  })

  it('productId 有值时才透传，空值/缺省不传空串', () => {
    expect(buildJourneyQuery({ productId: 12 })).toEqual({ journey: 'j0', productId: '12' })
    expect(buildJourneyQuery({ productId: '' })).toEqual({ journey: 'j0' })
    expect(buildJourneyQuery({ productId: null })).toEqual({ journey: 'j0' })
  })

  it('isJourneyActive 仅 query.journey===\'j0\' 为真', () => {
    expect(isJourneyActive({ journey: 'j0' })).toBe(true)
    expect(isJourneyActive({ journey: 'j0', productId: '5' })).toBe(true)
    expect(isJourneyActive({})).toBe(false)
    expect(isJourneyActive({ journey: 'other' })).toBe(false)
  })
})

describe('deriveNextStep / derivePrevStep（下一步推导）', () => {
  it('discovery 下一步是 sourcing，并透传 productId', () => {
    const next = deriveNextStep('discovery', { productId: '7' })
    expect(next).toEqual({
      key: 'sourcing', title: '选择货源', route: '/app/supply/sourcing',
      query: { journey: 'j0', productId: '7' },
    })
  })

  it('channel 下一步是 prepare（末步前一步）', () => {
    const next = deriveNextStep('channel', {})
    expect(next?.key).toBe('prepare')
    expect(next?.route).toBe('/app/market/candidates')
  })

  it('prepare 是末步，下一步为 null', () => {
    expect(deriveNextStep('prepare', {})).toBeNull()
  })

  it('discovery 是首步，上一步为 null', () => {
    expect(derivePrevStep('discovery', {})).toBeNull()
  })

  it('cost 上一步是 sourcing，下一步是 channel', () => {
    expect(derivePrevStep('cost', {}).key).toBe('sourcing')
    expect(deriveNextStep('cost', {}).key).toBe('channel')
  })

  it('未知步返回 null（不崩溃）', () => {
    expect(deriveNextStep('unknown', {})).toBeNull()
    expect(derivePrevStep('unknown', {})).toBeNull()
  })
})

describe('identifyStartingPoint（起点识别）', () => {
  it('零基础且无方向：默认从研究商品方向开始', () => {
    const r = identifyStartingPoint({})
    expect(r.firstStep).toBe('discovery')
    expect(r.reason).toContain('零基础')
  })

  it('零基础带方向：仍从 discovery 但说明含方向', () => {
    const r = identifyStartingPoint({ direction: 'A' })
    expect(r.firstStep).toBe('discovery')
    expect(r.reason).toContain('A')
  })

  it('已连接店铺：从研究商品方向开始', () => {
    const r = identifyStartingPoint({ hasShops: true })
    expect(r.firstStep).toBe('discovery')
  })

  it('已存在商品主档：从选择货源开始', () => {
    const r = identifyStartingPoint({ hasProducts: true })
    expect(r.firstStep).toBe('sourcing')
    expect(r.reason).toContain('货源')
  })
})

describe('credibilityTag / credibilityLabel（可信度标签映射）', () => {
  it('来源字符串映射到标签码（对齐 DATA_TAGS）', () => {
    expect(credibilityTag('api')).toBe('API_UNVERIFIED')
    expect(credibilityTag('CSV')).toBe('EXTERNAL_IMPORT')
    expect(credibilityTag('manual')).toBe('MANUAL_UNVERIFIED')
    expect(credibilityTag('builtin')).toBe('DEMO')
    expect(credibilityTag('official')).toBe('OFFICIAL_VERIFIED')
  })

  it('未识别来源回落 UNKNOWN', () => {
    expect(credibilityTag('')).toBe('UNKNOWN')
    expect(credibilityTag('whatever')).toBe('UNKNOWN')
  })

  it('标签码到中文', () => {
    expect(credibilityLabel('DEMO')).toBe('演示数据')
    expect(credibilityLabel('UNKNOWN')).toBe('数据未知')
  })
})

describe('honestValue（缺数据诚实降级：MISSING 不当 0）', () => {
  it('null/undefined/NaN/空串 → 占位符 —', () => {
    expect(honestValue(null)).toBe(MISSING_PLACEHOLDER)
    expect(honestValue(undefined)).toBe(MISSING_PLACEHOLDER)
    expect(honestValue(NaN)).toBe(MISSING_PLACEHOLDER)
    expect(honestValue('')).toBe(MISSING_PLACEHOLDER)
    expect(honestValue('   ')).toBe(MISSING_PLACEHOLDER)
  })

  it('0 与 false 视为有效值，原样保留（关键：不得当缺失）', () => {
    expect(honestValue(0)).toBe(0)
    expect(honestValue(false)).toBe(false)
    expect(honestValue(0.0)).toBe(0)
  })

  it('正常数值/字符串原样返回', () => {
    expect(honestValue(42)).toBe(42)
    expect(honestValue('yoga mat')).toBe('yoga mat')
  })
})

describe('stepCompletion（步骤完成度）', () => {
  it('discovery：有商品数或已选商品即 done', () => {
    expect(stepCompletion('discovery', { productsCount: 0 })).toBe('empty')
    expect(stepCompletion('discovery', { productsCount: 3 })).toBe('done')
    expect(stepCompletion('discovery', { selectedProductId: 5 })).toBe('done')
  })

  it('cost：成本已算或利润非空即 done', () => {
    expect(stepCompletion('cost', {})).toBe('empty')
    expect(stepCompletion('cost', { costComputed: true })).toBe('done')
    expect(stepCompletion('cost', { profit: 1.2 })).toBe('done')
  })

  it('prepare：有商品主档 id 即 done', () => {
    expect(stepCompletion('prepare', {})).toBe('empty')
    expect(stepCompletion('prepare', { productMasterId: 9 })).toBe('done')
  })

  it('未知步默认 empty', () => {
    expect(stepCompletion('unknown', {})).toBe('empty')
  })
})

describe('stepIndex', () => {
  it('返回 0 基索引，未知步 -1', () => {
    expect(stepIndex('discovery')).toBe(0)
    expect(stepIndex('prepare')).toBe(4)
    expect(stepIndex('nope')).toBe(-1)
  })
})
