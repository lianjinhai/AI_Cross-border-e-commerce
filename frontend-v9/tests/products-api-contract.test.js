import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * R3-1A products 域端点契约锁定（E01/E02/E05）：
 * 域函数必须打到 backend/app/routers/{products,product_assets,product_channels}.py
 * 的真实端点，入参键名与后端 Pydantic/Query 模型逐字一致。
 * 断言范式与 uxd-api-domains.test.js 一致（vi.mock client + mock.calls 直读）。
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
import {
  addAsset, fetchAssets, fetchChannels, fetchProduct, isAssetContentHash, verifyAsset,
} from '../src/api/domains/products'

const last = (fn) => fn.mock.calls.at(-1)

beforeEach(() => {
  api.get.mockClear(); api.post.mockClear(); api.put.mockClear(); api.delete.mockClear()
})

describe('E01 fetchChannels — GET /products/{id}/channels 透传 channels_dto', () => {
  it('hits the real endpoint and passes the whole DTO through (no .items guessing)', async () => {
    const dto = {
      product: { id: 7, title: 't', sku: 's' },
      total: 1,
      channels: [{ shop: { id: 1, name: 'n', platform: 'amazon', market: 'US' }, active_launch: null, history: [] }],
    }
    api.get.mockResolvedValueOnce({ data: dto })
    await expect(fetchChannels(7)).resolves.toEqual(dto)
    expect(last(api.get)).toEqual(['/products/7/channels'])
    // 契约形状断言：后端 channels_dto 只含 channels，不含 items
    expect(dto.channels).toHaveLength(1)
    expect(dto.items).toBeUndefined()
  })
})

describe('E02 fetchAssets — shop_id 必填，缺上下文时拒绝猜测默认店铺', () => {
  it('sends shop_id/page_num/page_size query params', async () => {
    await fetchAssets(7, { shopId: 11, pageNum: 2, pageSize: 50 })
    expect(last(api.get)).toEqual(['/products/7/assets', {
      params: { shop_id: 11, page_num: 2, page_size: 50 },
    }])
  })

  it('throws a local guard error when shopId is missing/invalid (no default shop, no request fired)', async () => {
    await expect(fetchAssets(7)).rejects.toThrow(/shop_id/)
    await expect(fetchAssets(7, { shopId: 0 })).rejects.toThrow(/shop_id/)
    await expect(fetchAssets(7, { shopId: '11' })).rejects.toThrow(/shop_id/)
    expect(api.get).not.toHaveBeenCalled()
  })
})

describe('E05 addAsset / verifyAsset — 请求体与后端模型逐字对齐', () => {
  it('POST /products/{id}/assets carries AssetIn keys (AssetRegistration + shop_id)', async () => {
    await addAsset(7, {
      shop_id: 11,
      asset_key: 'main_image',
      expected_version: 0,
      asset_type: 'MAIN_IMAGE',
      uri: 'https://cdn.example.com/main.jpg',
      content_hash: 'a'.repeat(64),
      rights_status: 'OWNED',
      rights_evidence_ref: '',
      source: '供应商目录',
    })
    const [url, body] = last(api.post)
    expect(url).toBe('/products/7/assets')
    expect(body).toMatchObject({ shop_id: 11, asset_type: 'MAIN_IMAGE', expected_version: 0 })
    // extra=forbid：不带任何模型外字段
    expect(Object.keys(body).sort()).toEqual([
      'asset_key', 'asset_type', 'content_hash', 'expected_version', 'rights_evidence_ref',
      'rights_status', 'shop_id', 'source', 'uri',
    ])
  })

  it('POST /products/{id}/assets/{assetId}/verify carries ReviewIn keys', async () => {
    await verifyAsset(7, 101, {
      shop_id: 11,
      expected_version: 2,
      decision: 'VERIFIED',
      evidence_ref: 'evidence://rights/101.pdf',
      reason: '授权书在档',
    })
    const [url, body] = last(api.post)
    expect(url).toBe('/products/7/assets/101/verify')
    expect(body).toMatchObject({ shop_id: 11, expected_version: 2, decision: 'VERIFIED' })
    expect(Object.keys(body).sort()).toEqual(['decision', 'evidence_ref', 'expected_version', 'reason', 'shop_id'])
  })

  it('isAssetContentHash enforces the backend sha256 hex64 pattern', () => {
    expect(isAssetContentHash('a'.repeat(64))).toBe(true)
    expect(isAssetContentHash('abc')).toBe(false)
    expect(isAssetContentHash('Z'.repeat(64))).toBe(false)
    expect(isAssetContentHash('')).toBe(false)
  })
})

describe('fetchProduct — GET /products/{id} 端点锁定', () => {
  it('hits the real endpoint', async () => {
    await fetchProduct(7)
    expect(last(api.get)).toEqual(['/products/7'])
  })
})
