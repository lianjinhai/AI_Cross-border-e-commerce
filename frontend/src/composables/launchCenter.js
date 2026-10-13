import api from '../api'

/**
 * 上线中心数据层（设计 D9 / T04）：列表、上下文、详情、步骤、事件、动作执行、同步。
 *
 * 三条铁律（T03 冻结契约，前端不得自行改写）：
 *   1. 写路径必须带 `Idempotency-Key` 头 + body `expected_revision`（缺一即 409/422）。
 *   2. 列表响应字段是 **`page_num`**（不是 `page`）；服务端先 Scope 后分页，前端不得自行过滤。
 *   3. 错误体是 `err.response.data.detail` 对象 `{code,message,blockers,current_revision?,existing_launch_id?}`。
 *
 * 纯函数集中在文件后半段，供 vitest 直测（组件只消费，不重复实现判定）。
 */

const LIST_PAGE_FIELDS = new Set(['page_num', 'page_size'])
const BOOLEAN_FILTERS = ['mine', 'waiting_platform', 'blocked_only', 'include_history']
const NUMBER_FILTERS = ['product_id', 'shop_id', 'owner_user_id']
const TEXT_FILTERS = ['platform', 'market', 'execution_status']
const RETURN_WHITELIST = ['/launch']

// ── 数据层（T04 用到 ①②③；④⑤⑥⑦ 供 T05 详情复用） ───────────────────────────

/** ① 上线入口上下文（GET /launch/context）。 */
export async function loadContext() {
  return (await api.get('/launch/context')).data
}

/** ② 列表（GET /launch）。响应含 page_num / page_size / total / items。 */
export async function listLaunches(params = {}) {
  return (await api.get('/launch', { params })).data
}

/** ③ 详情（GET /launch/{id}）。 */
export async function loadDetail(runId) {
  return (await api.get(`/launch/${runId}`)).data
}

/** ④ 步骤（GET /launch/{id}/steps）。 */
export async function loadSteps(runId) {
  return (await api.get(`/launch/${runId}/steps`)).data
}

/** ⑤ 事件（GET /launch/{id}/events，升序分页）。 */
export async function loadEvents(runId, page = {}) {
  return (await api.get(`/launch/${runId}/events`, { params: page })).data
}

/**
 * ⑥ 执行动作（POST /launch/{id}/actions/{action}）。
 * 必带 `Idempotency-Key` 头（未传则自动生成）与 body `expected_revision`。
 */
export async function executeAction(runId, action, payload = {},
                                   { expectedRevision, stepCode = '', idempotencyKey } = {}) {
  const key = idempotencyKey || newIdempotencyKey(`launch-${runId}-${action}`)
  return (await api.post(`/launch/${runId}/actions/${action}`,
    { step_code: stepCode, expected_revision: expectedRevision, payload },
    { headers: { 'Idempotency-Key': key } })).data
}

/** ⑦ 同步（POST /launch/{id}/sync，仅支持 refresh 模式）。 */
export async function syncLaunch(runId, expectedRevision) {
  return (await api.post(`/launch/${runId}/sync`,
    { mode: 'refresh', expected_revision: expectedRevision })).data
}

// ── 纯函数（vitest 直测） ───────────────────────────────────────────────────

/** 执行状态文案/标签（AC-14.2：等待平台用中性 info，不用失败红）。 */
export const EXECUTION_STATUS = {
  NOT_STARTED: { text: '未开始', tag: 'info' },
  READY: { text: '待执行', tag: 'primary' },
  RUNNING: { text: '进行中', tag: 'primary' },
  WAITING_USER: { text: '待你处理', tag: 'warning' },
  WAITING_APPROVAL: { text: '待审批', tag: 'warning' },
  WAITING_EXTERNAL: { text: '等待平台反馈', tag: 'info' },
  BLOCKED: { text: '已阻断', tag: 'danger' },
  FAILED: { text: '执行失败', tag: 'danger' },
  COMPLETED: { text: '已完成', tag: 'success' },
  CANCELLED: { text: '已取消', tag: 'info' },
}

/** 平台状态文案/标签（AC-14.2：UNKNOWN 不得显示为绿色完成）。 */
export const PLATFORM_STATUS = {
  UNKNOWN: { text: '未知', tag: 'info' },
  NOT_SUBMITTED: { text: '未提交', tag: 'info' },
  SUBMITTED: { text: '已提交', tag: 'warning' },
  UNDER_REVIEW: { text: '平台审核中', tag: 'warning' },
  ACTIVE: { text: '在售', tag: 'success' },
  PAUSED: { text: '已暂停', tag: 'warning' },
  OFFLINE: { text: '已下架', tag: 'info' },
  REJECTED: { text: '平台驳回', tag: 'danger' },
}

/** 查表取文案；未知值退化为中性 info（绝不误标成功）。 */
export function statusMeta(table, value) {
  return table[value] || { text: value || '未知', tag: 'info' }
}

export const executionStatusMeta = (value) => statusMeta(EXECUTION_STATUS, value)
export const platformStatusMeta = (value) => statusMeta(PLATFORM_STATUS, value)

/** 完成数/总数文案。 */
export function progressText(progress = {}) {
  return `${Number(progress.completed ?? 0)}/${Number(progress.total ?? 0)}`
}

/** 阻断摘要（取前 3 条中的首条，其余折叠计数）。 */
export function blockerText(blockedSummary = []) {
  if (!blockedSummary.length) return '—'
  const first = blockedSummary[0]
  const rest = blockedSummary.length > 1 ? `（+${blockedSummary.length - 1}）` : ''
  return `${first.message || first.code || '存在阻断'}${rest}`
}

/** 下一动作文案：可执行只显示动作，不可执行附带原因（AC-14.5 引导）。 */
export function nextActionText(nextAction = {}) {
  if (!nextAction.action) return '暂无待办动作'
  const step = nextAction.step_code ? ` · ${nextAction.step_code}` : ''
  return nextAction.executable
    ? `${nextAction.action}${step}`
    : `${nextAction.action}（${nextAction.reason || '当前不可执行'}）`
}

/** 责任人展示（role_hint 优先，如「运营/平台/复核人」）。 */
export function ownerText(owner = {}) {
  if (!owner.actor) return '—'
  return owner.role_hint || owner.actor
}

/** 降级行标记（单行事实异常时后端给出 LAUNCH_DEFINITION_CORRUPT）。 */
export function isDegraded(item = {}) {
  return (item.blocked_summary || []).some((b) => b.code === 'LAUNCH_DEFINITION_CORRUPT')
}

/** Guided 业务语言摘要（AC-16.2）：数值全部来自 DTO。 */
export function guidedSummary(item = {}) {
  const progress = item.progress || {}
  const parts = [`你的商品已完成 ${progress.completed ?? 0}/${progress.total ?? 0}`,
                 executionStatusMeta(item.execution_status).text]
  const blocker = item.blocked_summary?.[0]?.message
  if (blocker) parts.push(`阻断：${blocker}`)
  return parts.join('；')
}

/** 浏览器临时模式初值来自 Workspace 默认（AC-16.4）。 */
export function experienceMode(context) {
  return context?.effective_experience_mode || 'GUIDED'
}

// ── F02/F03 详情辅助（T05 纯函数，组件只消费） ──────────────────────────────

/** 未接入领域的统一占位（AC-16.3/17.3）：绝不伪造数值。 */
export const NOT_CONNECTED = '未接入'

export function notConnected(value) {
  return value === null || value === undefined || value === '' ? NOT_CONNECTED : value
}

/** PROFESSIONAL 展开字段（AC-16.3）：DTO 缺失的一律「未接入」。 */
export function professionalFields(step = {}) {
  const external = step.external || {}
  return [
    { label: '原始步骤状态', value: notConnected(step.step_status) },
    { label: '执行模式', value: notConnected(step.execution_mode) },
    { label: '外部状态', value: notConnected(external.status) },
    { label: '外部引用', value: notConnected(external.reference) },
    { label: '外部类型', value: notConnected(external.type) },
    { label: '映射版本', value: notConnected(step.mapping_version) },
    { label: '输入版本', value: notConnected(step.input_revision) },
  ]
}

/** 列表文本化（要求/缺项/证据/依赖共用；空集合显示占位）。 */
export function evidenceText(items = []) {
  const list = Array.isArray(items) ? items.filter((item) => item !== null && item !== undefined && item !== '') : []
  return list.length ? list.join('、') : '—'
}

/** 需二次确认的高危动作（AC-15.5）：确认核验/取消类，或后端标注高风险/需审批。 */
const DOUBLE_CONFIRM_ACTIONS = new Set(['CONFIRM_ACTIVATION', 'CANCEL', 'ABANDON_PRODUCT'])

export function needsDoubleConfirm(action, entry = {}) {
  return DOUBLE_CONFIRM_ACTIONS.has(action) || entry.risk === 'HIGH' || entry.approval_required === true
}

/** 需人工确认（note + confirm）的 run 级动作；载荷必填 note/confirm（后端 422 契约）。 */
const CONFIRM_PAYLOAD_ACTIONS = new Set(['CANCEL', 'ABANDON_PRODUCT'])

export function requiresMaterial(action) {
  return action === 'CONFIRM_ACTIVATION'
}

export function requiresNote(action) {
  return CONFIRM_PAYLOAD_ACTIONS.has(action)
}

/** 按 per-action 载荷契约构造 payload（避免发送未知键触发 422）。 */
export function actionPayload(action, form = {}) {
  if (CONFIRM_PAYLOAD_ACTIONS.has(action)) {
    return { note: String(form.note || '').trim(), confirm: true }
  }
  const payload = {}
  if (requiresMaterial(action) && form.material_ref) payload.material_ref = String(form.material_ref).trim()
  if (form.note) payload.note = String(form.note).trim()
  return payload
}

/** 结果不确定（超时/断网/后端未给终态）：显示「结果待核查」，不诱导重发（AC-15.6）。 */
const UNCERTAIN_CODES = new Set(['EXECUTION_UNCERTAIN', 'ACTION_UNCERTAIN', 'APPROVAL_UNKNOWN'])

export function isUncertainError(error) {
  if (!error || !error.response) return true  // 网络中断/超时：结果未知
  return UNCERTAIN_CODES.has(error.response?.data?.detail?.code)
}

/** 时间线并行分组（AC-15.1）：按 sequence 升序分组，同组即并行。 */
export function groupStepsBySequence(steps = []) {
  const groups = new Map()
  for (const step of steps) {
    const key = Number(step.sequence ?? 0)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(step)
  }
  return [...groups.entries()].sort((a, b) => a[0] - b[0])
    .map(([sequence, items]) => ({ sequence, items }))
}

/** 其他可并行处理的 READY 节点（AC-15.2）：当前焦点不是唯一可操作步骤。 */
export function parallelReadySteps(steps = []) {
  return steps.filter((step) => step.step_status === 'READY')
}

export const EMPTY_REASONS = {
  REQUEST_FAILED: { text: '加载失败', hint: '请检查网络后重试', action: 'retry' },
  NO_PERMISSION: { text: '没有权限', hint: '当前账号没有查看上线流程的权限', action: 'none' },
  NO_SHOP: { text: '还没有销售店铺', hint: '请先在「店铺授权」添加销售店铺', action: 'add_shop' },
  NO_PROFILE: { text: '没有可用的上线流程', hint: '目标店铺缺少适用的已发布流程', action: 'none' },
  NO_MATCH: { text: '没有匹配的流程', hint: '请调整或清除筛选条件', action: 'clear_filters' },
  NO_PRODUCT: { text: '还没有上线流程', hint: '从商品库选择商品创建上线流程', action: 'none' },
}

/** 是否设置了收窄型筛选（不含分页与 include_history 作用域开关）。 */
export function hasActiveFilters(filters = {}) {
  return Object.entries(filters).some(([key, value]) => {
    if (LIST_PAGE_FIELDS.has(key) || key === 'include_history') return false
    if (typeof value === 'boolean') return value
    return value !== '' && value !== null && value !== undefined
  })
}

/** 空态分因（AC-14.5）：无商品/无销售店/无适用 Profile/无匹配筛选/无权限/请求失败。 */
export function emptyStateReason({ context = null, filters = {}, error = null, total = 0 } = {}) {
  const pick = (code) => ({ code, ...EMPTY_REASONS[code] })
  if (error) return pick('REQUEST_FAILED')
  if (context) {
    const blocked = context.blocked_reason?.code
    if (blocked === 'PERMISSION_DENIED') return pick('NO_PERMISSION')
    if (blocked === 'NO_USABLE_SHOP' || !(context.shops || []).length) return pick('NO_SHOP')
    if (blocked === 'NO_PROFILE' || !(context.shops || []).some((s) => s.usable)) return pick('NO_PROFILE')
  }
  if (total === 0 && hasActiveFilters(filters)) return pick('NO_MATCH')
  return pick('NO_PRODUCT')
}

/** 站内白名单校验（AC-14.7）：仅放行 `/launch` 与 `/launch/...`。 */
export function isSafeReturnTo(path) {
  if (typeof path !== 'string' || !path.startsWith('/')) return false
  if (path.startsWith('//') || path.includes('\\') || path.includes('..')) return false
  const base = path.split('?')[0].split('#')[0]
  return RETURN_WHITELIST.some((p) => base === p || base.startsWith(`${p}/`))
}

export function sanitizeReturnTo(path, fallback = '/launch') {
  return isSafeReturnTo(path) ? path : fallback
}

/** 由当前筛选构造 return_to（跳过空值与分页字段）。 */
export function buildReturnTo(filters = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (LIST_PAGE_FIELDS.has(key)) continue
    if (value === '' || value === null || value === undefined || value === false) continue
    query.set(key, String(value))
  }
  const qs = query.toString()
  return qs ? `/launch?${qs}` : '/launch'
}

/** 从 return_to 还原筛选（类型归一）；非法路径返回 null。 */
export function parseReturnTo(path) {
  if (!isSafeReturnTo(path)) return null
  const raw = Object.fromEntries(new URLSearchParams(path.split('?')[1] || ''))
  const filters = {}
  for (const key of [...NUMBER_FILTERS, ...BOOLEAN_FILTERS, ...TEXT_FILTERS]) {
    if (!(key in raw)) continue
    if (NUMBER_FILTERS.includes(key)) filters[key] = raw[key] ? Number(raw[key]) : null
    else if (BOOLEAN_FILTERS.includes(key)) filters[key] = raw[key] === 'true'
    else filters[key] = raw[key]
  }
  return filters
}

/** 行点击目标：详情路径 + 站内白名单 return_to（T05 详情路由使用）。 */
export function detailPath(runId, returnTo) {
  const query = isSafeReturnTo(returnTo) ? { return_to: returnTo } : {}
  return { path: `/launch/${runId}`, query }
}

/** 列表请求参数：服务端字段名 + 仅发送非空筛选。 */
export function listQuery(filters = {}, { pageNum = 1, pageSize = 20 } = {}) {
  const params = { page_num: pageNum, page_size: pageSize }
  for (const [key, value] of Object.entries(filters)) {
    if (LIST_PAGE_FIELDS.has(key)) continue
    if (value === '' || value === null || value === undefined || value === false) continue
    params[key] = value
  }
  return params
}

/** 幂等键生成（写路径必用；结构可测、两次不同）。 */
export function newIdempotencyKey(prefix = 'launch') {
  const rand = Math.random().toString(36).slice(2, 10)
  return `${prefix}-${Date.now().toString(36)}-${rand}`
}

/** 错误 envelope 归一（对象 detail / 字符串 detail / 无 detail 三态）。 */
export function errorEnvelope(error) {
  const detail = error?.response?.data?.detail
  if (detail && typeof detail === 'object') {
    return {
      code: detail.code || 'REQUEST_FAILED',
      message: detail.message || '请求失败，请稍后重试',
      blockers: detail.blockers || [],
      current_revision: detail.current_revision ?? null,
      existing_launch_id: detail.existing_launch_id ?? null,
    }
  }
  return {
    code: 'REQUEST_FAILED',
    message: typeof detail === 'string' && detail ? detail : '请求失败，请稍后重试',
    blockers: [],
    current_revision: null,
    existing_launch_id: null,
  }
}

/** 409 REVISION_CONFLICT 时返回服务端最新 revision（供组件回填并保留用户输入）。 */
export function revisionConflict(error) {
  const envelope = errorEnvelope(error)
  return envelope.code === 'REVISION_CONFLICT' ? envelope.current_revision : null
}
