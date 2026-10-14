import { describe, expect, it } from 'vitest'
import {
  assetPageItems,
  assetRowView,
  buildShopOptions,
  launchItemView,
  normalizeChannels,
  progressLabel,
  nextActionLabel,
  sectionErrorText,
  shopContext,
  verifyErrorKind,
} from '../src/shared/productDetailView'

/**
 * R3-1A E01/E05/E06 契约测试：以真实后端响应样本断言前端只读稳定字段。
 * 样本形状逐字来自 backend/app/workflows/launch_dto.py（channels_dto / launch_list_item）
 * 与 backend/app/routers/product_assets.py + models.ProductAsset。
 */

const SAMPLE_CHANNELS_RESPONSE = {
  product: { id: 7, title: '演示商品', sku: 'SKU-007' },
  total: 2,
  channels: [
    {
      shop: { id: 11, name: '美国站主店', platform: 'amazon', market: 'US' },
      active_launch: {
        id: 41, execution_status: 'RUNNING', platform_status: 'SUBMITTED',
        progress: { completed: 3, total: 8 },
        next_action: { action: 'ADD_MATERIAL', step_code: 'ASSETS', executable: true },
        blocked_summary: [], revision: 5, created_at: '2026-01-02 10:00:00', is_history: false,
      },
      history: [],
    },
    {
      shop: { id: 12, name: '欧洲站副店', platform: 'amazon', market: 'DE' },
      active_launch: null,
      history: [
        {
          id: 31, execution_status: 'CANCELLED', platform_status: 'DRAFT',
          progress: { completed: 1, total: 8 },
          next_action: { action: null, step_code: null, executable: false },
          blocked_summary: [{ code: 'STORE_CONTEXT_MISSING', message: '店铺缺少目标国家或履约配置' }],
          revision: 2, created_at: '2025-12-20 08:00:00', is_history: true,
        },
      ],
    },
  ],
}

const SAMPLE_ASSET_PAGE = {
  items: [
    {
      id: 101, asset_key: 'main_image', version: 2, asset_type: 'MAIN_IMAGE',
      uri: 'https://cdn.example.com/main.jpg',
      content_hash: 'a'.repeat(64),
      rights_status: 'OWNED', source: '供应商目录', rights_evidence_ref: '',
      market: 'US', platform: 'amazon', verification_status: 'VERIFIED',
      valid_from: null, valid_until: null, manifest: {},
      created_by: 1, created_at: '2026-01-03 09:00:00',
    },
    {
      id: 102, asset_key: 'rights_evidence', version: 1, asset_type: 'RIGHTS_EVIDENCE',
      uri: 'evidence://rights/2026/101.pdf',
      content_hash: 'b'.repeat(64),
      rights_status: 'UNKNOWN', source: '待补充', rights_evidence_ref: '',
      market: 'US', platform: 'amazon', verification_status: 'MANUAL_REPORTED',
      valid_from: null, valid_until: null, manifest: {},
      created_by: 1, created_at: '2026-01-04 09:00:00',
    },
  ],
  total: 2, page: 1, page_size: 20,
}

describe('E01 normalizeChannels — 读 channels 聚合，不读 items', () => {
  it('reads response.channels with per-shop independence', () => {
    const view = normalizeChannels(SAMPLE_CHANNELS_RESPONSE)
    expect(view.total).toBe(2)
    expect(view.channels.map((c) => c.shop.id)).toEqual([11, 12])
    expect(view.channels[0].active).toMatchObject({
      id: 41,
      execution_status: 'RUNNING',
      progress: { completed: 3, total: 8 },
    })
    // 展示层（launchItemView）才把 progress 折成文案
    expect(launchItemView(view.channels[0].active).progress).toBe('3/8 步')
    expect(view.channels[1].active).toBeNull()
    expect(view.channels[1].history).toHaveLength(1)
  })

  it('tolerates legacy items-shaped payloads without inventing fields', () => {
    const view = normalizeChannels({ items: [{ shop: { id: 5, name: 'x' }, active_launch: null, history: [] }] })
    expect(view.channels).toHaveLength(1)
    expect(view.channels[0].shop.id).toBe(5)
  })

  it('normalizes garbage/empty input to an empty view', () => {
    expect(normalizeChannels(null).channels).toEqual([])
    expect(normalizeChannels({}).total).toBe(0)
  })
})

describe('E01 launchItemView — 双店独立状态字段白名单', () => {
  it('exposes executionStatus/progress/nextAction/revision without raw guessing', () => {
    const view = launchItemView(SAMPLE_CHANNELS_RESPONSE.channels[0].active_launch)
    expect(view).toMatchObject({
      id: 41,
      executionStatus: 'RUNNING',
      progress: '3/8 步',
      nextAction: 'ADD_MATERIAL',
      blocked: false,
      revision: 5,
    })
  })

  it('marks blocked rounds and non-executable next actions', () => {
    const h = launchItemView(SAMPLE_CHANNELS_RESPONSE.channels[1].history[0])
    expect(h.blocked).toBe(true)
    expect(nextActionLabel(SAMPLE_CHANNELS_RESPONSE.channels[1].history[0].next_action)).toBe('—')
  })

  it('progress fallback reads as 尚未获得, never zero', () => {
    expect(progressLabel({})).toBe('尚未获得')
    expect(progressLabel({ completed: 2, total: 6 })).toBe('2/6 步')
  })
})

describe('E05 assetRowView — 真实字段映射，权利≠核验，未知不当可发布', () => {
  it('maps ProductAsset columns to stable view fields', () => {
    const view = assetRowView(SAMPLE_ASSET_PAGE.items[0])
    expect(view).toMatchObject({
      id: 101,
      assetKey: 'main_image',
      version: 2,
      typeLabel: '主图',
      uri: 'https://cdn.example.com/main.jpg',
      rightsLabel: '自有权利',
      verificationLabel: '已核验',
      market: 'US',
      platform: 'amazon',
    })
    expect(view.publishable).toBe(true)
  })

  it('UNKNOWN rights or unverified assets are never publishable', () => {
    const unknown = assetRowView(SAMPLE_ASSET_PAGE.items[1])
    expect(unknown.rightsLabel).toBe('权利未知')
    expect(unknown.publishable).toBe(false)
    const restricted = assetRowView({ rights_status: 'RESTRICTED', verification_status: 'VERIFIED' })
    expect(restricted.rightsLabel).toBe('权利受限')
    expect(restricted.publishable).toBe(false)
  })

  it('assetPageItems only trusts response.items', () => {
    expect(assetPageItems(SAMPLE_ASSET_PAGE)).toHaveLength(2)
    expect(assetPageItems({ data: [1] })).toEqual([])
    expect(assetPageItems(null)).toEqual([])
  })
})

describe('E02 buildShopOptions — 店铺选择器选项（渠道优先 + shops 兜底去重）', () => {
  it('merges channel shops with extra shops, dedup by id', () => {
    const options = buildShopOptions(
      [{ id: 11, name: '美国站主店', platform: 'amazon', market: 'US' }],
      [
        { id: 11, shop_name: '美国站主店', platform: 'amazon' },
        { id: 13, shop_name: '独立站', platform: 'shopify' },
      ],
    )
    expect(options).toEqual([
      { id: 11, label: '美国站主店 · amazon（US）' },
      { id: 13, label: '独立站 · shopify' },
    ])
  })

  it('returns empty without guessing a default shop', () => {
    expect(buildShopOptions([], [])).toEqual([])
  })
})

describe('E06 sectionErrorText — 错误不当空，具体原因透传', () => {
  it('prefers backend detail object message', () => {
    const err = { response: { data: { detail: { code: 'ASSET_TARGET_NOT_FOUND', message: '商品或目标店铺不存在' } } } }
    expect(sectionErrorText(err, 'fallback')).toBe('商品或目标店铺不存在')
  })

  it('falls back to error.message then caller fallback', () => {
    expect(sectionErrorText(new Error('boom'), 'fallback')).toBe('boom')
    expect(sectionErrorText(null, 'fallback')).toBe('fallback')
  })
})

describe('E03 shopContext — 由目标店铺推导 market/platform，不猜测', () => {
  it('reads market/platform from channel shops first', () => {
    const ctx = shopContext(
      [{ id: 11, name: '美国站', platform: 'amazon', market: 'US' }],
      [],
      11,
    )
    expect(ctx).toEqual({ market: 'US', platform: 'amazon' })
  })

  it('falls back to shops API when not in channels', () => {
    const ctx = shopContext([], [{ id: 13, shop_name: '独立站', platform: 'shopify', market: 'DE' }], 13)
    expect(ctx).toEqual({ market: 'DE', platform: 'shopify' })
  })

  it('returns null when shop missing or lacks market/platform (no guessing)', () => {
    expect(shopContext([], [], 99)).toBeNull()
    expect(shopContext([{ id: 5, name: 'x' }], [], 5)).toBeNull()
  })
})

describe('E04 verifyErrorKind — 无权限/自审/版本冲突分因，409 保留输入提示', () => {
  it('403 合规审批缺权 → no_permission', () => {
    const err = { response: { status: 403, data: { detail: { code: 'ASSET_PERMISSION_DENIED', message: '需要合规审批权' } } } }
    expect(verifyErrorKind(err).kind).toBe('no_permission')
  })

  it('自审限制（403 ASSET_SELF_REVIEW）→ self_review', () => {
    const err = { response: { status: 403, data: { detail: { code: 'ASSET_SELF_REVIEW', message: '提交人不能核验自己的权利证据' } } } }
    expect(verifyErrorKind(err).kind).toBe('self_review')
  })

  it('409 版本冲突 → version_conflict（保留已填内容提示）', () => {
    const err = { response: { status: 409, data: { detail: { code: 'ASSET_VERSION_CONFLICT', message: '仅可核验当前版本' } } } }
    const kind = verifyErrorKind(err)
    expect(kind.kind).toBe('version_conflict')
    expect(kind.message).toMatch(/刷新/)
  })

  it('其它错误（404/422）→ other，透传后端原因', () => {
    const err = { response: { status: 404, data: { detail: { code: 'ASSET_NOT_FOUND', message: '素材不适用于目标店铺' } } } }
    expect(verifyErrorKind(err, '兜底')).toEqual({ kind: 'other', message: '素材不适用于目标店铺' })
  })
})
