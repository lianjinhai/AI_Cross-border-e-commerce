import { describe, expect, it } from 'vitest'
import {
  SHOP_TRISTATE,
  SHOP_TABS,
  TRISTATE_LABEL,
  shopTriStates,
  shopTabStates,
  buildShopDetailLink,
} from '../../src/shared/shopDetailView'

/**
 * CH-03 店铺详情纯函数测试：
 * - 三态判定（授权有效/商品能力/订单能力；未核端点 → "未验证"）
 * - 四 Tab（商品/订单/同步任务/证书配置）
 * - 深链（store_id + return_to）
 */

describe('SHOP_TRISTATE / SHOP_TABS', () => {
  it('exposes exactly 3 tri-state items and 4 tabs', () => {
    expect(SHOP_TRISTATE.map((t) => t.key)).toEqual(['auth', 'product', 'order'])
    expect(SHOP_TABS.map((t) => t.key)).toEqual(['product', 'orders', 'sync', 'cert'])
  })
})

describe('shopTriStates', () => {
  it('authorized shop → auth valid; product/order unverified (endpoint unverified §7#8)', () => {
    const states = shopTriStates({ status: 'authorized' })
    expect(states.map((s) => s.state)).toEqual(['valid', 'unverified', 'unverified'])
  })

  it('expired/failed shop → auth invalid', () => {
    expect(shopTriStates({ status: 'expired' })[0].state).toBe('invalid')
    expect(shopTriStates({ status: 'failed' })[0].state).toBe('invalid')
  })

  it('unknown/empty status → auth unverified (no fake success)', () => {
    expect(shopTriStates({}).map((s) => s.state)).toEqual(['unverified', 'unverified', 'unverified'])
    expect(shopTriStates(null).map((s) => s.state)).toEqual(['unverified', 'unverified', 'unverified'])
  })

  it('explicit product_verified=true flips that state only', () => {
    const states = shopTriStates({ status: 'authorized', product_verified: true })
    expect(states.find((s) => s.key === 'product').state).toBe('valid')
    expect(states.find((s) => s.key === 'order').state).toBe('unverified')
  })

  it('falsy product_verified never becomes valid (no fake ✅)', () => {
    expect(shopTriStates({ product_verified: 'yes' })[1].state).toBe('unverified')
    expect(shopTriStates({ product_verified: 1 })[1].state).toBe('unverified')
  })
})

describe('TRISTATE_LABEL', () => {
  it('maps valid/invalid/unverified to user-visible copy', () => {
    expect(TRISTATE_LABEL.valid).toBe('有效')
    expect(TRISTATE_LABEL.invalid).toBe('失效')
    expect(TRISTATE_LABEL.unverified).toBe('未验证')
  })
})

describe('shopTabStates', () => {
  it('all 4 tabs are enabled by default (no hidden tabs)', () => {
    const tabs = shopTabStates({})
    expect(tabs).toHaveLength(4)
    expect(tabs.every((t) => t.disabled === false)).toBe(true)
  })
})

describe('buildShopDetailLink', () => {
  it('builds /app/channels/shops/:id carrying store id', () => {
    expect(buildShopDetailLink(42)).toBe('/app/channels/shops/42')
  })

  it('appends encoded return_to when provided (deep link with return_to)', () => {
    const link = buildShopDetailLink(7, '/app/orders')
    expect(link).toBe('/app/channels/shops/7?return_to=%2Fapp%2Forders')
  })

  it('omits query when returnTo is empty', () => {
    expect(buildShopDetailLink(7, '')).toBe('/app/channels/shops/7')
  })
})
