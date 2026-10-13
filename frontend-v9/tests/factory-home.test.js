import { describe, expect, it } from 'vitest'
import {
  TODO_GROUPS,
  hasTodoSource,
  todoCounts,
  homeStateCode,
  emptyHomeCopy,
  skuSidebarCount,
} from '../src/shared/factoryHome'

/**
 * 工厂门户首页纯函数回归（蓝图 R1 包 3 · FP-01，§B.3 / 差距 §2.10）。
 *
 * 红线：待办数据源 factory_network portal 未核 → 未接入落"暂无任务"空态，
 * 禁止编造待办计数；只收工厂身份绑定数据。
 */
describe('hasTodoSource — 待办数据源判定', () => {
  it('缺 todos 字段 / 空响应 → 未接入', () => {
    expect(hasTodoSource(null)).toBe(false)
    expect(hasTodoSource({ supplier: {} })).toBe(false)
    expect(hasTodoSource({ todos: 'not-an-array' })).toBe(false)
  })

  it('显式含 todos 数组（含空数组）→ 已接入', () => {
    expect(hasTodoSource({ todos: [] })).toBe(true)
    expect(hasTodoSource({ todos: [{ kind: 'quote' }] })).toBe(true)
  })
})

describe('todoCounts — 待办分组计数', () => {
  it('未接数据源 → 全 0 + connected=false（不推计数）', () => {
    const c = todoCounts({ supplier: {} })
    expect(c).toEqual({ quote: 0, stocking: 0, labeling: 0, total: 0, connected: false })
  })

  it('按 kind 归类计数，未知 kind 不计入', () => {
    const c = todoCounts({ todos: [
      { kind: 'quote' }, { kind: 'quote' },
      { kind: 'stocking' },
      { kind: 'labeling' }, { kind: 'labeling' }, { kind: 'unknown' },
    ] })
    expect(c.quote).toBe(2)
    expect(c.stocking).toBe(1)
    expect(c.labeling).toBe(2)
    expect(c.total).toBe(5)
    expect(c.connected).toBe(true)
  })

  it('空 todos → 全 0 但 connected=true', () => {
    const c = todoCounts({ todos: [] })
    expect(c.total).toBe(0)
    expect(c.connected).toBe(true)
  })
})

describe('homeStateCode — 首页主态（11 态码）', () => {
  it('loading → LOADING；error → ERROR', () => {
    expect(homeStateCode(true, false, {})).toBe('LOADING')
    expect(homeStateCode(false, true, {})).toBe('ERROR')
  })

  it('已接数据源且有待办 → ready', () => {
    expect(homeStateCode(false, false, { connected: true, total: 3 })).toBe('ready')
  })

  it('未接数据源 / 零待办 → EMPTY_NEW（"暂无任务"空态，不误报 PARTIAL）', () => {
    expect(homeStateCode(false, false, { connected: false, total: 0 })).toBe('EMPTY_NEW')
    expect(homeStateCode(false, false, { connected: true, total: 0 })).toBe('EMPTY_NEW')
  })
})

describe('factoryHome — 文案与侧栏', () => {
  it('空态文案集中产出"暂无任务"', () => {
    const copy = emptyHomeCopy()
    expect(copy.title).toBe('暂无任务')
    expect(copy.detail).toContain('尚未接入')
  })

  it('待办分组字典 = 报价/备货/贴标', () => {
    expect(TODO_GROUPS.map((g) => g.label)).toEqual(['报价', '备货', '贴标'])
  })

  it('SKU 侧栏计数：非数组归 0', () => {
    expect(skuSidebarCount(null)).toBe(0)
    expect(skuSidebarCount([{}, {}, {}])).toBe(3)
  })
})
