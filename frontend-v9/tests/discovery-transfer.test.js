import { beforeEach, describe, expect, it, vi } from 'vitest'

// 转池走真实 POST /products 域函数；mock 掉 client 层，域逻辑不变。
const mocks = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('../src/shared/api/client', () => ({ default: { post: mocks.post } }))

import { candidateToProductPayload, transferCandidates } from '../src/composables/discoveryTransfer'

describe('candidateToProductPayload（候选 → 商品创建载荷）', () => {
  it('候选缺标题（null/空串/非字符串）返回 null，不可转池', () => {
    expect(candidateToProductPayload({})).toBeNull()
    expect(candidateToProductPayload({ title: '   ' })).toBeNull()
    expect(candidateToProductPayload({ title: 42 })).toBeNull()
  })

  it('标题去首尾空格', () => {
    expect(candidateToProductPayload({ title: '  Yoga Mat  ' }).title).toBe('Yoga Mat')
  })

  it('无价格属性时 attrs 为空对象（不伪造字段）', () => {
    expect(candidateToProductPayload({ title: 'x' }).attrs).toEqual({})
  })

  it('supplier_price/sale_price 进 attrs', () => {
    const payload = candidateToProductPayload({ title: 'x', supplier_price: 10, sale_price: 25.5 })
    expect(payload.attrs).toEqual({ supplier_price: 10, sale_price: 25.5 })
  })

  it('仅 price 时回退为 sale_price', () => {
    expect(candidateToProductPayload({ title: 'x', price: 9.9 }).attrs.sale_price).toBe(9.9)
  })

  it('price 与 sale_price 同时存在时 sale_price 优先，不覆盖', () => {
    const payload = candidateToProductPayload({ title: 'x', price: 1, sale_price: 2 })
    expect(payload.attrs.sale_price).toBe(2)
    expect(payload.attrs.price).toBeUndefined()
  })

  it('类目缺失归空串', () => {
    expect(candidateToProductPayload({ title: 'x' }).category).toBe('')
  })

  it('来源平台/链接原样透传；缺失则键不出现', () => {
    const full = candidateToProductPayload({
      title: 'x', source_platform: '1688', source_url: 'https://d.1688.com/1',
    })
    expect(full.source_platform).toBe('1688')
    expect(full.source_url).toBe('https://d.1688.com/1')
    const bare = candidateToProductPayload({ title: 'x' })
    expect(bare.source_platform).toBeUndefined()
    expect(bare.source_url).toBeUndefined()
  })
})

describe('transferCandidates（批量转池）', () => {
  beforeEach(() => { mocks.post.mockReset() })

  it('全部成功：逐条 POST /products 并按序收集 created', async () => {
    mocks.post.mockImplementation((url, payload) =>
      Promise.resolve({ data: { id: payload.title === 'A' ? 1 : 2, title: payload.title } }))
    const { created, failed } = await transferCandidates([{ title: 'A' }, { title: 'B' }])
    expect(mocks.post).toHaveBeenCalledTimes(2)
    expect(mocks.post).toHaveBeenNthCalledWith(1, '/products', { title: 'A', category: '', attrs: {} })
    expect(created.map((p) => p.id)).toEqual([1, 2])
    expect(failed).toEqual([])
  })

  it('缺标题候选进 failed 并带序号与原因，不中断后续', async () => {
    mocks.post.mockResolvedValue({ data: { id: 2 } })
    const { created, failed } = await transferCandidates([{ title: '' }, { title: 'B' }])
    expect(failed).toEqual([{ index: 0, reason: '候选缺少标题，无法转入商品池' }])
    expect(created.length).toBe(1)
  })

  it('创建抛错（detail.message）进 failed，不抛出异常', async () => {
    mocks.post.mockRejectedValue({ response: { data: { detail: { message: '标题重复' } } } })
    const { created, failed } = await transferCandidates([{ title: 'A' }])
    expect(created).toEqual([])
    expect(failed).toEqual([{ index: 0, reason: '标题重复' }])
  })

  it('网络级错误回退 err.message 兜底原因', async () => {
    mocks.post.mockRejectedValue(new Error('Network Error'))
    const { failed } = await transferCandidates([{ title: 'A' }])
    expect(failed[0].reason).toBe('Network Error')
  })
})
