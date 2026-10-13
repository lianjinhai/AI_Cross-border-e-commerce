import { describe, expect, it } from 'vitest'

import {
  FLOW_STEPS, deriveFlowStep, editFormFromListing, listingPayloadFromForm,
  publishGate, shopSelectable, shopStatusTag, stepIndex,
} from '../src/composables/listingFlow'

describe('editFormFromListing（编辑表单初值）', () => {
  it('bullets 补齐 5 槽（不足补空串，超出截断）', () => {
    expect(editFormFromListing({ bullets: ['a'] }).bullets).toEqual(['a', '', '', '', ''])
    const over = editFormFromListing({ bullets: ['1', '2', '3', '4', '5', '6', '7'] })
    expect(over.bullets).toHaveLength(5)
  })

  it('null/undefined 元素归空串，不做字符串拼接', () => {
    expect(editFormFromListing({ bullets: [null, 'x'] }).bullets).toEqual(['', 'x', '', '', ''])
  })

  it('keywords 文本化为逗号分隔；非数组安全兜底', () => {
    expect(editFormFromListing({ keywords: ['a', 'b'] }).keywordsText).toBe('a, b')
    expect(editFormFromListing({}).keywordsText).toBe('')
  })
})

describe('listingPayloadFromForm（表单 → PUT 请求体）', () => {
  it('裁剪空值：空卖点与空关键词不进载荷', () => {
    const payload = listingPayloadFromForm({
      title: ' T ', description: 'd', bullets: [' a ', '', 'b'], keywordsText: 'k1, k2,,',
    })
    expect(payload).toEqual({ title: 'T', description: 'd', bullets: ['a', 'b'], keywords: ['k1', 'k2'] })
  })

  it('支持中文逗号与换行分隔关键词', () => {
    const payload = listingPayloadFromForm({ title: 'x', description: '', bullets: [], keywordsText: 'a，b\nc' })
    expect(payload.keywords).toEqual(['a', 'b', 'c'])
  })

  it('全空输入得到合法空载荷（不抛错）', () => {
    expect(listingPayloadFromForm({})).toEqual({ title: '', description: '', bullets: [], keywords: [] })
  })
})

describe('deriveFlowStep（由 Listing 状态推导当前步）', () => {
  it('无 id（未生成）→ generate', () => {
    expect(deriveFlowStep({})).toBe('generate')
  })

  it('高风险 → review（复核门禁优先级最高）', () => {
    expect(deriveFlowStep({ id: 1, risk_level: 'high' })).toBe('review')
  })

  it('needs_review → review', () => {
    expect(deriveFlowStep({ id: 1, needs_review: true })).toBe('review')
  })

  it('已发布 → receipts', () => {
    expect(deriveFlowStep({ id: 1, status: 'published' })).toBe('receipts')
  })

  it('其余 → publish；步骤顺序定义冻结为 5 步', () => {
    expect(deriveFlowStep({ id: 1 })).toBe('publish')
    expect(FLOW_STEPS.map((s) => s.key)).toEqual(['generate', 'edit', 'review', 'publish', 'receipts'])
  })
})

describe('stepIndex / publishGate / shopSelectable', () => {
  it('stepIndex 已知与未知 key', () => {
    expect(stepIndex('generate')).toBe(0)
    expect(stepIndex('receipts')).toBe(4)
    expect(stepIndex('unknown')).toBe(0)
  })

  it('publishGate：高风险禁发并给原因；其余放行', () => {
    expect(publishGate({ risk_level: 'high' }).allowed).toBe(false)
    expect(publishGate({ risk_level: 'high' }).reason).toContain('高风险')
    expect(publishGate({ risk_level: 'low' })).toEqual({ allowed: true, reason: '' })
    expect(publishGate({}).allowed).toBe(true)
  })

  it('shopSelectable：仅已授权且未显式禁发', () => {
    expect(shopSelectable({ status: 'authorized' })).toBe(true)
    expect(shopSelectable({ status: 'pending' })).toBe(false)
    expect(shopSelectable({ status: 'authorized', capabilities: { can_publish: false } })).toBe(false)
    expect(shopSelectable({ status: 'authorized', capabilities: { can_listing_readiness: true } })).toBe(true)
  })

  it('shopStatusTag：查表归一 + 未知值退化为中性 info', () => {
    expect(shopStatusTag('authorized')).toEqual({ text: '已授权·可选', type: 'success' })
    expect(shopStatusTag('weird')).toEqual({ text: 'weird', type: 'info' })
    expect(shopStatusTag('')).toEqual({ text: '未知', type: 'info' })
  })
})
