import { describe, expect, it } from 'vitest'
import {
  TASK_VIEWS, buildTaskHref, dedupeKey, dedupeTasks, filterTasks, filtersFromQuery, normalizeTasks,
  queryFromFilters, safeReturnToTasks, sourceStatusRows, viewCounts,
} from '../src/shared/taskCenterView'
import { UNKNOWN } from '../src/shared/workspaceHomeView'

/**
 * R3-2B §2/§3 待办中心视图模型单测：统一列表/去重（含 store 维度）/视图/URL 筛选。
 *
 * 样本形状**逐字对齐后端真实响应**（backend/app/services/workbench.py build_todo/build_overview
 * + launch_dto.py product_ref/store_ref）：`product={id,title,sku,category}`、
 * `store={id,name,platform}` 均为**对象**（不是字符串）——这是 bug1/bug2 之前未被拦住的根因。
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
      { id: 41, product: { id: 111, title: '弹力带', sku: 'BAND-01', category: '运动' }, store: { id: 201, name: '美国站', platform: 'amazon' }, execution_status: 'RUNNING', progress: { completed: 3, total: 8 }, next_action: { action: 'ADD_MATERIAL', executable: true } },
      { id: 42, product: { id: 112, title: '瑜伽垫', sku: 'MAT-02', category: '运动' }, store: { id: 202, name: '欧洲站', platform: 'ebay' }, execution_status: 'WAITING_EXTERNAL', progress: { completed: 5, total: 8 }, next_action: { action: null, executable: false } },
      { id: 43, product: { id: 113, title: '哑铃', sku: 'DUMB-03', category: '运动' }, store: { id: 203, name: '美国站', platform: 'amazon' }, execution_status: 'BLOCKED', progress: { completed: 1, total: 8 }, blocked_summary: [{ message: '店铺缺少目标国家' }] },
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

  it('in_progress → waiting/blocked 视图；ai_done → done 视图（口径与顶栏一致）', () => {
    const { tasks } = normalizeTasks({ todo: SAMPLE_TODO, overview: SAMPLE_OVERVIEW })
    const waiting = tasks.filter((t) => t.view === 'waiting')
    const blocked = tasks.filter((t) => t.view === 'blocked')
    const done = tasks.filter((t) => t.view === 'done')
    expect(waiting.map((t) => t.id)).toContain('launch:42')
    expect(blocked.map((t) => t.id)).toContain('launch:43')
    expect(done.map((t) => t.id)).toContain('ai_run:9')
    // RUNNING（id41）既非等待外部也非阻断 → 不混入 waiting（bug2 语义污染修复）
    expect(waiting.map((t) => t.id)).not.toContain('launch:41')
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

/**
 * R3-2B 缺陷回归（bug1/bug2/bug4/bug5）：这些断言在修复前会 FAIL——
 * 因为旧 SAMPLE 把 product/store 写成字符串，掩盖了对象渲染/筛选缺陷。
 */
describe('对象字段渲染 / 筛选 / 稳定 id / return_to（R3-2B 缺陷回归）', () => {
  const { tasks } = normalizeTasks({ todo: SAMPLE_TODO, overview: SAMPLE_OVERVIEW })

  it('bug1：product/store 对象 → 人类可读字符串，绝不出现 [object Object]', () => {
    const row = tasks.find((t) => t.id === 'launch:41')
    expect(row.title).toBe('弹力带 的上线流程')
    expect(row.object).toBe('弹力带')
    expect(row.store).toBe('美国站')
    expect(JSON.stringify([row.title, row.object, row.store])).not.toContain('[object Object]')
    // 保留原对象供筛选/跳转
    expect(row.productRaw).toEqual({ id: 111, title: '弹力带', sku: 'BAND-01', category: '运动' })
    expect(row.storeRaw).toEqual({ id: 201, name: '美国站', platform: 'amazon' })
  })

  it('bug2：按真实 store/product 名筛选命中正确行数（修复前对对象求值恒 0）', () => {
    expect(filterTasks(tasks, { view: 'waiting', store: '欧洲站' }).map((t) => t.id)).toEqual(['launch:42'])
    expect(filterTasks(tasks, { view: 'waiting', store: '美国站' })).toHaveLength(0)
    expect(filterTasks(tasks, { view: 'blocked', store: '美国站' }).map((t) => t.id)).toEqual(['launch:43'])
    expect(filterTasks(tasks, { view: 'blocked', product: '哑铃' }).map((t) => t.id)).toEqual(['launch:43'])
  })

  it('bug5：todo 稳定 id 基于业务键、不含下标（列表重排不漂移）', () => {
    const idsA = normalizeTasks({ todo: SAMPLE_TODO, overview: {} }).tasks.map((t) => t.id)
    const reordered = { ...SAMPLE_TODO, items: [...SAMPLE_TODO.items].reverse() }
    const idsB = normalizeTasks({ todo: reordered, overview: {} }).tasks.map((t) => t.id)
    expect([...idsA].sort()).toEqual([...idsB].sort()) // 重排后 id 集合不变（无下标依赖）
    const launchId = idsA.find((id) => id.startsWith('todo:launch'))
    expect(launchId).not.toMatch(/:\d+$/) // 无尾随下标
  })

  it('bug4：buildTaskHref URL 感知合并 return_to（不重复追加、保留 view 筛选、拒绝站外）', () => {
    // 传入链接已含 return_to，且新 return_to 携带 view/store 筛选
    const href = buildTaskHref('/app/launch?return_to=%2Fapp%2Ftasks', '/app/tasks?view=todo&store=美国站')
    const u = new URL(href, 'http://localhost')
    expect(u.pathname).toBe('/app/launch')
    // 只有一个 return_to（旧值被覆盖为规范化后的唯一值），且保留完整筛选
    expect(u.searchParams.getAll('return_to')).toEqual(['/app/tasks?view=todo&store=美国站'])
    expect(buildTaskHref('/app/launch', '//evil.com')).toBe('/app/launch')
    expect(buildTaskHref('', '/app/tasks')).toBe('')
  })
})

/**
 * R3-3 J2 诚实降级：来源状态三态（加载失败 / 未接入 / 0 条 / 正常）+ 回跳安全。
 */
describe('sourceStatusRows（来源状态三态，R3-3 J2）', () => {
  it('ok 计数>0 → 正常；ok 计数=0 → 0 条；skipped → 未接入；failed → 加载失败', () => {
    const rows = sourceStatusRows({
      counts: { launch: 3, action: 0, alert: 0, review: 1 },
      sources: { launch: 'ok', action: 'ok', alert: 'skipped', review: 'failed' },
    })
    const by = Object.fromEntries(rows.map((r) => [r.type, r]))
    expect(by.launch.state).toBe('ok'); expect(by.launch.note).toBe('3 条')
    expect(by.action.state).toBe('empty'); expect(by.action.note).toBe('0 条')
    expect(by.alert.state).toBe('skipped'); expect(by.alert.note).toBe('未接入')
    expect(by.review.state).toBe('failed'); expect(by.review.note).toBe('加载失败')
  })

  it('缺失 sources 不报错，缺类型按 0 条计（不当 0 掩盖）', () => {
    const rows = sourceStatusRows({ counts: {}, sources: {} })
    const by = Object.fromEntries(rows.map((r) => [r.type, r]))
    expect(by.launch.state).toBe('empty')
    expect(rows).toHaveLength(4)
  })
})

describe('detailAvailable（明细可达性，R3-3 J2）', () => {
  const { tasks } = normalizeTasks({ todo: SAMPLE_TODO, overview: SAMPLE_OVERVIEW })

  it('in_progress 上线流程携带 item 级明细 → 可直达处理', () => {
    expect(tasks.find((t) => t.id === 'launch:41')?.detailAvailable).toBe(true)
  })

  it('todo 来源摘要无 item 级明细 → 只能去来源页处理（不得伪造）', () => {
    const launch = tasks.find((t) => t.kind === 'launch' && t.view === 'todo')
    expect(launch.detailAvailable).toBe(false)
    // 仍保留可继续动作：跳到来源页
    expect(launch.link).toBeTruthy()
  })
})

describe('safeReturnToTasks（J2 回跳安全校验）', () => {
  it('放行 /app/tasks（含 query/筛选），否则回退默认待办页', () => {
    expect(safeReturnToTasks('/app/tasks?view=blocked&store=美国站')).toBe('/app/tasks?view=blocked&store=美国站')
    expect(safeReturnToTasks('/app/tasks')).toBe('/app/tasks')
    expect(safeReturnToTasks('')).toBe('/app/tasks')
  })

  it('拒绝站外 / 穿越 / 非待办路径（不依赖全局白名单，避免扩大共享导航事实）', () => {
    expect(safeReturnToTasks('//evil.com')).toBe('/app/tasks')
    expect(safeReturnToTasks('/app/launch/4')).toBe('/app/tasks')
    expect(safeReturnToTasks('/app/tasks/../x')).toBe('/app/tasks')
    expect(safeReturnToTasks('//evil.com', '/app/tasks?view=todo')).toBe('/app/tasks?view=todo')
  })
})
