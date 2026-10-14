import { describe, expect, it } from 'vitest'
import {
  TASK_VIEWS, dedupeKey, dedupeTasks, filterTasks, filtersFromQuery, normalizeTasks, queryFromFilters, viewCounts,
} from '../src/shared/taskCenterView'
import { UNKNOWN } from '../src/shared/workspaceHomeView'

/**
 * R3-2B §2/§3 待办中心视图模型单测：统一列表/去重（含 store 维度）/视图/URL 筛选。
 * 样本形状逐字来自 backend/app/services/workbench.py（build_todo/build_overview）。
 */

const SAMPLE_TODO = {
  items: [
    { type: 'launch', title: '待你处理的上线流程', count: 5, severity: 'high', due_at: null, route: { path: '/launch', return_to: '/launch?mine=true' }, ref: null },
    { type: 'review', title: '待人工复核的 Listing', count: 1, severity: 'high', due_at: null, route: { path: '/compliance-workbench', return_to: null }, ref: null },
  ],
  counts: { launch: 5, action: 0, alert: 0, review: 1 },
  partial: false,
  sources: { launch: 'ok', action: 'ok', alert: 'ok', review: 'ok' },
}

const SAMPLE_OVERVIEW = {
  sources: { launch: 'ok', workflow: 'ok' },
  sections: {
    in_progress: [
      { id: 41, product: '弹力带', store: '美国站', execution_status: 'RUNNING', progress: { completed: 3, total: 8 }, next_action: { action: 'ADD_MATERIAL', executable: true } },
      { id: 42, product: '瑜伽垫', store: '欧洲站', execution_status: 'WAITING_EXTERNAL', progress: { completed: 5, total: 8 }, next_action: { action: null, executable: false } },
      { id: 43, product: '哑铃', store: '美国站', execution_status: 'BLOCKED', progress: { completed: 1, total: 8 }, blocked_summary: [{ message: '店铺缺少目标国家' }] },
    ],
    ai_done: { count: 1, items: [{ id: 9, title: '自动标准化', status: 'success', finished_at: '2026-01-02 10:00:00' }] },
  },
}

describe('filtersFromQuery / queryFromFilters（URL 单一事实源）', () => {
  it('非法 view 退回默认 todo；空值不写 query', () => {
    expect(filtersFromQuery({ view: 'bogus' }).view).toBe('todo')
    expect(filtersFromQuery({ view: 'waiting', product: 'P' })).toEqual({ view: 'waiting', product: 'P', store: '', type: '', due: '' })
    expect(queryFromFilters({ view: 'todo', product: '', store: 'S' })).toEqual({ store: 'S' })
  })

  it('往返一致（携带 view 与筛选）', () => {
    const filters = { view: 'blocked', product: '哑铃', store: '美国站', type: 'launch', due: '' }
    expect(filtersFromQuery(queryFromFilters(filters))).toEqual(filters)
  })
})

describe('dedupeTasks / dedupeKey（含 store 维度，不合并不同 Store）', () => {
  it('相同去重键合并并累加计数、保留来源', () => {
    const merged = dedupeTasks([
      { kind: 'launch', store: 'S1', object: 'P', title: 'x', source: 'a' },
      { kind: 'launch', store: 'S1', object: 'P', title: 'x', source: 'b' },
    ])
    expect(merged).toHaveLength(1)
    expect(merged[0].mergedCount).toBe(2)
    expect(merged[0].sources.sort()).toEqual(['a', 'b'])
  })

  it('同商品不同 Store → 不合并（独立业务事项）', () => {
    const out = dedupeTasks([
      { kind: 'launch', store: '美国站', object: '弹力带', title: 'x', source: 'a' },
      { kind: 'launch', store: '欧洲站', object: '弹力带', title: 'x', source: 'a' },
    ])
    expect(out).toHaveLength(2)
  })

  it('dedupeKey 显式含 store', () => {
    expect(dedupeKey({ kind: 'launch', store: 'S1', object: 'P', title: 't' }))
      .not.toBe(dedupeKey({ kind: 'launch', store: 'S2', object: 'P', title: 't' }))
  })
})

describe('normalizeTasks（三类来源统一 + 诚实缺口）', () => {
  it('todo 摘要 → 默认视图，并标注明细缺口（不捏造责任人）', () => {
    const { tasks, unavailable } = normalizeTasks({ todo: SAMPLE_TODO, overview: SAMPLE_OVERVIEW })
    const launch = tasks.find((t) => t.kind === 'launch' && t.view === 'todo')
    expect(launch.owner).toBe(UNKNOWN)
    expect(launch.object).toBe(UNKNOWN)
    expect(launch.gaps.length).toBeGreaterThan(0)
    expect(unavailable).toEqual([])
  })

  it('in_progress → waiting/blocked 视图；ai_done → done 视图', () => {
    const { tasks } = normalizeTasks({ todo: SAMPLE_TODO, overview: SAMPLE_OVERVIEW })
    const waiting = tasks.filter((t) => t.view === 'waiting')
    const blocked = tasks.filter((t) => t.view === 'blocked')
    const done = tasks.filter((t) => t.view === 'done')
    expect(waiting.map((t) => t.id)).toContain('launch:42')
    expect(blocked.map((t) => t.id)).toContain('launch:43')
    expect(done.map((t) => t.id)).toContain('ai_run:9')
  })

  it('来源失败 → 标记不可用，不产生该来源任务（不得当 0/空）', () => {
    const { tasks, unavailable } = normalizeTasks({
      todo: { items: [], sources: { launch: 'failed', action: 'ok', alert: 'ok', review: 'ok' } },
      overview: { sources: { launch: 'failed', workflow: 'ok' }, sections: {} },
    })
    expect(unavailable).toContain('workbench.todo')
    expect(unavailable).toContain('overview.launch')
    expect(tasks.filter((t) => t.view === 'todo')).toHaveLength(0)
  })
})

describe('filterTasks / viewCounts（筛选与视图计数）', () => {
  const { tasks } = normalizeTasks({ todo: SAMPLE_TODO, overview: SAMPLE_OVERVIEW })

  it('按 view 过滤（默认 todo）', () => {
    expect(filterTasks(tasks, { view: 'waiting' }).every((t) => t.view === 'waiting')).toBe(true)
    expect(filterTasks(tasks, { view: 'blocked' }).map((t) => t.id)).toEqual(['launch:43'])
  })

  it('按 store / product / type 过滤', () => {
    expect(filterTasks(tasks, { view: 'blocked', store: '美国站' })).toHaveLength(1)
    expect(filterTasks(tasks, { view: 'blocked', store: '欧洲站' })).toHaveLength(0)
    expect(filterTasks(tasks, { view: 'todo', type: 'review' })).toHaveLength(1)
  })

  it('viewCounts 累加后端 count（缺失按 1），与首屏计数条口径一致', () => {
    const counts = viewCounts(tasks)
    expect(counts.todo).toBe(6) // launch(5) + review(1)
    expect(counts.done).toBe(1)
    expect(Object.keys(counts).sort()).toEqual(TASK_VIEWS.map((v) => v.key).sort())
  })
})
