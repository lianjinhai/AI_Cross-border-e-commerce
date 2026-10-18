import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * B1 正确性修复：fetchProducts 必须同时支持 category 与 source，
 * 各自按其语义转发（后端 list_products 仅按 category 过滤）。
 * - 传 category 时，params.category 必须命中（修复前被错误塞进 source）；
 * - 仅传 source 的既有调用方，params.source 必须保持不变（向后兼容）。
 * 断言范式同 products-api-contract.test.js（vi.mock client + 直读 mock.calls）。
 */
vi.mock('../src/shared/api/client', () => {
  const make = (method) => vi.fn(async () => ({ data: { ok: true, method } }))
  const api = {
    get: make('GET'), post: make('POST'), put: make('PUT'), delete: make('DELETE'),
    interceptors: { request: { use() {} }, response: { use() {} } },
  }
  return { default: api }
})

import api from '../src/shared/api/client'
import { fetchProducts } from '../src/api/domains/products'

const lastParams = () => api.get.mock.calls.at(-1)[1].params

beforeEach(() => {
  api.get.mockClear(); api.post.mockClear(); api.put.mockClear(); api.delete.mockClear()
})

describe('fetchProducts — category 过滤正确转发（修复前被误塞进 source）', () => {
  it('传 category 时，params 携带 category 且值正确', async () => {
    await fetchProducts({ page: 1, keyword: '杯', category: '家居' })
    const params = lastParams()
    expect(params).toMatchObject({ category: '家居', keyword: '杯', page_num: 1 })
    // 关键回归：category 绝不能再被当作 source 透传
    expect(params.source).toBeUndefined()
  })

  it('category 为空字符串时不污染 params（等价未筛选）', async () => {
    await fetchProducts({ page: 1, category: '' })
    const params = lastParams()
    expect(params.category).toBe('')
  })
})

describe('fetchProducts — source 仅调用方向后兼容', () => {
  it('仅传 source 时，params.source 保持不变、category 仍透传（默认空）', async () => {
    await fetchProducts({ page: 2, source: '1688' })
    const params = lastParams()
    expect(params.source).toBe('1688')
    // 兼容旧调用方：不应因新增 category 而丢失/改写 source
    expect(params.page_num).toBe(2)
  })

  it('同时传 category 与 source 时两者各自独立转发', async () => {
    await fetchProducts({ page: 1, category: '3C配件', source: '1688' })
    const params = lastParams()
    expect(params).toMatchObject({ category: '3C配件', source: '1688' })
  })
})

describe('fetchProducts — 端点锁定', () => {
  it('命中真实 GET /products 端点', async () => {
    await fetchProducts({ page: 1 })
    expect(api.get.mock.calls.at(-1)[0]).toBe('/products')
  })
})
