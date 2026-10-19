import { afterEach, describe, expect, it, vi } from 'vitest'

/**
 * 首页经营工作台（UX-04a）数据层与纯函数单测。
 *
 * 项目未安装 @vue/test-utils，故只测 composable 暴露的纯函数与数据层；
 * 组件（Dashboard.vue）仅消费这些函数，不重复实现判定。
 */

const client = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}

vi.mock('../src/api', () => ({ default: client }))

const {
  isEmptySection,
  loadOverview,
  loadTodo,
  missingSignals,
  missingSources,
  resolvePersona,
  sectionState,
  todoGroups,
} = await import('../src/composables/workbenchTodo')

afterEach(() => {
  client.get.mockReset()
  client.post.mockReset()
  client.put.mockReset()
  client.patch.mockReset()
  client.delete.mockReset()
})

// ---------------------------------------------------------------- 数据层（只读）

describe('workbench data layer', () => {
  it('loadTodo/loadOverview 走 GET，且不发起任何写请求', async () => {
    client.get.mockResolvedValue({ data: { items: [], counts: {}, sources: {} } })
    await loadTodo()
    await loadOverview()
    expect(client.get).toHaveBeenCalledWith('/workbench/todo', expect.anything())
    expect(client.get).toHaveBeenCalledWith('/workbench/overview', expect.anything())
    expect(client.post).not.toHaveBeenCalled()
    expect(client.put).not.toHaveBeenCalled()
    expect(client.patch).not.toHaveBeenCalled()
    expect(client.delete).not.toHaveBeenCalled()
  })

  it('loadTodo 返回响应体 data', async () => {
    client.get.mockResolvedValue({ data: { items: [{ type: 'launch' }], counts: { launch: 1 } } })
    expect(await loadTodo()).toEqual({ items: [{ type: 'launch' }], counts: { launch: 1 } })
  })
})

// ---------------------------------------------------------------- todoGroups

describe('todoGroups', () => {
  it('按 type 分组，count=条目数、total=数量之和', () => {
    const groups = todoGroups([
      { type: 'launch', count: 2 },
      { type: 'launch', count: 3 },
      { type: 'alert', count: 4 },
    ])
    const launch = groups.find((g) => g.type === 'launch')
    expect(launch.count).toBe(2)
    expect(launch.total).toBe(5)
    expect(groups.find((g) => g.type === 'alert').total).toBe(4)
  })

  it('已知类型按固定顺序，未知类型排在已知之后', () => {
    const groups = todoGroups([
      { type: 'zzz', count: 1 },
      { type: 'alert', count: 1 },
      { type: 'launch', count: 1 },
    ])
    expect(groups.map((g) => g.type)).toEqual(['launch', 'alert', 'zzz'])
  })

  it('空/非数组输入返回空分组', () => {
    expect(todoGroups([])).toEqual([])
    expect(todoGroups(null)).toEqual([])
  })
})

// ---------------------------------------------------------------- resolvePersona

describe('resolvePersona', () => {
  const base = {
    has_sales_shop: false, sales_shop_count: 0,
    has_factory: false, factory_match_count: 0,
    has_1688_credential: false, member_count: 1, order_count_30d: 0,
  }

  it('信号缺失（null / 非对象）→ GENERIC', () => {
    expect(resolvePersona(null)).toBe('GENERIC')
    expect(resolvePersona(undefined)).toBe('GENERIC')
    expect(resolvePersona('x')).toBe('GENERIC')
    expect(resolvePersona({})).toBe('GENERIC')
  })

  it('关键判别位缺失（非布尔）→ GENERIC', () => {
    expect(resolvePersona({ ...base, has_sales_shop: null })).toBe('GENERIC')
    expect(resolvePersona({ ...base, has_factory: null })).toBe('GENERIC')
  })

  it('无店无厂 → A（单人）/ F（多人）', () => {
    expect(resolvePersona({ ...base, member_count: 1 })).toBe('A')
    expect(resolvePersona({ ...base, member_count: 3 })).toBe('F')
  })

  it('仅有工厂 → C', () => {
    expect(resolvePersona({ ...base, has_factory: true })).toBe('C')
    expect(resolvePersona({ ...base, has_factory: false, factory_match_count: 2 })).toBe('C')
  })

  it('店+厂无订单 → B；店+厂有订单 → D', () => {
    const both = { ...base, has_sales_shop: true, has_factory: true }
    expect(resolvePersona({ ...both, order_count_30d: 0 })).toBe('B')
    expect(resolvePersona({ ...both, order_count_30d: 5 })).toBe('D')
  })
})

// ---------------------------------------------------------------- sectionState

describe('sectionState', () => {
  it('空段 + 对应源失败 → error', () => {
    expect(sectionState([], false, { launch: 'failed' })).toBe('error')
    expect(sectionState(null, false, { launch: 'failed' })).toBe('error')
  })

  it('空段 + 无失败源 → empty', () => {
    expect(sectionState([], false, { launch: 'ok' })).toBe('empty')
    expect(sectionState(null, true, { launch: 'ok' })).toBe('empty')
  })

  it('非空段 + partial → partial', () => {
    expect(sectionState([{ id: 1 }], true, { launch: 'ok' })).toBe('partial')
  })

  it('非空段 + 非 partial → ready', () => {
    expect(sectionState([{ id: 1 }], false, { launch: 'ok' })).toBe('ready')
  })

  it('对象形态（含 items/total/count）正确判定空', () => {
    expect(isEmptySection({ items: [], total: 0 })).toBe(true)
    expect(isEmptySection({ items: [{ id: 1 }], total: 1 })).toBe(false)
    expect(isEmptySection({ count: 0 })).toBe(true)
    expect(isEmptySection({ count: 2 })).toBe(false)
  })
})

// ---------------------------------------------------------------- 缺失源/信号

describe('missing helpers', () => {
  it('missingSources 只挑 failed 的源', () => {
    expect(missingSources({ bi: 'ok', alert: 'failed', todo: 'skipped' })).toEqual(['alert'])
  })

  it('missingSignals 挑 null/undefined 的键', () => {
    expect(missingSignals({ a: 1, b: null, c: undefined })).toEqual(['b', 'c'])
  })
})
