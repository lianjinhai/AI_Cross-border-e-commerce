import { describe, expect, it } from 'vitest'

import {
  buildContextChips,
  deriveCandidateDirections,
  extractTrendKeyword,
  filterCandidatesByCategory,
  filterCandidatesByKeyword,
  filterTrendsByKeyword,
  freshnessTimestamp,
  listCategories,
  maxTimestamp,
  resolveEvidenceStatus,
} from '../src/shared/discoveryView'

const trends = [
  { keyword: 'led strip', platform: 'google', source: 'api', created_at: '2026-10-01 10:00:00' },
  { keyword: 'yoga mat', platform: 'amazon', source: 'csv', created_at: '2026-10-02 09:00:00' },
  { keyword: 'phone case', platform: 'ebay', source: 'builtin', created_at: '2026-09-20 08:00:00' },
]

describe('extractTrendKeyword', () => {
  it('解析 趋势词「」 全角引号', () => {
    expect(extractTrendKeyword(['趋势词「led strip」30天增长80%，需求分 75'])).toBe('led strip')
  })
  it('解析 趋势词『』 半角引号变体', () => {
    expect(extractTrendKeyword(['趋势词『yoga mat』增长'])).toBe('yoga mat')
  })
  it('无趋势引用返回 null', () => {
    expect(extractTrendKeyword(['无匹配趋势，按默认需求评估'])).toBeNull()
    expect(extractTrendKeyword([])).toBeNull()
    expect(extractTrendKeyword(undefined)).toBeNull()
  })
})

describe('resolveEvidenceStatus', () => {
  it('api 趋势 → 有依据', () => {
    const r = resolveEvidenceStatus(
      { reasons: ['趋势词「led strip」30天增长80%，需求分 75'] },
      trends,
    )
    expect(r.status).toBe('verified')
    expect(r.kind).toBe('api')
    expect(r.label).toBe('官方API·有依据')
  })
  it('csv 趋势 → 有依据', () => {
    const r = resolveEvidenceStatus(
      { reasons: ['趋势词「yoga mat」30天增长10%，需求分 60'] },
      trends,
    )
    expect(r.status).toBe('verified')
    expect(r.kind).toBe('csv')
  })
  it('builtin 演示趋势 → 待验证', () => {
    const r = resolveEvidenceStatus(
      { reasons: ['趋势词「phone case」增长'] },
      trends,
    )
    expect(r.status).toBe('pending')
    expect(r.kind).toBe('builtin')
    expect(r.label).toBe('演示数据·待验证')
  })
  it('无趋势词 → 待验证（默认估算）', () => {
    const r = resolveEvidenceStatus({ reasons: ['无匹配趋势，按默认需求评估'] }, trends)
    expect(r.status).toBe('pending')
    expect(r.kind).toBe('none')
    expect(r.label).toBe('默认估算·待验证')
  })
  it('引用的趋势不在实时列表 → 待验证', () => {
    const r = resolveEvidenceStatus({ reasons: ['趋势词「ghost kw」增长'] }, trends)
    expect(r.status).toBe('pending')
    expect(r.kind).toBe('none')
  })
})

describe('deriveCandidateDirections', () => {
  const scores = [
    { product_id: 3, demand: 70, competition: 40, profit: 80, risk: 10, total: 65, model: 'rule', reasons: ['趋势词「phone case」增长'] },
    { product_id: 1, demand: 90, competition: 30, profit: 60, risk: 20, total: 88, model: 'llm', reasons: ['趋势词「led strip」增长'] },
    { product_id: 2, demand: 50, competition: 50, profit: 50, risk: 50, total: 55, model: 'rule', reasons: ['无匹配趋势，按默认需求评估'] },
  ]
  const productsById = {
    1: { title: 'LED Strip Lights', category: '3C配件' },
    2: { title: 'Mystery Item', category: '家居' },
    3: { title: 'Phone Case', category: '3C配件' },
  }

  it('按 total 降序取 Top N，透传原始分值', () => {
    const cards = deriveCandidateDirections({ scores, productsById, trends, topN: 2 })
    expect(cards.map((c) => c.productId)).toEqual([1, 3])
    expect(cards[0].total).toBe(88)
    expect(cards[0].demand).toBe(90)
  })

  it('解析标题/类目，缺商品回退为「商品 #id」', () => {
    const cards = deriveCandidateDirections({ scores, productsById: {}, trends, topN: 5 })
    expect(cards.find((c) => c.productId === 1).title).toBe('商品 #1')
    expect(cards.find((c) => c.productId === 1).category).toBe('')
  })

  it('携带证据状态（api 有依据 / builtin 待验证 / none 待验证）', () => {
    const cards = deriveCandidateDirections({ scores, productsById, trends, topN: 5 })
    const byId = Object.fromEntries(cards.map((c) => [c.productId, c]))
    expect(byId[1].evidenceKind).toBe('api')
    expect(byId[3].evidenceKind).toBe('builtin')
    expect(byId[2].evidenceKind).toBe('none')
    expect(byId[1].evidenceStatus).toBe('verified')
  })

  it('reasons 原样透传，不重标', () => {
    const cards = deriveCandidateDirections({ scores, productsById, trends, topN: 5 })
    expect(cards[0].reasons).toEqual(['趋势词「led strip」增长'])
  })
})

describe('筛选语义（真实本地过滤）', () => {
  const candidates = [
    { productId: 1, title: 'LED Strip Lights', category: '3C配件', evidenceBasis: '需求基于官方API趋势' },
    { productId: 2, title: 'Yoga Mat', category: '户外运动', evidenceBasis: '默认估算' },
    { productId: 3, title: 'Phone Case', category: '3C配件', evidenceBasis: '演示数据' },
  ]
  it('关键词筛选候选（标题匹配）', () => {
    expect(filterCandidatesByKeyword(candidates, 'yoga').map((c) => c.productId)).toEqual([2])
  })
  it('关键词筛选候选（依据说明匹配）', () => {
    expect(filterCandidatesByKeyword(candidates, 'api').map((c) => c.productId)).toEqual([1])
  })
  it('关键词筛选候选（空关键词不过滤）', () => {
    expect(filterCandidatesByKeyword(candidates, '  ').length).toBe(3)
  })
  it('类目筛选候选（精确匹配）', () => {
    expect(filterCandidatesByCategory(candidates, '3C配件').map((c) => c.productId)).toEqual([1, 3])
    expect(filterCandidatesByCategory(candidates, '').length).toBe(3)
  })
  it('趋势表关键词筛选（含 platform）', () => {
    expect(filterTrendsByKeyword(trends, 'ebay').map((t) => t.keyword)).toEqual(['phone case'])
    expect(filterTrendsByKeyword(trends, 'yoga').map((t) => t.keyword)).toEqual(['yoga mat'])
  })
  it('listCategories 去重排序', () => {
    expect(listCategories(candidates)).toEqual(['3C配件', '户外运动'])
  })
})

describe('数据时间（freshness）', () => {
  it('取 created_at 最大值', () => {
    expect(maxTimestamp(trends)).toBe('2026-10-02 09:00:00')
  })
  it('无时间戳返回 null', () => {
    expect(maxTimestamp([{ keyword: 'x' }, {}])).toBeNull()
    expect(freshnessTimestamp({ trends: [], scores: [] })).toBeNull()
  })
  it('合并趋势与评分时间', () => {
    const scores = [{ product_id: 1, created_at: '2026-10-05 12:00:00' }]
    expect(freshnessTimestamp({ trends, scores })).toBe('2026-10-05 12:00:00')
  })
})

describe('buildContextChips（画像上下文，仅参考不筛选）', () => {
  it('有值 → 本页范围参考', () => {
    const chips = buildContextChips({ budget: '5万', targetMarket: 'US', risk: '中' })
    expect(chips.find((c) => c.key === 'budget')).toMatchObject({ present: true, value: '5万' })
    expect(chips.every((c) => c.present)).toBe(true)
  })
  it('缺项 → 待补', () => {
    const chips = buildContextChips({ budget: '' })
    expect(chips.find((c) => c.key === 'budget').present).toBe(false)
    expect(chips.find((c) => c.key === 'targetMarket').present).toBe(false)
  })
  it('null 画像按全部待补', () => {
    const chips = buildContextChips(null)
    expect(chips.every((c) => !c.present)).toBe(true)
  })
})
