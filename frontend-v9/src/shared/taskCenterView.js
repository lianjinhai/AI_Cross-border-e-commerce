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

import { UNKNOWN, displayName, safeInternalPath, taskLink } from './workspaceHomeView'
import { isBlockedItem, isWaitingExternalItem } from './workbenchContext'

/**
 * 视图定义。默认「全部待办」= 跨域来源摘要（launch/action/alert/review）；
 * 其余三视图与顶栏/工作台计数条**同口径**（等待外部 = WAITING_EXTERNAL ∪ 平台
 * SUBMITTED/UNDER_REVIEW；被阻断 = BLOCKED/FAILED），避免「同词不同义」。
 */
export const TASK_VIEWS = [
  { key: 'todo', label: '全部待办' },
  { key: 'waiting', label: '等待外部' },
  { key: 'blocked', label: '被阻断' },
  { key: 'done', label: '已完成' },
]

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

/** overview.sections.in_progress 行 → 统一任务项（等待外部 / 被阻断 / 进行中）。 */
function fromInProgress(rows) {
  if (!Array.isArray(rows)) return []
  return rows.map((row) => {
    // 视图口径与顶栏/工作台计数条同源（workbenchContext 谓词，对齐后端 _WAITING_STATES
    // / _PLATFORM_WAITING）：被阻断 = BLOCKED/FAILED；等待外部 = WAITING_EXTERNAL 或平台
    // SUBMITTED/UNDER_REVIEW；其余 mine 状态（READY/WAITING_USER/RUNNING…）→ 'active'
    // （**不混入「等待外部」计数**，bug2 语义统一）。
    const view = isBlockedItem(row) ? 'blocked' : (isWaitingExternalItem(row) ? 'waiting' : 'active')
    const reason = row?.blocked_summary?.[0]?.message
      || (row?.next_action && row.next_action.executable === false ? row.next_action.reason : null)
      || (view === 'blocked' ? '执行受阻' : (view === 'waiting' ? '等待外部平台回执' : UNKNOWN))
    const progress = row?.progress
    // bug1 修复：后端 product={id,title,sku} / store={id,name,platform} 为**对象**，
    // 直接插值会渲染 "[object Object]" → 归一化为人类可读字符串；原对象另存 raw 供筛选/跳转。
    const productName = displayName(row?.product, 'product')
    const storeName = displayName(row?.store, 'store')
    return {
      id: `launch:${row?.id ?? productName}`, // 业务键 = 上线运行 id（稳定，不含下标）
      kind: 'launch',
      view,
      title: `${productName} 的上线流程`,
      object: productName,
      store: storeName,
      productRaw: row?.product ?? null,
      storeRaw: row?.store ?? null,
      reason,
      owner: row?.owner?.role_hint || row?.owner?.actor || UNKNOWN,
      time: row?.created_at || UNKNOWN,
      severity: isBlockedItem(row) ? 'high' : 'mid',
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
  return items.map((item) => {
    // bug5 修复：稳定任务标识基于业务键（type + store + object），**不含下标**，
    // 列表重排不漂移。分组摘要的 store/object 未知 → 用 ref/title 兜底保证唯一。
    const storeDisp = displayName(item?.store, 'store')
    const objectDisp = displayName(item?.object, 'product')
    const parts = ['todo', item?.type || 'x']
    if (storeDisp !== UNKNOWN) parts.push(storeDisp)
    if (objectDisp !== UNKNOWN) parts.push(objectDisp)
    if (storeDisp === UNKNOWN && objectDisp === UNKNOWN) {
      parts.push(String(item?.ref ?? item?.title ?? '摘要'))
    }
    return {
      id: parts.join(':'),
      kind: item?.type || 'task',
      view: 'todo',
      title: item?.title || typeLabel(item?.type),
      object: objectDisp,
      store: storeDisp,
      reason: '跨域待办（后端为来源分组摘要，逐条明细未提供）',
      owner: UNKNOWN,
      time: item?.due_at || UNKNOWN,
      severity: item?.severity || 'low',
      count: Number(item?.count) || 0,
      link: taskLink(item?.route, '/app/tasks'),
      ref: item?.ref ?? null,
      source: 'workbench.todo',
      gaps: ['明细实例（对象/店铺/责任人）未提供，按来源摘要展示'],
    }
  })
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

/**
 * 取任务字段的可筛选文本（bug2 修复）：object/store 可能是**后端对象**
 * （product/store 引用）或已归一化的展示字符串 → 统一经 displayName 归一，
 * 避免对对象比较导致筛选恒 0 行。优先展示字段，其次 raw 对象。
 */
function filterText(task, field) {
  if (field === 'store') return displayName(task?.store ?? task?.storeRaw, 'store')
  return displayName(task?.object ?? task?.productRaw, 'product')
}

/** 按筛选过滤（product/store/type/due/view）。 */
export function filterTasks(tasks = [], filters = {}) {
  const list = Array.isArray(tasks) ? tasks : []
  return list.filter((t) => {
    if ((filters.view || 'todo') !== t.view) return false
    if (filters.type && t.kind !== filters.type) return false
    if (filters.product && !includesText(filterText(t, 'product'), filters.product)) return false
    if (filters.store && !includesText(filterText(t, 'store'), filters.store)) return false
    if (!matchesDue(t, filters.due)) return false
    return true
  })
}

/**
 * 构造任务处理深链（bug4 修复）：**URL 感知**地把 return_to 合并进任务 link，
 * 已含 return_to 则覆盖为规范化后的单一值（不重复追加），保留当前 ?view=&store=
 * 等筛选于 return_to。使用 URLSearchParams 构造，避免手拼 query。
 * @param {string} link 任务目标路径（可能已含 ?return_to=…）
 * @param {string} returnTo 当前待办页位置（path + query）
 * @returns {string} 站内路径；非法 path → ''
 */
export function buildTaskHref(link, returnTo) {
  if (!link || typeof link !== 'string') return ''
  const [rawPath, rawQuery = ''] = link.split('?')
  const path = safeInternalPath(rawPath)
  if (!path) return ''
  const params = new URLSearchParams(rawQuery)
  const back = safeInternalPath(returnTo)
  if (back) params.set('return_to', back) // set → 覆盖重复项，保证唯一
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}
