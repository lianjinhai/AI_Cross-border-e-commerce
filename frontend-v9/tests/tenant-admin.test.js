import { describe, expect, it } from 'vitest'

import {
  fmt, isExpired, n, normalizeList, planTag, platformLabel,
  purgeResultText, statCardsFromOverview, statusTag,
} from '../src/composables/tenantAdmin'

describe('徽标查表（plan/status/platform）', () => {
  it('planTag 查表；未知值退化 info', () => {
    expect(planTag('pro')).toEqual({ text: '专业版', type: 'primary' })
    expect(planTag('mystery')).toEqual({ text: 'mystery', type: 'info' })
    expect(planTag('')).toEqual({ text: '—', type: 'info' })
  })

  it('statusTag：active/suspended；未知退化', () => {
    expect(statusTag('active')).toEqual({ text: '正常', type: 'success' })
    expect(statusTag('suspended')).toEqual({ text: '停用', type: 'danger' })
    expect(statusTag(undefined)).toEqual({ text: '未知', type: 'info' })
  })

  it('platformLabel：查表命中与原样透传', () => {
    expect(platformLabel('1688')).toBe('1688（阿里巴巴）')
    expect(platformLabel('temu')).toBe('temu')
    expect(platformLabel('')).toBe('—')
  })
})

describe('isExpired（授权到期判定）', () => {
  const now = new Date('2025-06-15T00:00:00Z').getTime()

  it('缺失/非法日期一律未过期（不误伤）', () => {
    expect(isExpired(null, now)).toBe(false)
    expect(isExpired('', now)).toBe(false)
    expect(isExpired('not-a-date', now)).toBe(false)
  })

  it('过去时点过期、未来时点未过期；边界同一时刻不算过期（与后端严格 < 一致）', () => {
    expect(isExpired('2025-06-14T00:00:00Z', now)).toBe(true)
    expect(isExpired('2025-06-16T00:00:00Z', now)).toBe(false)
    expect(isExpired('2025-06-15T00:00:00Z', now)).toBe(false)
  })
})

describe('数字与结果文本化', () => {
  it('n：null/undefined → 0，其余原样', () => {
    expect(n(null)).toBe(0)
    expect(n(undefined)).toBe(0)
    expect(n(5)).toBe(5)
  })

  it('fmt：null → —，数字千分位', () => {
    expect(fmt(null)).toBe('—')
    expect(fmt(12345)).toBe('12,345')
  })

  it('purgeResultText：对象 → "k v，k v"；标量字符串化；null → 空串', () => {
    expect(purgeResultText({ products: 3, orders: 12 })).toBe('products 3，orders 12')
    expect(purgeResultText('ok')).toBe('ok')
    expect(purgeResultText(null)).toBe('')
  })
})

describe('statCardsFromOverview（6 卡顺序冻结）', () => {
  it('总览字段一一映射，缺失字段显示 —', () => {
    const cards = statCardsFromOverview({ tenants: 2, active: 1, suspended: 1, expiring_in_30d: 0, users: 9, orders_total: 100 })
    expect(cards.map((c) => c.label)).toEqual(
      ['租户总数', '正常租户', '停用租户', '30 天内到期', '用户总数', '订单总数'])
    expect(cards[4].value).toBe('9')
  })

  it('空总览全部显示 —（不伪造数值）', () => {
    expect(statCardsFromOverview({})[0].value).toBe('—')
  })
})

describe('normalizeList（列表三态归一）', () => {
  it('裸数组 / {items} / {tenants} / {logs} 归一为 {items,total}', () => {
    expect(normalizeList([1, 2])).toEqual({ items: [1, 2], total: 2 })
    expect(normalizeList({ items: [1], total: 7 })).toEqual({ items: [1], total: 7 })
    expect(normalizeList({ tenants: [{ id: 1 }] })).toEqual({ items: [{ id: 1 }], total: 1 })
    expect(normalizeList({ logs: [] })).toEqual({ items: [], total: 0 })
  })

  it('空输入得到空列表（不抛错）', () => {
    expect(normalizeList(null)).toEqual({ items: [], total: 0 })
  })
})
