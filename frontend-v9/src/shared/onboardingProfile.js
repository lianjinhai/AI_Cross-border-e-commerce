/**
 * 经营画像（B2；D63 起为**服务端持久化**，会话层降级为草稿/缓存）。
 *
 * 诚实契约（不可违反）：
 * - 服务端（GET/PUT /api/business-profile）是权威事实：保存成功后同一账号
 *   重新登录仍可读回（跨会话），且按用户/工作区隔离。
 * - sessionStorage 会话画像仅作两件事：① 未登录/接口失败时的**草稿**；
 *   ② 页面间的同步缓存（服务端读回后立即镜像，供同步消费方读取）。
 * - `persisted` 标注数据来源：`true` = 已从服务端读回/已成功保存到服务端；
 *   `false` = 仅会话草稿。消费方**必须**按该标志渲染保存状态文案：
 *   persisted=false 时禁止出现「已保存」话术，必须明示「未保存到服务器」。
 *
 * 字段：direction（资源起点）/ budget（预算展示标签）/ budgetAmount /
 *       budgetCurrency（服务端数值字段）/ targetMarket（目标市场）/
 *       risk（风险偏好）——缺项由消费方按「待补」渲染。
 */

const KEY = 'v91_onboarding_profile'

/** 隐私模式 / 非浏览器环境下 sessionStorage 可能抛异常：降级为模块级内存。 */
let _memStore = null
function memoryStorage() {
  if (!_memStore) {
    const m = new Map()
    _memStore = {
      getItem: (k) => (m.has(k) ? m.get(k) : null),
      setItem: (k, v) => { m.set(k, String(v)) },
      removeItem: (k) => { m.delete(k) },
    }
  }
  return _memStore
}

function storage() {
  try {
    if (typeof sessionStorage !== 'undefined' && sessionStorage !== null) {
      // 探测一次可用性（隐私模式可能只在读写时抛）
      const probe = '__v91_probe__'
      sessionStorage.setItem(probe, '1')
      sessionStorage.removeItem(probe)
      return sessionStorage
    }
  } catch { /* 降级 */ }
  return memoryStorage()
}

/** 读取会话画像；无 / 损坏一律返回 null（消费方按「待补」处理，不伪造）。 */
export function loadSessionProfile() {
  try {
    const raw = storage().getItem(KEY)
    if (!raw) return null
    const p = JSON.parse(raw)
    if (!p || typeof p !== 'object' || Array.isArray(p)) return null
    return { ...p, persisted: false }
  } catch {
    return null
  }
}

/** 增量合并写入，返回写入后的完整画像。部分字段更新不影响其余字段。 */
export function saveSessionProfile(partial = {}) {
  const prev = loadSessionProfile() || {}
  const next = {
    ...prev,
    ...partial,
    updatedAtISO: new Date().toISOString(),
    persisted: false,
  }
  _writeCache(next)
  return next
}

/** 保真写入：不篡改 persisted/updatedAtISO（服务端读回镜像专用）。 */
function _writeCache(profile) {
  try {
    storage().setItem(KEY, JSON.stringify(profile))
  } catch { /* 写不进去就放弃：调用方拿到的返回值仍是会话语义 */ }
}

/** 清空会话画像（用户显式重来时用）。 */
export function clearSessionProfile() {
  try {
    storage().removeItem(KEY)
  } catch { /* 降级存储无副作用 */ }
}

/* ─────────────────────────── 服务端映射（纯函数） ─────────────────────────── */

/** 预算展示标签：金额（数值，本位币元）+ 币种代码 → 中文标签。 */
export function formatBudgetLabel(amount, currency) {
  if (amount == null || !Number.isFinite(Number(amount))) return ''
  const n = Number(amount)
  const cur = currency || ''
  const num = n.toLocaleString('en-US')
  if (cur === 'CNY') return `¥${num}`
  if (cur === 'USD') return `$${num}`
  return `${num} ${cur}`.trim()
}

/**
 * 服务端 GET /business-profile 响应 → 前端画像形状（并镜像进会话缓存）。
 * dto 缺失/非对象返回 null；字段缺失保持 null/空串，绝不臆造。
 */
export function profileFromServer(dto) {
  if (!dto || typeof dto !== 'object' || Array.isArray(dto)) return null
  const amount = dto.budget?.amount ?? null
  const currency = dto.budget?.currency ?? null
  const profile = {
    direction: dto.direction ?? '',
    budget: formatBudgetLabel(amount, currency),
    budgetAmount: amount,
    budgetCurrency: currency,
    targetMarket: dto.target_market ?? '',
    risk: dto.risk ?? '',
    completed: Boolean(dto.completed),
    updatedAtISO: dto.updated_at ?? '',
    persisted: true,
  }
  _writeCache(profile) // 镜像进会话缓存（保真：persisted/updatedAtISO 原样），供同步消费方读取
  return profile
}

/**
 * 前端画像增量 → PUT /business-profile 请求体（snake_case）。
 * 只包含 partial 中**显式提供**的键（undefined = 不动服务端原值）；
 * 显式 null = 清除该字段（与后端契约一致）。
 */
export function serverPayloadFromProfile(partial = {}) {
  const payload = {}
  if ('direction' in partial) payload.direction = partial.direction
  if ('budgetAmount' in partial) payload.budget_amount = partial.budgetAmount
  if ('budgetCurrency' in partial) payload.budget_currency = partial.budgetCurrency
  if ('targetMarket' in partial) payload.target_market = partial.targetMarket
  if ('risk' in partial) payload.risk = partial.risk
  return payload
}

/**
 * 画像缺项清单（供「经营条件卡」逐项渲染「待补」）。
 * 返回 [{ key, label }]，label 为中文展示名。
 */
export function profileGaps(profile) {
  const p = profile || {}
  const labels = { budget: '预算', targetMarket: '目标市场', risk: '风险偏好' }
  return ['budget', 'targetMarket', 'risk']
    .filter((k) => !String(p[k] ?? '').trim())
    .map((k) => ({ key: k, label: labels[k] }))
}
