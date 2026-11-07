import { describe, expect, it } from 'vitest'

import {
  blockerHeadline,
  blockerViews,
  repairView,
  unrepairableCount,
} from '../src/shared/launchRepair'

/** 后端 repair_action 的典型形态。 */
function repair(overrides = {}) {
  return {
    kind: 'ACTION',
    label: '补充商品资料',
    path: '/app/products/42',
    action: 'COMPLETE_DATA',
    connected: true,
    reason: '',
    ...overrides,
  }
}

function blocker(overrides = {}) {
  return {
    code: 'MISSING_DATA',
    message: '缺少可发布图片',
    step_code: 'INFORMATION',
    owner_actor: 'USER',
    evidence_refs: [],
    repair_action: repair(),
    ...overrides,
  }
}

describe('repairView', () => {
  it('已接通的补齐入口可跳转，不显示未接入提示', () => {
    const view = repairView(repair())
    expect(view.canNavigate).toBe(true)
    expect(view.path).toBe('/app/products/42')
    expect(view.note).toBe('')
  })

  it('未接入但有真实页面时仍给入口，同时标注未接入原因', () => {
    const view = repairView(repair({
      kind: 'ROUTE', path: '/app/pricing', action: null, connected: false,
      reason: '核价领域服务未接入（B03–B09）',
    }))
    expect(view.canNavigate).toBe(true)
    expect(view.connected).toBe(false)
    expect(view.note).toContain('未接入')
  })

  it('UNAVAILABLE 形态不给跳转按钮', () => {
    const view = repairView(repair({ kind: 'UNAVAILABLE', path: '/app/launch', connected: false }))
    expect(view.canNavigate).toBe(false)
  })

  it('缺少补齐入口时降级为「暂无补齐入口」而不是空白', () => {
    const view = repairView(null)
    expect(view.kind).toBe('UNAVAILABLE')
    expect(view.label).toBe('暂无补齐入口')
    expect(view.canNavigate).toBe(false)
    expect(view.note).toContain('待办')
  })

  it('忽略不安全的路径，不把外部地址当跳转目标', () => {
    expect(repairView(repair({ path: 'https://evil.example.com' })).canNavigate).toBe(false)
    expect(repairView(repair({ path: '/other/place' })).canNavigate).toBe(false)
  })

  it('未知 kind 按未接入处理', () => {
    expect(repairView(repair({ kind: 'WAT' })).kind).toBe('UNAVAILABLE')
  })
})

describe('blockerView / blockerViews', () => {
  it('保留阻断码与原因，并带上补齐入口视图', () => {
    const view = blockerViews([blocker()])[0]
    expect(view.code).toBe('MISSING_DATA')
    expect(view.message).toBe('缺少可发布图片')
    expect(view.repair.canNavigate).toBe(true)
  })

  it('脏数据被丢弃，不抛错', () => {
    expect(blockerViews([null, 3, 'x', blocker()])).toHaveLength(1)
    expect(blockerViews()).toEqual([])
    expect(blockerViews('nope')).toEqual([])
  })

  it('缺字段的阻断项也给可用默认值', () => {
    const view = blockerViews([{}])[0]
    expect(view.code).toBe('MISSING_DATA')
    expect(view.message).toBe('未提供阻断原因')
    expect(view.repair.label).toBe('暂无补齐入口')
  })
})

describe('blockerHeadline / unrepairableCount', () => {
  it('无阻断时返回空串', () => {
    expect(blockerHeadline([])).toBe('')
  })

  it('概括里带条数与首条原因', () => {
    expect(blockerHeadline([blocker(), blocker({ message: '图片授权过期' })]))
      .toBe('阻断 2 项：缺少可发布图片')
  })

  it('统计「点了也补不完」的项数', () => {
    const blocked = [
      blocker(),
      blocker({ repair_action: repair({ connected: false, reason: '未接入' }) }),
      blocker({ repair_action: null }),
    ]
    expect(unrepairableCount(blocked)).toBe(2)
  })
})
