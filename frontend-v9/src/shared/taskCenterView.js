/**
 * 待办中心视图模型（R3-2B §2/§3）：统一任务列表 + 视图 + 筛选 + 去重（纯函数，供 vitest 直测）。
 *
 * 契约来源（现场核对后端源码）：
 * - `GET /workbench/todo`：items 为**来源分组摘要**（type/title/count/severity/due_at/route/ref），
 *   目前 ref 为空、无逐条明细实例 → 前端**不得捏造**负责人/截止时间，如实标注缺口。
 * - `GET /workbench/overview.sections.in_progress`：进行中上线（含 product/store/execution_status/next_action/market）。
 * - `GET /workbench/overview.sections.ai_done.items`：近 24h 完成的 AI 运行。
 *
 * 红线：缺失显示 UNKNOWN='—'，不当 0；来源失败 → 视图标注不可用；不同 Store 的独立事项不合并。
 */

import { UNKNOWN, safeInternalPath, taskLink } from './workspaceHomeView'

/** 视图定义（默认「需要我处理」）。 */
export const TASK_VIEWS = [
  { key: 'todo', label: '需要我处理' },
  { key: 'waiting', label: '等待外部' },
  { key: 'blocked', label: '受阻' },
  { key: 'done', label: '已完成' },
]

const WAITING_STATES = new Set(['WAITING_EXTERNAL', 'WAITING_PLATFORM', 'WAITING_EXTERNAL_FEEDBACK'])
const BLOCKED_STATES = new Set(['BLOCKED', 'FAILED'])

const TYPE_LABELS = { launch: '上线流程', action: '待审批动作', alert: '风险告警', review: '人工复核', ai_run: 'AI 运行' }
export const typeLabel = (kind) => TYPE_LABELS[kind] || kind || '任务'

/** 稳定任务标识：kind|store|object|ref/title（**含 store 维度**，不同店铺不合并）。 */
export function dedupeKey(task = {}) {
  const ref = task.ref == null ? '' : String(task.ref)
  const store = task.store && task.store !== UNKNOWN ? String(task.store) : ''
  return [task.kind || 'x', store, task.object && task.object !== UNKNOWN ? task.object : '',
    ref || task.title || ''].join('|')
}

/** 跨域去重：相同去重键只保留一条，其余计数累加（保留来源追溯）。 */
export function dedupeTasks(items = []) {
  const list = Array.isArray(items) ? items.filter((i) => i && typeof i === 'object') : []
  const seen = new Map()
  const out = []
  for (const item of list) {
    const key = dedupeKey(item)
    if (seen.has(key)) {
      const kept = seen.get(key)
      kept.mergedCount = (kept.mergedCount || 1) + 1
      if (!kept.sources.includes(item.source)) kept.sources.push(item.source)
      continue
    }
    const clone = { ...item, mergedCount: 1, sources: [item.source].filter(Boolean) }
    seen.set(key, clone)
    out.push(clone)
  }
  return out
}

/** overview.sections.in_progress 行 → 统一任务项（等待外部 / 受阻）。 */
function fromInProgress(rows, { waitingExternal = true } = {}) {
  if (!Array.isArray(rows)) return []
  return rows.map((row, i) => {
    const status = row?.execution_status || ''
    const view = BLOCKED_STATES.has(status) ? 'blocked'
      : (WAITING_STATES.has(status) ? 'waiting' : (waitingExternal ? 'waiting' : 'blocked'))
    const reason = row?.blocked_summary?.[0]?.message
      || row?.next_action?.reason
      || (BLOCKED_STATES.has(status) ? '执行受阻' : UNKNOWN)
    const progress = row?.progress
    return {
      id: `launch:${row?.id ?? i}`,
      kind: 'launch',
      view,
      title: `${row?.product || '商品'} 的上线流程`,
      object: row?.product || UNKNOWN,
      store: row?.store || UNKNOWN,
      reason,
      owner: row?.owner?.role_hint || row?.owner?.actor || UNKNOWN,
      time: row?.created_at || UNKNOWN,
      severity: BLOCKED_STATES.has(status) ? 'high' : 'mid',
      progress: progress ? `${progress.completed ?? 0}/${progress.total ?? 0}` : UNKNOWN,
      link: safeInternalPath(`/app/launch/${row?.id}`),
      ref: row?.id ?? null,
      source: 'overview.in_progress',
      gaps: [row?.owner == null ? '责任人未提供' : null].filter(Boolean),
    }
  })
}

/** todo.items（来源分组摘要）→ 统一任务项（默认视图，如实标注「摘要」缺口）。 */
function fromTodo(items) {
  if (!Array.isArray(items)) return []
  return items.map((item, i) => ({
    id: `todo:${item?.type || 'x'}:${i}`,
    kind: item?.type || 'task',
    view: 'todo',
    title: item?.title || typeLabel(item?.type),
    object: UNKNOWN,
    store: UNKNOWN,
    reason: '跨域待办（后端为来源分组摘要，逐条明细未提供）',
    owner: UNKNOWN,
    time: item?.due_at || UNKNOWN,
    severity: item?.severity || 'low',
    count: Number(item?.count) || 0,
    link: taskLink(item?.route, '/app/tasks'),
    ref: item?.ref ?? null,
    source: 'workbench.todo',
    gaps: ['明细实例（对象/店铺/责任人）未提供，按来源摘要展示'],
  }))
}

/** ai_done.items → 已完成视图。 */
function fromAiDone(items) {
  if (!Array.isArray(items)) return []
  return items.map((row, i) => ({
    id: `ai_run:${row?.id ?? i}`,
    kind: 'ai_run',
    view: 'done',
    title: row?.title || 'AI 运行',
    object: UNKNOWN,
    store: UNKNOWN,
    reason: '自动化已完成',
    owner: 'AI',
    time: row?.finished_at || UNKNOWN,
    severity: 'low',
    link: '',
    ref: row?.id ?? null,
    source: 'overview.ai_done',
    gaps: [],
  }))
}

/**
 * 汇总三类来源为统一任务列表（去重后）。
 * @returns {{tasks:Array, unavailable:Array<string>}}
 */
export function normalizeTasks({ todo = {}, overview = {} } = {}) {
  const tSources = todo?.sources || {}
  const oSources = overview?.sources || {}
  const unavailable = []
  const tasks = []

  if (tSources.launch === 'failed' || tSources.action === 'failed'
    || tSources.alert === 'failed' || tSources.review === 'failed') {
    unavailable.push('workbench.todo')
  } else {
    tasks.push(...fromTodo(todo?.items))
  }

  if (oSources.launch === 'failed') {
    unavailable.push('overview.launch')
  } else {
    tasks.push(...fromInProgress(overview?.sections?.in_progress))
  }

  if (oSources.workflow === 'failed') {
    unavailable.push('overview.workflow')
  } else {
    tasks.push(...fromAiDone(overview?.sections?.ai_done?.items))
  }

  return { tasks: dedupeTasks(tasks), unavailable }
}

/** 每个视图的待办总量（优先累加后端 count，缺失按 1 计；与首屏计数条口径一致）。 */
export function viewCounts(tasks = []) {
  const counts = Object.fromEntries(TASK_VIEWS.map((v) => [v.key, 0]))
  for (const t of Array.isArray(tasks) ? tasks : []) {
    if (counts[t?.view] == null) continue
    counts[t.view] += Number(t?.count) > 0 ? Number(t.count) : 1
  }
  return counts
}

/** URL query ↔ 筛选（product/store/type/due/view）；空值不写入 query。 */
export const FILTER_KEYS = ['view', 'product', 'store', 'type', 'due']

export function filtersFromQuery(query = {}) {
  const pick = (k) => (typeof query?.[k] === 'string' ? query[k] : '')
  const view = TASK_VIEWS.some((v) => v.key === pick('view')) ? pick('view') : 'todo'
  return { view, product: pick('product'), store: pick('store'), type: pick('type'), due: pick('due') }
}

export function queryFromFilters(filters = {}) {
  const query = {}
  for (const key of FILTER_KEYS) {
    const value = filters[key]
    if (value === '' || value === null || value === undefined || value === 'todo') continue
    query[key] = String(value)
  }
  return query
}

/** due 筛选：''=全部 / overdue=已逾期 / soon=7 天内 / none=无截止。 */
function matchesDue(task, due) {
  if (!due) return true
  const hasDue = task?.time && task.time !== UNKNOWN
  if (due === 'none') return !hasDue
  if (!hasDue) return false
  const ts = Date.parse(String(task.time).replace(' ', 'T'))
  if (Number.isNaN(ts)) return false
  if (due === 'overdue') return ts < Date.now()
  if (due === 'soon') return ts >= Date.now() && ts <= Date.now() + 7 * 864e5
  return true
}

const includesText = (value, needle) => String(value || '').toLowerCase().includes(String(needle).toLowerCase())

/** 按筛选过滤（product/store/type/due/view）。 */
export function filterTasks(tasks = [], filters = {}) {
  const list = Array.isArray(tasks) ? tasks : []
  return list.filter((t) => {
    if ((filters.view || 'todo') !== t.view) return false
    if (filters.type && t.kind !== filters.type) return false
    if (filters.product && !includesText(t.object, filters.product)) return false
    if (filters.store && !includesText(t.store, filters.store)) return false
    if (!matchesDue(t, filters.due)) return false
    return true
  })
}
