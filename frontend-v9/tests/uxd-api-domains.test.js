import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * UX-D 域端点契约锁定：域函数必须打到 backend/app/routers/ 的真实端点，
 * 入参键名与后端 Pydantic 模型一致（对照 routers 源码逐字核对）。
 */
vi.mock('../src/shared/api/client', () => {
  const calls = []
  const make = (method) => vi.fn(async (url, config) => {
    calls.push({ method, url, config })
    return { data: { ok: true, url, method, config } }
  })
  const api = {
    get: make('GET'), post: make('POST'), put: make('PUT'), delete: make('DELETE'),
    interceptors: { request: { use() {} }, response: { use() {} } },
  }
  api.__calls = calls
  return { default: api }
})

import api from '../src/shared/api/client'
import { fetchRefunds, createRefund, updateRefundStatus, receiveReturn, executeRefund } from '../src/api/domains/refunds'
import { generateSettlement, updateSettlement, fetchPayableSummary } from '../src/api/domains/settlements'
import { generateFromForecast, receivePurchase } from '../src/api/domains/purchases'
import { dutyRates, calcLandedCost } from '../src/api/domains/crossBorder'
import { importCsv, syncShopOrders } from '../src/api/domains/orders'
import { requestAutoReply, reply } from '../src/api/domains/support'
import { fetchAlerts, updateAlertRule } from '../src/api/domains/alerts'

const calls = () => api.__calls
const last = () => calls().at(-1)

beforeEach(() => { calls().length = 0 })

describe('refunds domain endpoints', () => {
  it('hits the real refunds routes with backend param names', async () => {
    await fetchRefunds({ status: 'pending', page: 2 })
    expect(last().url).toBe('/refunds')
    expect(last().config.params).toEqual({ status: 'pending', page_num: 2 })

    await createRefund({ order_id: 1, type: 'return_refund', qty: 1, restock: true })
    expect(last()).toMatchObject({ method: 'POST', url: '/refunds' })

    await updateRefundStatus(7, { status: 'rejected', note: 'x' })
    expect(last()).toMatchObject({ method: 'PUT', url: '/refunds/7/status' })
    expect(last().config ? undefined : undefined)
    expect(api.put.mock.calls.at(-1)[1]).toEqual({ status: 'rejected', note: 'x' })

    await receiveReturn(7)
    expect(last()).toMatchObject({ method: 'POST', url: '/refunds/7/return_receive' })
    await executeRefund(7)
    expect(last()).toMatchObject({ method: 'POST', url: '/refunds/7/refund' })
  })
})

describe('settlements domain endpoints', () => {
  it('hits generate/summary/status-transition routes', async () => {
    await fetchPayableSummary()
    expect(last().url).toBe('/settlements/summary')

    await generateSettlement(3)
    expect(last()).toMatchObject({ method: 'POST', url: '/settlements/generate' })
    expect(api.post.mock.calls.at(-1)[1]).toEqual({ supplier_id: 3 })

    await updateSettlement(9, { status: 'paid' })
    expect(last()).toMatchObject({ method: 'PUT', url: '/settlements/9' })
    expect(api.put.mock.calls.at(-1)[1]).toEqual({ status: 'paid', note: '' })
  })
})

describe('purchases domain endpoints', () => {
  it('from_forecast sends product_ids/qty_multiplier (FromForecastIn)', async () => {
    await generateFromForecast({})
    expect(last()).toMatchObject({ method: 'POST', url: '/purchases/from_forecast' })
    expect(api.post.mock.calls.at(-1)[1]).toEqual({ product_ids: [], qty_multiplier: 1.0 })
    await receivePurchase(5, {})
    expect(last()).toMatchObject({ method: 'POST', url: '/purchases/5/receive' })
  })
})

describe('cross-border domain endpoints', () => {
  it('covers four config groups CRUD + landed-cost calc', async () => {
    await dutyRates.list({ country: 'US' })
    expect(last()).toMatchObject({ method: 'GET', url: '/cross-border/duty-rates' })
    await dutyRates.create({ destination_country: 'US', rate: 0.1 })
    expect(last()).toMatchObject({ method: 'POST', url: '/cross-border/duty-rates' })
    await dutyRates.update(11, { rate: 0.2 })
    expect(last()).toMatchObject({ method: 'PUT', url: '/cross-border/duty-rates/11' })
    await dutyRates.remove(11)
    expect(last()).toMatchObject({ method: 'DELETE', url: '/cross-border/duty-rates/11' })

    await calcLandedCost({ product_id: 3, destination_country: 'US', qty: 2 })
    expect(last()).toMatchObject({ method: 'POST', url: '/cross-border/landed-cost' })
  })
})

describe('orders/support/alerts domain endpoints', () => {
  it('csv import takes csv_text; demo sync takes platform/count', async () => {
    await importCsv({ csvText: 'a,b' })
    expect(last()).toMatchObject({ method: 'POST', url: '/orders/import' })
    expect(api.post.mock.calls.at(-1)[1]).toEqual({ csv_text: 'a,b', shop_id: null })

    await syncShopOrders({ platform: 'amazon', count: 3 })
    expect(last()).toMatchObject({ method: 'POST', url: '/orders/sync' })
    expect(api.post.mock.calls.at(-1)[1]).toEqual({ platform: 'amazon', count: 3 })
  })

  it('auto-reply and reply hit the conversation routes', async () => {
    await reply(4, 'hello')
    expect(last()).toMatchObject({ method: 'POST', url: '/support/conversations/4/reply' })
    await requestAutoReply(4)
    expect(last()).toMatchObject({ method: 'POST', url: '/support/conversations/4/auto_reply' })
  })

  it('alerts list passes level/status; rule update merges', async () => {
    await fetchAlerts({ level: 'high', status: 'open' })
    expect(last().config.params).toEqual({ level: 'high', status: 'open' })
    await updateAlertRule(2, { enabled: false, level: 'low' })
    expect(last()).toMatchObject({ method: 'PUT', url: '/alerts/rules/2' })
  })
})
