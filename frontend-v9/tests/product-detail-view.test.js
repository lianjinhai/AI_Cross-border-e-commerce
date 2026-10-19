import { describe, expect, it } from 'vitest'
import {
  assetPageItems,
  assetRowView,
  buildLaunchDeepLink,
  buildShopOptions,
  launchItemView,
  launchWizardStartStep,
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

describe('J1 buildLaunchDeepLink — 商品→上线向导深链携带上下文', () => {
  it('携带 product_id 与来源（from），不丢商品上下文', () => {
    expect(buildLaunchDeepLink(7, { from: '/app/products/7' })).toEqual({
      path: '/app/launch',
      query: { product_id: '7', from: '/app/products/7' },
    })
  })

  it('带 shop_id 时一并下传（按店铺预选）', () => {
    expect(buildLaunchDeepLink(7, { shopId: 11, from: '/app/products/7' })).toEqual({
      path: '/app/launch',
      query: { product_id: '7', shop_id: '11', from: '/app/products/7' },
    })
  })

  it('缺 product_id / from 时不写入空键', () => {
    expect(buildLaunchDeepLink(null)).toEqual({ path: '/app/launch', query: {} })
    expect(buildLaunchDeepLink(7, { shopId: null, from: '' })).toEqual({
      path: '/app/launch', query: { product_id: '7' },
    })
  })

  // 回归证明（R3-3 真实浏览器发现）：`@click="goCreateLaunch"`（漏括号）会把 PointerEvent
  // 当 shopId 传入，旧实现 String(event) → `shop_id=[object PointerEvent]` → 上线中心
  // Number() 得 NaN → 店铺为空、创建按钮永久禁用。修复后必须丢弃任何非 id 值。
  it('丢弃事件对象等非 id 值，绝不把 [object …] 写进深链', () => {
    const pointerEvent = { isTrusted: true, type: 'click', target: { id: 3 } }
    expect(buildLaunchDeepLink(7, { shopId: pointerEvent, from: '/app/products/7' })).toEqual({
      path: '/app/launch', query: { product_id: '7', from: '/app/products/7' },
    })
    expect(buildLaunchDeepLink(pointerEvent, { shopId: pointerEvent })).toEqual({
      path: '/app/launch', query: {},
    })
    expect(buildLaunchDeepLink(7, { shopId: 'abc' }).query).toEqual({ product_id: '7' })
    expect(buildLaunchDeepLink(7, { shopId: 0 }).query).toEqual({ product_id: '7' })
    expect(buildLaunchDeepLink(7, { shopId: 3.5 }).query).toEqual({ product_id: '7' })
  })

  it('数字字符串 id 正常归一为数字（路由 query 场景）', () => {
    expect(buildLaunchDeepLink('7', { shopId: '11' })).toEqual({
      path: '/app/launch', query: { product_id: '7', shop_id: '11' },
    })
  })
})

describe('J1 launchWizardStartStep — 深链跳过「选商品」步', () => {
  it('携带 product_id 时跳过选商品步（从商品详情进）', () => {
    expect(launchWizardStartStep(7)).toBe(1)
    expect(launchWizardStartStep('11')).toBe(1)
  })

  it('未携带商品时从选商品步开始（正常从上线中心进）', () => {
    expect(launchWizardStartStep(null)).toBe(0)
    expect(launchWizardStartStep('')).toBe(0)
  })

  it('传进来的是事件对象时退回「选商品」步（不因 [object Object] 误跳过）', () => {
    expect(launchWizardStartStep({ isTrusted: true })).toBe(0)
    expect(launchWizardStartStep('abc')).toBe(0)
  })
})

// ── B3：概览 / 货源 / 表现 纯函数（防御式映射，任何缺失键回落「待补」，绝不崩溃） ──
import {
  offersViewModel,
  overviewViewModel,
  performanceViewModel,
  stageTone,
  supplierVerificationLabel,
} from '../src/shared/productDetailView'

describe('B3 stageTone', () => {
  it('缺口阶段 amber / 就绪 blue / 经营 success / 未知 neutral', () => {
    expect(stageTone('NO_SUPPLY')).toBe('amber')
    expect(stageTone('CHANNEL_PENDING')).toBe('amber')
    expect(stageTone('SUPPLY_READY')).toBe('blue')
    expect(stageTone('LAUNCHING')).toBe('blue')
    expect(stageTone('OPERATING')).toBe('success')
    expect(stageTone('WHATEVER')).toBe('neutral')
  })
})

describe('B3 overviewViewModel', () => {
  it('完整 overview → 稳定视图（供给摘要 + 阶段 + 理由 + 表现透传）', () => {
    const v = overviewViewModel({
      product: { id: 1 },
      supply: { offers_count: 2, selected_offer_id: 5, selected_offer_price_cny: 9.5,
        min_offer_price_cny: 8.1, cost_missing: ['hs_code'], cost_complete: false },
      channels: { total: 1, channels: [] },
      performance: { units_sold: 12 },
      stage: { key: 'SUPPLY_READY', label: '货源就绪', reasons: ['已有 2 条报价'] },
      generated_at: '2026-10-19T08:00:00',
    })
    expect(v.supply.offersCount).toBe(2)
    expect(v.supply.selectedOfferId).toBe(5)
    expect(v.supply.costMissing).toEqual(['hs_code'])
    expect(v.stage.key).toBe('SUPPLY_READY')
    expect(v.stage.tone).toBe('blue')
    expect(v.stage.reasons).toEqual(['已有 2 条报价'])
    expect(v.performance).toEqual({ units_sold: 12 })
    expect(v.generatedAt).toBe('2026-10-19T08:00:00')
  })

  it('空/缺失 overview → 全部「待补」回落，永不抛错', () => {
    const v = overviewViewModel()
    expect(v.product).toBeNull()
    expect(v.supply.offersCount).toBeNull()
    expect(v.supply.costMissing).toEqual([])
    expect(v.stage.label).toBe('待补')
    expect(v.stage.tone).toBe('neutral')
    expect(v.performance).toBeNull()
    const v2 = overviewViewModel(null)
    expect(v2.stage.label).toBe('待补')
  })
})

describe('B3 offersViewModel', () => {
  const supplier = { id: 3, name: '深圳华强', region: '广东', supplier_type: 'factory',
    verification_status: 'verified', rating: 4.6, certifications: ['ISO9001'], capabilities: ['OEM'] }

  it('嵌套 supplier 契约 → 行视图（金额真币种、供应商 chips、选中标记）', () => {
    const rows = offersViewModel([
      { id: 5, price: 9.9, currency: 'CNY', moq: 50, ship_days: 14, in_stock: true,
        valid_until: '2026-12-31', source_kind: 'manual', verification_status: 'verified', supplier },
      { id: 6, price: 8.2, currency: 'CNY', moq: 100, ship_days: 20, in_stock: false,
        source_kind: 'scraped', verification_status: 'unverified', supplier },
    ], 5)
    expect(rows).toHaveLength(2)
    expect(rows[0].isSelected).toBe(true)
    expect(rows[1].isSelected).toBe(false)
    expect(rows[0].validityText).toBe('2026-12-31')
    expect(rows[1].validityText).toBe('未填写')
    expect(rows[0].supplier.name).toBe('深圳华强')
    expect(rows[0].supplier.verificationHonestNote).toBe('平台核验，非工商尽调')
    expect(rows[0].supplier.chips.map((c) => c.label)).toEqual(['ISO9001', 'OEM'])
    expect(rows[0].priceText).not.toBe('—')
    // 爬取 + 未核验 → 诚实「待核实」琥珀（tone 由 matchingView 决定，此处只断言非 success）
    expect(rows[1].verificationLabel).toBe('待核实')
  })

  it('无币种 → 裸数字 + 「币种未知」，绝不默认 $；缺 id 不标选中', () => {
    const rows = offersViewModel([{ price: 9.9, moq: 10 }], 5)
    expect(rows[0].priceText).not.toContain('$')
    expect(rows[0].priceNote).toBe('币种未知')
    expect(rows[0].isSelected).toBe(false)
  })

  it('非数组输入 → 空数组', () => {
    expect(offersViewModel(null, null)).toEqual([])
  })
})

describe('B3 performanceViewModel', () => {
  it('null → 未取得（available=false），绝不臆造 0', () => {
    expect(performanceViewModel(null)).toMatchObject({ available: false, hasData: false, metrics: [] })
  })
  it('有值 → 金额裸数字 + 币种未知、比率百分比、缺失「—」', () => {
    const v = performanceViewModel({ units_sold: 34, revenue: 1234.5, margin: 0.18, profit: null })
    expect(v.available).toBe(true)
    const byKey = Object.fromEntries(v.metrics.map((m) => [m.key, m]))
    expect(byKey.units_sold.text).toBe('34')
    expect(byKey.revenue.text).not.toContain('$')
    expect(byKey.revenue.note).toBe('币种未知')
    expect(byKey.margin.text).toBe('18.0%')
    expect(byKey.profit.text).toBe('—')
    expect(byKey.profit.missing).toBe(true)
  })
})

describe('B3 supplierVerificationLabel', () => {
  it('verified 必须带诚实边界注；未知值回显不臆造', () => {
    expect(supplierVerificationLabel('verified')).toEqual({ label: '已核验', honestNote: '平台核验，非工商尽调' })
    expect(supplierVerificationLabel('unverified').label).toBe('未核验')
    expect(supplierVerificationLabel('').label).toBe('未核验')
    expect(supplierVerificationLabel('weird').label).toBe('weird')
  })
})
