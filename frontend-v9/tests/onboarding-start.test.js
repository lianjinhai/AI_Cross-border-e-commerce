import { describe, it, expect, beforeEach } from 'vitest'
import {
  recommendedStartCard,
  buildStartSignals,
  pathItemsForCard,
  START_CARDS,
} from '../src/shared/onboardingStart'
import {
  loadSessionProfile,
  saveSessionProfile,
  clearSessionProfile,
} from '../src/shared/onboardingProfile'

/**
 * 新手起步 · 资源起点卡（B2）纯函数测试。
 * 守护：推荐诚实（事实不足回退 A 且不假装已判定/已保存）、
 * 路径按卡重排、会话画像 roundtrip 与清空。
 */

describe('recommendedStartCard', () => {
  it('NEW_USER（无店铺无商品）→ A', () => {
    const r = recommendedStartCard({ hasSalesShop: false, hasGoods: false })
    expect(r.card).toBe('A')
  })

  it('STORE_OWNER（有销售店铺）→ C', () => {
    const r = recommendedStartCard({ hasSalesShop: true })
    expect(r.card).toBe('C')
    expect(r.reason).toContain('销售店铺')
  })

  it('FACTORY（有商品/货源资源）→ B', () => {
    const r = recommendedStartCard({ hasGoods: true })
    expect(r.card).toBe('B')
    expect(r.reason).toContain('供给')
  })

  it('空信号（事实不足）→ A 且理由诚实可改写', () => {
    const r = recommendedStartCard({})
    expect(r.card).toBe('A')
    expect(r.reason).toContain('可随时更换')
  })

  it('计数形式等价：salesShopCount>0 → C', () => {
    expect(recommendedStartCard({ salesShopCount: 2 }).card).toBe('C')
  })

  it('计数形式等价：productTotal>0 → B', () => {
    expect(recommendedStartCard({ productTotal: 5 }).card).toBe('B')
  })

  it('有店铺优先于有商品：同时具备 → C', () => {
    expect(recommendedStartCard({ hasSalesShop: true, hasGoods: true }).card).toBe('C')
  })
})

describe('buildStartSignals', () => {
  it('销售店铺 = type!=="source" 的计数', () => {
    const s = buildStartSignals({
      shopItems: [{ type: 'source' }, { type: '销售' }, { type: '销售' }],
      productTotal: 0,
    })
    expect(s.salesShopCount).toBe(2)
    expect(s.hasSalesShop).toBe(true)
    expect(s.hasGoods).toBe(false)
  })

  it('商品 total>0 视为有货源资源', () => {
    const s = buildStartSignals({ shopItems: [], productTotal: 7 })
    expect(s.hasGoods).toBe(true)
    expect(s.productTotal).toBe(7)
  })

  it('无店铺无商品 → 全 false/0', () => {
    const s = buildStartSignals({ shopItems: [], productTotal: 0 })
    expect(s.salesShopCount).toBe(0)
    expect(s.hasGoods).toBe(false)
  })

  it('缺参不崩，返回零值信号', () => {
    const s = buildStartSignals()
    expect(s).toEqual({ hasSalesShop: false, salesShopCount: 0, hasGoods: false, productTotal: 0 })
  })
})

describe('pathItemsForCard', () => {
  it('A/B/C 各返回非空清单', () => {
    for (const card of ['A', 'B', 'C']) {
      const items = pathItemsForCard(card)
      expect(Array.isArray(items)).toBe(true)
      expect(items.length).toBeGreaterThan(0)
      expect(items[0]).toHaveProperty('label')
    }
  })

  it('A 清单首项为研究商品方向', () => {
    expect(pathItemsForCard('A')[0].label).toContain('研究商品方向')
  })

  it('未知卡 → 默认清单（对齐原 GENERIC，无死端）', () => {
    const items = pathItemsForCard('Z')
    expect(items[0].label).toBe('浏览商品池')
  })

  it('START_CARDS 三卡主键齐全', () => {
    expect(Object.keys(START_CARDS).sort()).toEqual(['A', 'B', 'C'])
  })
})

describe('onboardingProfile 会话 roundtrip（刷新存活 / 清空生效）', () => {
  beforeEach(() => clearSessionProfile())

  it('保存后读回存活，persisted 恒 false', () => {
    const saved = saveSessionProfile({ direction: 'B', budget: '1-3万' })
    expect(saved.persisted).toBe(false)
    const loaded = loadSessionProfile()
    expect(loaded).not.toBeNull()
    expect(loaded.direction).toBe('B')
    expect(loaded.budget).toBe('1-3万')
    expect(loaded.persisted).toBe(false)
  })

  it('增量合并不丢旧字段', () => {
    saveSessionProfile({ direction: 'A', targetMarket: '美国' })
    const next = saveSessionProfile({ risk: '低' })
    expect(next.direction).toBe('A')
    expect(next.targetMarket).toBe('美国')
    expect(next.risk).toBe('低')
  })

  it('clear 后读回 null', () => {
    saveSessionProfile({ direction: 'C' })
    clearSessionProfile()
    expect(loadSessionProfile()).toBeNull()
  })
})
