/**
 * 控制台 AI 资源与成本纯函数（蓝图 R1 包 3 · PC-05，§B.3 / §5.19 / §F#8）。
 *
 * 蓝图 §5.19：AI 资源页记录模型路由、Token/成本、限流、失败、策略和工作空间配额，
 * 但**只在真实数据可用时显示**。ai 配额读端点**未核** → 缺数据不渲染图表，显"未接入"。
 *
 * 本模块定义配额/成本区缺项判定与"未接入"标记，组件（AiResources.vue）只消费。
 * 红线：不编造 Token 成本、不渲染假图表。
 */

/** AI 资源展示区（蓝图 §5.19 五类）。 */
export const AI_RESOURCE_SECTIONS = [
  { code: 'model_route', label: '模型路由' },
  { code: 'token_cost', label: 'Token / 成本' },
  { code: 'throttle', label: '限流' },
  { code: 'failure', label: '失败' },
  { code: 'quota', label: '工作空间配额' },
]

/**
 * 配额数据可用判定：仅当 ai 配额读端点显式返回 quota 对象才视为已接入。
 * @param {object} [aiQuota] ai 配额读端点返回体（未核 → 传 null/undefined）。
 * @returns {boolean}
 */
export function hasAiQuotaSource(aiQuota) {
  return Boolean(aiQuota && typeof aiQuota === 'object'
    && Object.prototype.hasOwnProperty.call(aiQuota, 'used')
    && Object.prototype.hasOwnProperty.call(aiQuota, 'limit'))
}

/**
 * 某展示区状态（11 态码 + 文案）：无真实数据源 → NOT_CONFIGURED 语境"未接入"。
 * @param {boolean} sectionDataAvailable 该区块是否拿到真实数据。
 * @returns {{code:string, title:string, tone:string}}
 */
export function aiSectionState(sectionDataAvailable) {
  if (sectionDataAvailable) return { code: 'ready', title: '', tone: 'info' }
  return { code: 'NOT_CONFIGURED', title: '未接入', tone: 'neutral' }
}

/** 整页占位文案（ai 配额读端点未核，§F#8 用户可见文案）。 */
export function aiResourcesPendingCopy() {
  return {
    title: 'AI 资源配额未接入',
    detail: 'AI 配额读端点尚未核；模型路由 / Token / 成本 / 限流 / 失败 / 配额均无真实数据，故不渲染图表，仅标记"未接入"。',
  }
}

/** 缺值不渲染 0（Token/成本缺项 → "—"，避免假数字）。 */
export function aiNumberOrDash(value) {
  return value == null ? '—' : value
}
