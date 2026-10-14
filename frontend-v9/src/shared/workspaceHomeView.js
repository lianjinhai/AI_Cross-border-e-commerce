/**
 * 工作台视图模型（R3-2B §1 四层优先级）：纯函数，供 vitest 直测。
 *
 * 契约来源（现场核对后端源码，非文档臆测）：
 * - `GET /workbench/todo`（backend/app/services/workbench.py build_todo）→
 *   {items:[{type,title,count,severity,due_at,route:{path,return_to},ref}],
 *    counts:{launch,action,alert,review}, generated_at, partial, sources:{type:'ok'|'failed'|'skipped'}}。
 * - `GET /workbench/overview`（build_overview）→ {sections:{metrics,in_progress,top_today,
 *   need_human,ai_done,exceptions}, data_quality, next_actions, signals, partial, sources}。
 *
 * 红线（契约 §4 禁止项）：缺失/未知不当 0，一律用 UNKNOWN='—'；错误不当空；
 * 后端只给分组摘要（items 为聚合条目，ref 目前为空）→ 前端**不得捏造**明细实例
 * （负责人/截止时间缺失即如实标注，不臆造）。
 */

/** 未知/尚未获得占位（金额、计数、百分比通用）。 */
export const UNKNOWN = '—'

/** 严重度权重（后端 severity 取值域 high|mid|low；未知排最后）。 */
const SEVERITY_RANK = { high: 0, mid: 1, low: 2 }

/** 类型责任权重：需人工处理的排前（复核 > 审批动作 > 上线 > 告警）。 */
const TYPE_RANK = { review: 0, action: 1, launch: 2, alert: 3 }

/** 等待平台/外部反馈的执行状态（不计入「需我处理」，计入「等待外部」）。 */
const WAITING_EXTERNAL_STATES = new Set(['WAITING_EXTERNAL', 'WAITING_PLATFORM', 'WAITING_EXTERNAL_FEEDBACK'])
/** 阻断/失败执行状态（计入「被阻断」）。 */
const BLOCKED_STATES = new Set(['BLOCKED', 'FAILED'])

/** due_at（后端 "YYYY-MM-DD HH:MM:SS"）→ 可比较数值；缺失排最后。 */
function dueWeight(value) {
  if (!value) return Number.POSITIVE_INFINITY
  const ts = Date.parse(String(value).replace(' ', 'T'))
  return Number.isNaN(ts) ? Number.POSITIVE_INFINITY : ts
}

/**
 * 单条待办确定性排序键（时限 → 风险 → 责任 → 数量），同键稳定。
 * 排序优先级：severity（高优先）→ due_at（到期近优先）→ type 责任序 → count 降序 → title。
 * @returns {number[]} 可比较数组（配合 compareKeys 使用）。
 */
export function taskPriorityKey(item = {}) {
  const severity = SEVERITY_RANK[item?.severity] ?? 3
  const due = dueWeight(item?.due_at)
  const type = TYPE_RANK[item?.type] ?? 9
  const count = -(Number(item?.count) || 0)
  return [severity, due, type, count]
}

/** 按排序键比较（确定性、稳定）。 */
export function compareTasks(a, b) {
  const ka = taskPriorityKey(a)
  const kb = taskPriorityKey(b)
  for (let i = 0; i < ka.length; i += 1) {
    if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1
  }
  return String(a?.title || '').localeCompare(String(b?.title || ''))
}

/** 确定性排序（不改原数组）；非数组输入 → []。 */
export function rankTasks(items) {
  const list = Array.isArray(items) ? items.filter((i) => i && typeof i === 'object') : []
  return [...list].sort(compareTasks)
}

/** 第一层：当前用户最值得完成的唯一主任务（排序后首条）；无 → null。 */
export function pickPrimaryTask(items) {
  return rankTasks(items)[0] || null
}

/** 第二层：最多 N 项高优先级待办（默认 3，排除主任务）。 */
export function pickHighPriority(items, limit = 3) {
  const ranked = rankTasks(items)
  const primary = ranked[0] || null
  const rest = primary ? ranked.slice(1) : ranked
  return rest.slice(0, Math.max(0, limit))
}

/** 源状态是否失败（单个源）。 */
function isFailed(sources, key) {
  return (sources || {})[key] === 'failed'
}

/**
 * 首屏计数条（§1）：待我处理 / 等待外部 / 被阻断。
 * 缺失或源失败 → 该计数为 UNKNOWN（**不当 0**）；确实为空 → 0。
 * @param {object} todo /workbench/todo 响应
 * @param {object} overview /workbench/overview 响应
 */
export function taskCounters(todo = {}, overview = {}) {
  const tSources = todo?.sources || {}
  const oSources = overview?.sources || {}
  const counts = todo?.counts || {}

  // 待我处理 = 上线(需我) + 待审批动作 + 风险告警 + 待复核；任一相关源失败 → 未知
  const mineKeys = ['launch', 'action', 'alert', 'review']
  const mineFailed = mineKeys.some((k) => isFailed(tSources, k))
  const mine = mineFailed
    ? UNKNOWN
    : mineKeys.reduce((sum, k) => sum + (Number(counts[k]) || 0), 0)

  // 等待外部 / 被阻断：来自进行中上线（源失败 → 未知）
  const inProgress = overview?.sections?.in_progress
  const launchFailed = isFailed(oSources, 'launch')
  const rows = Array.isArray(inProgress) ? inProgress : []
  const derive = (states) => {
    if (launchFailed) return UNKNOWN
    if (!Array.isArray(inProgress)) return UNKNOWN
    return rows.filter((r) => states.has(r?.execution_status)).length
  }
  return {
    mine,
    waitingExternal: derive(WAITING_EXTERNAL_STATES),
    blocked: derive(BLOCKED_STATES),
    partial: Boolean(todo?.partial) || Boolean(overview?.partial),
  }
}

/**
 * 画像 → 入口档案（§1 不同画像入口不同）：确定性规则，仅用 Workspace/店铺/商品/订单事实。
 * 与既有 `resolvePersona`（A/B/C/D/F）并存：本函数面向「任务入口」二值化，不替代它。
 * @returns {'NEW_USER'|'STORE_OWNER'|'FACTORY'|'TEAM'|'UNKNOWN'}
 */
export function resolveEntryProfile(signals) {
  if (!signals || typeof signals !== 'object') return 'UNKNOWN'
  const hasShopFlag = typeof signals.has_sales_shop === 'boolean'
    ? signals.has_sales_shop
    : (typeof signals.sales_shop_count === 'number' ? signals.sales_shop_count > 0 : null)
  const hasFactoryFlag = typeof signals.has_factory === 'boolean'
    ? signals.has_factory
    : (typeof signals.factory_match_count === 'number' ? signals.factory_match_count > 0 : null)
  if (hasShopFlag === null) return 'UNKNOWN' // 关键事实缺失 → 不猜
  if (hasShopFlag) return 'STORE_OWNER'
  if (hasFactoryFlag === true) return 'FACTORY'
  if (typeof signals.member_count === 'number' && signals.member_count > 1) return 'TEAM'
  return 'NEW_USER'
}

/** 入口档案 → 差异化入口（左侧首层、右侧唯一推荐；路径为站内合法路径）。 */
const ENTRY_PLANS = {
  NEW_USER: {
    label: '新手起步',
    hint: '先完成「选品 → 连店 → 上线」一次闭环，再看经营数据。',
    steps: [
      { key: 'prepare', text: '准备商品资料', path: '/app/products' },
      { key: 'discover', text: '选品（商品发现）', path: '/app/market/discovery' },
      { key: 'connect', text: '连接销售店铺', path: '/app/channels/shops' },
    ],
    recommended: { key: 'discover', text: '开始选品', path: '/app/market/discovery' },
  },
  STORE_OWNER: {
    label: '店铺经营',
    hint: '有店铺：聚焦上线、订单履约与利润。',
    steps: [
      { key: 'launch', text: '继续上线流程', path: '/app/launch' },
      { key: 'orders', text: '处理订单 / 履约', path: '/app/orders' },
      { key: 'profit', text: '查看真实利润', path: '/app/analytics/finance' },
    ],
    recommended: { key: 'launch', text: '继续上线', path: '/app/launch' },
  },
  FACTORY: {
    label: '工厂协同',
    hint: '有工厂供给：聚焦供给数据与需求匹配。',
    steps: [
      { key: 'supply', text: '补全供给数据', path: '/app/supply/suppliers' },
      { key: 'match', text: '查看匹配结果', path: '/app/supply/matching' },
    ],
    recommended: { key: 'supply', text: '补全供给数据', path: '/app/supply/suppliers' },
  },
  TEAM: {
    label: '团队协作',
    hint: '多人空间：先治理权限与授权。',
    steps: [
      { key: 'team', text: '管理成员与权限', path: '/app/settings/team' },
      { key: 'discover', text: '选品（商品发现）', path: '/app/market/discovery' },
    ],
    recommended: { key: 'team', text: '管理成员与权限', path: '/app/settings/team' },
  },
  UNKNOWN: {
    label: '通用工作台',
    hint: '经营事实不足，先按通用路径了解系统。',
    steps: [
      { key: 'products', text: '浏览商品池', path: '/app/products' },
      { key: 'shops', text: '绑定销售店铺', path: '/app/channels/shops' },
    ],
    recommended: { key: 'products', text: '浏览商品池', path: '/app/products' },
  },
}

/** 入口档案详情（label/hint/steps/recommended）；未知档案 → 通用。 */
export function entryPlan(profile) {
  return ENTRY_PLANS[profile] || ENTRY_PLANS.UNKNOWN
}

/**
 * 经营阶段（第三层）：确定性判定，仅用信号与进行中事实。
 * @returns {{stage:string,label:string,hint:string}}
 */
export function businessStage(signals, overview = {}) {
  const profile = resolveEntryProfile(signals)
  const inProgress = overview?.sections?.in_progress
  const hasInProgress = Array.isArray(inProgress) && inProgress.length > 0
  if (profile === 'UNKNOWN') {
    return { stage: 'UNKNOWN', label: '阶段未知', hint: '经营事实不足，无法判断当前阶段。' }
  }
  if (profile === 'NEW_USER') {
    return { stage: 'STARTING', label: '起步阶段', hint: '还没有销售店铺：先准备好商品并连接店铺。' }
  }
  if (profile === 'FACTORY') {
    return { stage: 'SUPPLY', label: '供给阶段', hint: '聚焦工厂供给数据与需求匹配。' }
  }
  if (profile === 'STORE_OWNER' && hasInProgress) {
    return { stage: 'LAUNCHING', label: '上线阶段', hint: '有进行中的上线流程：优先推进直至完成。' }
  }
  return { stage: 'OPERATING', label: '经营阶段', hint: '店铺已就绪：关注订单履约与利润。' }
}

/**
 * 第三层：需要关注的阻断摘要（来自 overview.sections.in_progress 的 blocked/失败/next_action.reason）。
 * 缺失源 → available=false（页面明示未知，不当 0）。
 */
export function blockerSummary(overview = {}) {
  const sources = overview?.sources || {}
  const inProgress = overview?.sections?.in_progress
  if (sources.launch === 'failed') return { available: false, items: [], reason: '上线数据源不可用' }
  if (!Array.isArray(inProgress)) return { available: false, items: [], reason: '暂无上线数据' }
  const items = []
  for (const row of inProgress) {
    if (BLOCKED_STATES.has(row?.execution_status)) {
      items.push({ kind: 'blocked', id: row?.id, product: row?.product, store: row?.store,
        status: row?.execution_status, message: row?.blocked_summary?.[0]?.message || '执行受阻' })
    } else if (row?.next_action && row.next_action.executable === false && row.next_action.reason) {
      items.push({ kind: 'waiting', id: row?.id, product: row?.product, store: row?.store,
        status: row?.execution_status, message: row.next_action.reason })
    }
  }
  return { available: true, items, reason: '' }
}

/**
 * 第三层：真实经营摘要（缺失/无权限 → UNKNOWN，绝不当 0）。
 * @returns {Array<{label:string,value:string,missing:boolean}>}
 */
export function businessSummary(overview = {}) {
  const m = overview?.sections?.metrics
  const sources = overview?.sources || {}
  if (sources.bi === 'failed') {
    return [{ label: '经营指标', value: UNKNOWN, missing: true }]
  }
  if (!m || typeof m !== 'object') {
    return [{ label: '经营指标', value: UNKNOWN, missing: true }]
  }
  const money = (v) => (v === null || v === undefined ? UNKNOWN : `$${Number(v).toFixed(2)}`)
  const num = (v) => (v === null || v === undefined ? UNKNOWN : v)
  return [
    { label: `GMV（近30天 · ${m.currency || UNKNOWN}）`, value: money(m.gmv), missing: m.gmv === null || m.gmv === undefined },
    { label: '订单数（销售口径）', value: String(num(m.orders)), missing: m.orders === null || m.orders === undefined },
    { label: '贡献利润', value: money(m.contribution_profit), missing: m.contribution_profit === null || m.contribution_profit === undefined },
  ]
}

/**
 * 第四层：AI 执行历史（可展开活动流）；源失败 → available=false。
 */
export function aiActivity(overview = {}) {
  const sources = overview?.sources || {}
  if (sources.workflow === 'failed') return { available: false, items: [], reason: 'AI 运行数据源不可用' }
  const section = overview?.sections?.ai_done
  if (!section || typeof section !== 'object') return { available: false, items: [], reason: '暂无 AI 运行记录' }
  const items = Array.isArray(section.items) ? section.items : []
  return { available: true, items, count: Number(section.count) || items.length, reason: '' }
}

/** 是否为安全站内路径（用于把 return_to 附加到任务深链）。 */
export function safeInternalPath(path) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) return null
  if (path.includes('..')) return null
  return path
}

/**
 * 为任务深链附加 return_to（保留待办位置，§3 闭环）。
 * @returns {string} 站内路径（含 return_to query；非法 return_to 不附加）
 */
export function taskLink(route = {}, returnTo) {
  const path = safeInternalPath(route?.path) || ''
  const back = safeInternalPath(returnTo || route?.return_to)
  if (!path || !back) return path
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}return_to=${encodeURIComponent(back)}`
}
