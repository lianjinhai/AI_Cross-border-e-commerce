/**
 * J0 零基础经营准备链路（纯函数，可独立单测，不依赖 Vue / axios）。
 *
 * 链路（5 步）：
 *   1. 研究商品方向  discovery  → /app/market/discovery
 *   2. 选择货源      sourcing   → /app/supply/sourcing
 *   3. 查看成本/风险  cost       → /app/analytics/landed-cost
 *   4. 准备销售渠道   channel    → /app/channels
 *   5. 建立商品销售准备 prepare   → /app/market/candidates
 *
 * 机制：路由 query 透传 `journey=j0` 与 `productId=XX`（同一对象上下文，返回不丢），
 * 复用既有 API / service，不造第二套数据模型。
 *
 * 诚实红线：
 * - 缺值渲染 "—"（MISSING），不当 0；
 * - 无对应端点不伪造，最终"准备任务"落到真实能力：创建商品主档（POST /products）；
 * - 后端缺口（独立"销售准备任务"写端点）由页面显式标注，不在本报告外掩盖。
 */

import { tagInfo } from './dataLabels'

/** J0 链路标识（写入路由 query.journey）。 */
export const J0_JOURNEY_KEY = 'j0'

/** 有序步骤定义（route = 规范路由；also = 该步骤可归属的并列/子页路由前缀）。 */
export const J0_STEPS = [
  {
    key: 'discovery',
    title: '研究商品方向',
    goal: '从市场趋势 / 机会评分里挑出想做的商品，并转入商品池建立商品主档',
    route: '/app/market/discovery',
    also: ['/app/market/candidates', '/app/market/opportunity'],
  },
  {
    key: 'sourcing',
    title: '选择货源',
    goal: '在货源发现 / 供应商库里确认供货来源、采购价与交期',
    route: '/app/supply/sourcing',
    also: ['/app/supply/suppliers', '/app/supply/matching'],
  },
  {
    key: 'cost',
    title: '查看成本/风险',
    goal: '核算到岸成本与毛利假设，识别关税 / 物流 / 汇率等风险缺项',
    route: '/app/analytics/landed-cost',
    also: ['/app/pricing'],
  },
  {
    key: 'channel',
    title: '准备销售渠道',
    goal: '选择目标销售平台并授权店铺，准备上架渠道',
    route: '/app/channels',
    also: ['/app/channels/shops'],
  },
  {
    key: 'prepare',
    title: '建立商品销售准备',
    goal: '为所选商品建立商品主档（POST /products），作为后续上架销售的统一准备载体',
    route: '/app/market/candidates',
    also: [],
  },
]

/** 步骤 key 有序集合。 */
export const J0_STEP_KEYS = J0_STEPS.map((s) => s.key)

/**
 * 由路由 path 识别当前 J0 步骤；命中 also 前缀也算（如 /app/market/opportunity/123 归属 discovery）。
 * 精确匹配 route 优先于 also 前缀匹配。
 * @param {string} [path] 当前路由 path（可带/不带前导 /）。
 * @returns {object|null} 步骤对象，或 null（不在 J0 链路）。
 */
export function stepFromPath(path = '') {
  if (!path) return null
  const norm = path.startsWith('/') ? path : `/${path}`
  const exact = J0_STEPS.find((s) => s.route === norm)
  if (exact) return exact
  const byAlso = J0_STEPS.find((s) => (s.also || []).some((a) => norm === a || norm.startsWith(`${a}/`)))
  return byAlso || null
}

/** 步骤索引（0 基）；不在链路返回 -1。 */
export function stepIndex(stepKey) {
  return J0_STEP_KEYS.indexOf(stepKey)
}

/** 构造 J0 透传 query：journey 固定；productId 仅在有有效值时带（缺失不传空串）。 */
export function buildJourneyQuery({ productId = null, extra = {} } = {}) {
  const q = { journey: J0_JOURNEY_KEY }
  if (productId != null && productId !== '' && productId !== undefined) {
    q.productId = String(productId)
  }
  return { ...q, ...extra }
}

/** 是否处于 J0 链路（query.journey === 'j0'）。 */
export function isJourneyActive(query = {}) {
  return Boolean(query && query.journey === J0_JOURNEY_KEY)
}

/**
 * 推导下一步：返回 {key,title,route,query}；已是最后一步返回 null。
 * query 透传 journey 与 productId（缺失则不带）。
 */
export function deriveNextStep(currentKey, { productId = null } = {}) {
  const idx = stepIndex(currentKey)
  if (idx < 0 || idx >= J0_STEPS.length - 1) return null
  const next = J0_STEPS[idx + 1]
  return {
    key: next.key,
    title: next.title,
    route: next.route,
    query: buildJourneyQuery({ productId }),
  }
}

/** 推导上一步：返回 {key,title,route,query}；已是第一步返回 null。 */
export function derivePrevStep(currentKey, { productId = null } = {}) {
  const idx = stepIndex(currentKey)
  if (idx <= 0) return null
  const prev = J0_STEPS[idx - 1]
  return {
    key: prev.key,
    title: prev.title,
    route: prev.route,
    query: buildJourneyQuery({ productId }),
  }
}

/**
 * 起点识别（零基础用户）：依据简单信号推荐第一步与说明。
 * @param {{hasShops?:boolean, hasProducts?:boolean, direction?:string}} [profile]
 * @returns {{firstStep:string, reason:string}}
 */
export function identifyStartingPoint(profile = {}) {
  const { hasShops = false, hasProducts = false, direction } = profile
  if (hasProducts) {
    return {
      firstStep: 'sourcing',
      reason: '已存在商品主档，建议从「选择货源」开始核对供货与成本',
    }
  }
  if (hasShops) {
    return {
      firstStep: 'discovery',
      reason: '已连接销售渠道，建议从「研究商品方向」挑品并建主档',
    }
  }
  const dirHint = direction ? `（已选方向：${direction}）` : ''
  return {
    firstStep: 'discovery',
    reason: `零基础起步，先「研究商品方向」挑出想做的商品${dirHint}`,
  }
}

/**
 * 可信度标签映射（对齐 dataLabels.DATA_TAGS）：来源字符串 → 标签码；未识别 → 'UNKNOWN'。
 * @param {string} [source]
 * @returns {string}
 */
export function credibilityTag(source = '') {
  const s = String(source || '').toLowerCase()
  if (s === 'api' || s === 'platform') return 'API_UNVERIFIED'
  if (s === 'csv' || s === 'external' || s === 'import') return 'EXTERNAL_IMPORT'
  if (s === 'manual' || s === 'operator') return 'MANUAL_UNVERIFIED'
  if (s === 'builtin' || s === 'demo') return 'DEMO'
  if (s === 'official' || s === 'verified') return 'OFFICIAL_VERIFIED'
  if (s === 'ai' || s === 'estimated' || s === 'model') return 'AI_ESTIMATED'
  if (s === 'contract' || s === 'contract_test') return 'CONTRACT_TEST'
  return 'UNKNOWN'
}

/**
 * 可信度标签中文 —— **复用单一事实源** `dataLabels.tagInfo`，不再本地复制一份文案
 * （原先本地 MAP 漏 AI_ESTIMATED / CONTRACT_TEST，导致「模型估算」无法标注）。
 * 未知码回 `UNKNOWN`「数据未知」，不猜测。
 */
export function credibilityLabel(code = 'UNKNOWN') {
  return tagInfo(code).label
}

/** 缺值占位符（不当 0）。 */
export const MISSING_PLACEHOLDER = '—'

/**
 * 诚实降级：缺值 → 占位符 "—"；有效值（含 0 / false）原样返回。
 * 缺失判定：null / undefined / NaN / 空字符串。
 * @param {*} value
 * @returns {*}
 */
export function honestValue(value) {
  if (value === null || value === undefined) return MISSING_PLACEHOLDER
  if (typeof value === 'number' && Number.isNaN(value)) return MISSING_PLACEHOLDER
  if (typeof value === 'string' && value.trim() === '') return MISSING_PLACEHOLDER
  return value
}

/**
 * 步骤完成度（基于该步骤关键数据是否齐备；纯函数）。
 * 返回 'done' | 'empty'（二态即可驱动进度展示；partial 由各页自行细化）。
 * @param {string} stepKey
 * @param {object} [stepData] 各步骤关键字段。
 * @returns {'done'|'empty'}
 */
export function stepCompletion(stepKey, stepData = {}) {
  switch (stepKey) {
    case 'discovery':
      return ((stepData.productsCount != null && stepData.productsCount > 0) || stepData.selectedProductId != null)
        ? 'done' : 'empty'
    case 'sourcing':
      return ((stepData.suppliersCount != null && stepData.suppliersCount > 0) || stepData.selectedOffer != null)
        ? 'done' : 'empty'
    case 'cost':
      return (stepData.costComputed === true || stepData.profit != null) ? 'done' : 'empty'
    case 'channel':
      return ((stepData.shopsCount != null && stepData.shopsCount > 0) || stepData.authorizedShop === true)
        ? 'done' : 'empty'
    case 'prepare':
      return (stepData.productMasterId != null) ? 'done' : 'empty'
    default:
      return 'empty'
  }
}
