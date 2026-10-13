/**
 * AI 决策依据视图模型（UX-E #25，纯函数）。
 * 决策链只读审计：过滤项取值域对照 backend/app/routers/ai.py decisions()。
 */

/** Agent 过滤项（覆盖 AiDecision.agent 真实写入值；空值 = 全部）。 */
export const AGENT_OPTIONS = [
  { label: '全部 Agent', value: '' },
  { label: '选品 discovery', value: 'discovery' },
  { label: '定价 pricing', value: 'pricing' },
  { label: 'Listing listing', value: 'listing' },
  { label: '客服 support', value: 'support' },
  { label: '编排 orchestrator', value: 'orchestrator' },
]

/** 对象类型过滤项（AiDecision.subject_type 索引域，逐条对应真实业务对象）。 */
export const SUBJECT_TYPE_OPTIONS = [
  { label: '全部对象', value: '' },
  { label: '商品 product', value: 'product' },
  { label: 'Listing', value: 'listing' },
  { label: '订单 order', value: 'order' },
  { label: '供应商 supplier', value: 'supplier' },
  { label: '趋势 trend', value: 'trend' },
]

/** 判定结果单行摘要（k=v 顿号连接；空对象给明确占位）。 */
export function briefDecision(decision) {
  const entries = Object.entries(decision || {})
  if (!entries.length) return '—'
  return entries.map(([k, v]) => `${k}=${v}`).join('，')
}

/** JSON 美化（决策/依据抽屉展示用；循环引用等异常回退 String）。 */
export function prettyJson(obj) {
  try {
    return JSON.stringify(obj ?? {}, null, 2)
  } catch {
    return String(obj)
  }
}

/** 判定理由列表（evidence.reasons 数组；缺失给空数组，不伪造）。 */
export function decisionReasons(evidence) {
  const r = evidence?.reasons
  return Array.isArray(r) ? r : []
}

/**
 * 深链预填（矩阵 #25「从定价建议可跳到对应决策依据」）：
 * 把 route.query（agent/subject_type/subject_id）规整为过滤模型，非法值丢弃。
 */
export function filtersFromQuery(query = {}) {
  const agent = AGENT_OPTIONS.some((o) => o.value === query.agent) ? query.agent : ''
  const subjectType = SUBJECT_TYPE_OPTIONS.some((o) => o.value === query.subject_type)
    ? query.subject_type
    : ''
  const rawId = Number(query.subject_id)
  const subjectId = Number.isInteger(rawId) && rawId > 0 ? rawId : null
  return { agent, subjectType, subjectId }
}
