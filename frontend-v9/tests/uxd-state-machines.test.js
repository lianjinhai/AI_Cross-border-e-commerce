import { describe, expect, it } from 'vitest'
import {
  ORDER_STATUS_LABELS, ORDER_TRANSITIONS, canTransition, nextStatusOptions,
  fulfillmentChain, orderTimeline, parseImportErrors, CSV_IMPORT_HINT,
} from '../src/features/fulfillment/orderStateMachine'
import {
  SETTLE_FLOW, SETTLE_TRANSITIONS, canTransition as canSettle,
  settleActions, settleStatusTag,
} from '../src/features/fulfillment/settlementStateMachine'
import {
  PO_TRANSITIONS, poActions, poStatusTag, canTransition as canPo,
} from '../src/features/supply/purchaseStateMachine'
import {
  refundActions, refundStatusTag, refundTimeline,
} from '../src/features/aftersale/refundStateMachine'

/** UX-D 状态机纯函数锁定：前端流转表必须与后端 allowed 映射一致。 */
describe('order state machine', () => {
  it('mirrors backend allowed transitions', () => {
    expect(ORDER_TRANSITIONS.pending).toEqual(['paid', 'refunded'])
    expect(ORDER_TRANSITIONS.paid).toEqual(['shipped', 'refunded'])
    expect(ORDER_TRANSITIONS.shipped).toEqual(['delivered', 'refunded'])
    expect(ORDER_TRANSITIONS.delivered).toEqual(['refunded'])
    expect(ORDER_TRANSITIONS.refunded).toEqual([])
    expect(canTransition('pending', 'delivered')).toBe(false)
    expect(canTransition('paid', 'shipped')).toBe(true)
    expect(canTransition('', 'paid')).toBe(false)
  })

  it('offers only legal next statuses in the list dropdown', () => {
    expect(nextStatusOptions('paid')).toEqual(['shipped', 'refunded'])
    expect(nextStatusOptions('refunded')).toEqual([])
    expect(nextStatusOptions('unknown')).toEqual([])
  })

  it('marks fulfillment chain with tracking pending note', () => {
    const chain = fulfillmentChain('shipped')
    expect(chain.map((s) => s.state)).toEqual(['done', 'done', 'pending'])
    expect(chain[1].note).toContain('待接入')
    expect(fulfillmentChain('paid')[0].state).toBe('done')
  })

  it('builds order timeline including refunded terminal state', () => {
    const timeline = orderTimeline({ status: 'refunded', created_at: '2026-01-01' })
    expect(timeline[0]).toEqual({ key: 'created', label: '订单创建', state: 'done', time: '2026-01-01' })
    expect(timeline.at(-1)).toMatchObject({ key: 'refunded', state: 'error' })
    expect(orderTimeline({ status: 'pending' }).every((s) => s.key !== 'refunded')).toBe(true)
  })

  it('parses backend import error strings into per-row reports', () => {
    const parsed = parseImportErrors([
      '第2行(SO1001): 金额非法',
      '第5行(无订单号): 订单号为空',
      '随便一行错误',
    ])
    expect(parsed[0]).toEqual({ row: 2, orderNo: 'SO1001', reason: '金额非法' })
    expect(parsed[1]).toEqual({ row: 5, orderNo: '无订单号', reason: '订单号为空' })
    expect(parsed[2]).toEqual({ row: null, orderNo: '', reason: '随便一行错误' })
    expect(parseImportErrors(null)).toEqual([])
    expect(CSV_IMPORT_HINT).toContain('external_no')
  })
})

describe('settlement state machine', () => {
  it('follows pending → confirmed → paid and stops at paid', () => {
    expect(SETTLE_FLOW).toEqual(['pending', 'confirmed', 'paid'])
    expect(canSettle('pending', 'paid')).toBe(false)
    expect(canSettle('confirmed', 'paid')).toBe(true)
    expect(canSettle('paid', 'confirmed')).toBe(false)
  })

  it('exposes transition buttons only for actionable states', () => {
    expect(settleActions('pending')).toEqual([{ status: 'confirmed', label: '确认对账', type: 'primary' }])
    expect(settleActions('confirmed')).toEqual([{ status: 'paid', label: '标记已付款', type: 'success' }])
    expect(settleActions('paid')).toEqual([])
    expect(settleStatusTag('pending').label).toBe('对账中')
    expect(settleStatusTag('weird').label).toBe('weird')
  })
})

describe('purchase state machine', () => {
  it('mirrors backend allowed transitions and row actions', () => {
    expect(PO_TRANSITIONS.draft).toEqual(['submitted', 'cancelled'])
    expect(PO_TRANSITIONS.received).toEqual([])
    expect(canPo('submitted', 'received')).toBe(true)
    expect(poActions('draft').map((a) => a.action)).toEqual(['submit', 'receive', 'cancel'])
    expect(poActions('received')).toEqual([])
    expect(poStatusTag('draft').label).toBe('草稿')
  })
})

describe('refund state machine', () => {
  it('exposes only reachable actions per status/type', () => {
    expect(refundActions({ status: 'pending' }).map((a) => a.action)).toEqual(['approve', 'reject'])
    expect(refundActions({ status: 'approved', type: 'return_refund' }).map((a) => a.action)).toEqual(['receive'])
    expect(refundActions({ status: 'approved', type: 'refund_only' }).map((a) => a.action)).toEqual(['refund'])
    expect(refundActions({ status: 'rejected' })).toEqual([])
  })

  it('renders timeline per refund type and status', () => {
    const only = refundTimeline({ status: 'refunded', type: 'refund_only', created_at: 't1' })
    expect(only.map((s) => s.label)).not.toContain('退货入库')
    expect(only[0].time).toBe('t1')

    const ret = refundTimeline({ status: 'returned', type: 'return_refund' })
    expect(ret.find((s) => s.key === 'returned').state).toBe('done')
    expect(ret.find((s) => s.key === 'refunded').state).toBe('pending')

    const rejected = refundTimeline({ status: 'rejected', type: 'refund_only' })
    expect(rejected.find((s) => s.key === 'review').state).toBe('error')
  })

  it('falls back to raw status labels', () => {
    expect(refundStatusTag('pending').label).toBe('待审核')
    expect(refundStatusTag('weird').type).toBe('info')
  })
})
