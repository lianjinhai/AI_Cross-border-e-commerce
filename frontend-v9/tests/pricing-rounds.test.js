/**
 * M2-A 报价轮次视图单测：币种绑定、门槛文案、只读语义。
 * 组件层没装 @vue/test-utils，所以断言全部落在纯函数上。
 */
import { describe, expect, it } from 'vitest'

import {
  ROUND_ACTION_LABELS,
  priceGateMessage,
  roundMoney,
  roundPercent,
  roundRows,
  roundSummary,
  roundView,
} from '../src/shared/pricingRounds'

describe('roundMoney 币种绑定', () => {
  it('有币种就绑定币种代码', () => {
    expect(roundMoney(19.99, 'USD')).toBe('USD 19.99')
    expect(roundMoney(120, 'cny')).toBe('CNY 120')
  })

  it('没有币种一律显 —，绝不默认 $', () => {
    expect(roundMoney(19.99, '')).toBe('—')
    expect(roundMoney(19.99, null)).toBe('—')
    expect(roundMoney(19.99, undefined)).toBe('—')
    expect(roundMoney(19.99, 'USD')).not.toContain('$')
  })

  it('有币种但金额缺失时显「USD —」，不把空值当 0', () => {
    expect(roundMoney(null, 'USD')).toBe('USD —')
    expect(roundMoney('', 'USD')).toBe('USD —')
  })
})

describe('roundPercent', () => {
  it('0-1 小数转百分数（一位小数）', () => {
    expect(roundPercent(0.155)).toBe('15.5%')
    expect(roundPercent(0)).toBe('0.0%')
  })

  it('空值显 —', () => {
    expect(roundPercent(null)).toBe('—')
    expect(roundPercent(undefined)).toBe('—')
  })
})

describe('priceGateMessage 低价门禁文案', () => {
  it('低于门槛时给出两个具体数字', () => {
    const message = priceGateMessage(0.08, 0.15)
    expect(message).toBe('售价毛利 8.0% 低于最低要求 15.0%，不能提交核价')
  })

  it('达标或数据缺失时不显示红条', () => {
    expect(priceGateMessage(0.15, 0.15)).toBeNull()
    expect(priceGateMessage(0.42, 0.15)).toBeNull()
    expect(priceGateMessage(null, 0.15)).toBeNull()
    expect(priceGateMessage(0.2, undefined)).toBeNull()
  })
})

describe('roundView', () => {
  const row = {
    id: 7,
    round_no: 2,
    action: 'COUNTER',
    price: 109,
    currency: 'EUR',
    margin: 0.302,
    min_margin: 0.15,
    margin_ok: true,
    decision: { decision: 'COUNTER' },
    created_by: 1,
    created_at: '2026-11-07T10:00:00',
  }

  it('翻出可直接渲染的字段', () => {
    const view = roundView(row)
    expect(view.actionLabel).toBe(ROUND_ACTION_LABELS.COUNTER)
    expect(view.priceText).toBe('EUR 109')
    expect(view.marginText).toBe('30.2%')
    expect(view.floorText).toBe('15.0%')
    expect(view.gateOk).toBe(true)
    expect(view.gateLabel).toBe('过门槛')
    expect(view.decisionLabel).toBe('未决')
    expect(view.source).toBe('本地轮次')
  })

  it('被门禁拒绝的轮次显式标红，且不冒充已接受', () => {
    const view = roundView({ ...row, margin_ok: false, margin: 0.01, decision: {} })
    expect(view.gateOk).toBe(false)
    expect(view.gateLabel).toBe('低于门槛')
    expect(view.decisionLabel).toBe('未决')
  })

  it('接受轮次显式标已接受', () => {
    expect(roundView({ ...row, action: 'ACCEPT', decision: { decision: 'ACCEPT' } }).decisionLabel)
      .toBe('已接受')
  })

  it('空行不崩，全部落到占位符', () => {
    const view = roundView({})
    expect(view.actionLabel).toBe('—')
    expect(view.priceText).toBe('—')
    expect(view.gateLabel).toBe('—')
  })
})

describe('roundRows / roundSummary', () => {
  const rows = [
    { id: 3, round_no: 3, action: 'ACCEPT', price: 99, currency: 'USD', margin: 0.4, min_margin: 0.15, margin_ok: true, decision: { decision: 'ACCEPT' } },
    { id: 2, round_no: 2, action: 'COUNTER', price: 109, currency: 'USD', margin: 0.42, min_margin: 0.15, margin_ok: true, decision: { decision: 'COUNTER' } },
    { id: 1, round_no: 1, action: 'REPORT', price: 99, currency: 'USD', margin: 0.4, min_margin: 0.15, margin_ok: true, decision: {} },
  ]

  it('保持后端返回的顺序（新→旧），不改写轮次', () => {
    expect(roundRows(rows).map((r) => r.roundNo)).toEqual([3, 2, 1])
  })

  it('非数组输入返回空列表', () => {
    expect(roundRows(null)).toEqual([])
    expect(roundRows(undefined)).toEqual([])
  })

  it('汇总能看出总轮次与是否已接受', () => {
    const summary = roundSummary(rows)
    expect(summary.total).toBe(3)
    expect(summary.accepted).toBe(true)
    expect(summary.latest.roundNo).toBe(3)
    expect(summary.latestGateOk).toBe(true)
    expect(roundSummary([]).latest).toBeNull()
  })
})
