import { describe, expect, it } from 'vitest'
import { filterTasks, normalizeTasks } from '../src/shared/taskCenterView'

/**
 * R3-2B 缺陷回归**证据**（bug1/bug2/bug5）：证明新增的回归断言「修复前 FAIL / 修复后 PASS」，
 * 即它们真能拦住缺陷，而不是永真的空断言。
 *
 * 方法：对同一份**后端真实形状** fixture（product/store 为对象），同时计算
 *   - OLD：修复前的旧表达式（直接插值对象 / 对对象 includes / 下标 id）
 *   - NEW：修复后的纯函数输出
 * 断言 OLD 不满足（=修复前会 FAIL），NEW 满足（=修复后 PASS）。
 */

const OVERVIEW = {
  sources: { launch: 'ok', workflow: 'ok' },
  sections: {
    in_progress: [
      { id: 41, product: { id: 111, title: '弹力带', sku: 'BAND-01' }, store: { id: 201, name: '美国站', platform: 'amazon' }, execution_status: 'RUNNING' },
      { id: 42, product: { id: 112, title: '瑜伽垫', sku: 'MAT-02' }, store: { id: 202, name: '欧洲站', platform: 'ebay' }, execution_status: 'WAITING_EXTERNAL' },
    ],
    ai_done: { count: 0, items: [] },
  },
}
const TODO = {
  items: [{ type: 'launch', title: '待你处理的上线流程', count: 5, severity: 'high', route: { path: '/launch' }, ref: null }],
  counts: { launch: 5 },
  sources: { launch: 'ok', action: 'ok', alert: 'ok', review: 'ok' },
}

describe('R3-2B 回归证据：断言真能拦 bug1/bug2/bug5', () => {
  const { tasks } = normalizeTasks({ todo: TODO, overview: OVERVIEW })
  const row = tasks.find((t) => t.id === 'launch:41')
  const ip41 = OVERVIEW.sections.in_progress[0]
  const ip42 = OVERVIEW.sections.in_progress[1]

  it('bug1：旧表达式产生 [object Object]（修复前 FAIL），新输出人类可读（修复后 PASS）', () => {
    const oldTitle = `${ip41.product || '商品'} 的上线流程` // 旧逻辑
    expect(oldTitle).toContain('[object Object]')            // 修复前：会渲染成 [object Object] → 旧断言 FAIL
    expect(row.title).not.toContain('[object Object]')       // 修复后：PASS
    expect(row.title).toBe('弹力带 的上线流程')
    expect(row.object).toBe('弹力带')
    expect(row.store).toBe('美国站')
  })

  it('bug2：旧逻辑对对象 includes 恒 false（修复前筛选恒 0 → FAIL），新逻辑命中 1 行（PASS）', () => {
    const oldStoreHit = String(ip42.store).toLowerCase().includes('欧洲站'.toLowerCase())
    expect(oldStoreHit).toBe(false) // 旧逻辑：对象 → 恒 false → 修复前筛选 0 行（FAIL）
    expect(filterTasks(tasks, { view: 'waiting', store: '欧洲站' }).map((t) => t.id)).toEqual(['launch:42'])
  })

  it('bug5：旧下标记 id 命中 /:\\d+$/（修复前 FAIL），新业务键 id 不命中（PASS）', () => {
    const oldTodoId = 'todo:launch:0' // 旧逻辑（基于下标）
    expect(/:\d+$/.test(oldTodoId)).toBe(true) // 修复前：id 漂移 → 旧断言 FAIL
    const newTodoId = tasks.find((t) => t.id.startsWith('todo:launch'))?.id
    expect(/:\d+$/.test(newTodoId || '')).toBe(false) // 修复后：PASS
    expect(newTodoId).toBe('todo:launch:待你处理的上线流程')
  })
})
