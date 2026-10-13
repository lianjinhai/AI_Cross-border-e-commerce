/**
 * 工厂任务投影纯函数（蓝图 R1 包 3 · FP-04 备货/贴标，§B.3 / §F#5）。
 *
 * 后端 task projection 未接入 → 工厂门户备货/贴标只能呈**只读队列 + 待接入**，
 * 写操作（确认受理/提交证明/无法完成）一律灰化，禁止假 API 调用、假成功态。
 *
 * 组件（StockingTasks.vue）只消费本模块的纯函数，判定逻辑集中于此以便 vitest 直测。
 */

/**
 * 工厂任务类型（备货 / 贴标 两大类，蓝图 §5.18 顶部任务条）。
 * 仅用于展示标签，不代表后端已支持。
 */
export const FACTORY_TASK_KINDS = {
  stocking: { label: '备货', icon: 'Package' },
  labeling: { label: '贴标', icon: 'PriceTag' },
}

/** 任务队列主态（11 态码透传，经 SectionState 渲染；不页面自写）。 */
export const TASK_QUEUE_STATE = {
  LOADING: 'LOADING',
  EMPTY: 'EMPTY_NEW',        // 暂无任务（待接入 → 无真实数据源）
  READY: 'ready',
  ERROR: 'ERROR',
}

/**
 * 写操作可用性判定（§F#5：三按钮灰化 + "暂不支持"）。
 *
 * 规则：task projection 未接入时（projectionAvailable=false）三个写动作全部
 * 不可执行；即使接入后，也要看后端能力（capability）是否支持该动作。
 * 返回 { code, executable, reason }：executable=false 时组件走 NextActionPanel
 * 的"技术未接通"分支（灰化 + 原因），**不触发任何 API**。
 *
 * @param {string} actionCode 'accept'|'submit_proof'|'cannot_complete'
 * @param {object} [ctx]
 * @param {boolean} [ctx.projectionAvailable] 后端 task projection 是否已接入（当前恒为 false）。
 * @param {string} [ctx.capability] 该任务实际支持的动作能力码（缺省 ''）。
 * @returns {{code:string, executable:boolean, reason:string}}
 */
export function writeActionPolicy(actionCode, { projectionAvailable = false, capability = '' } = {}) {
  const kind = writeActionKind(actionCode)
  if (!kind) return { code: actionCode, executable: false, reason: '未知操作' }
  if (!projectionAvailable) {
    return { code: actionCode, executable: false, reason: '任务同步待接入，写操作暂缺' }
  }
  if (capability && capability !== kind) {
    return { code: actionCode, executable: false, reason: '该任务未开放此操作' }
  }
  return { code: actionCode, executable: true, reason: '' }
}

/** 动作码 → 任务能力类别（三写动作各归一类）。 */
function writeActionKind(actionCode) {
  const map = {
    accept: 'accept',
    submit_proof: 'submit_proof',
    cannot_complete: 'cannot_complete',
  }
  return map[actionCode] ?? ''
}

/**
 * 队列主态推导：空队列在"待接入"语境下显 EMPTY（暂无任务），避免误报 PARTIAL。
 * @param {boolean} loading
 * @param {boolean} hasError
 * @param {number} count 队列条数
 * @returns {string} 11 态码（LOADING/ERROR/EMPTY_NEW/ready）
 */
export function queueStateCode(loading, hasError, count) {
  if (loading) return TASK_QUEUE_STATE.LOADING
  if (hasError) return TASK_QUEUE_STATE.ERROR
  if (!count) return TASK_QUEUE_STATE.EMPTY
  return TASK_QUEUE_STATE.READY
}

/**
 * 待接入标记文案（§F#5 用户可见文案，集中在此避免组件自写）。
 * @returns {{title:string, detail:string}}
 */
export function pendingIntegrationCopy() {
  return {
    title: '任务同步待接入',
    detail: '工厂任务投影（备货/贴标）后端端点尚未接入；当前仅展示只读队列，确认受理/提交证明/无法完成暂不可用。',
  }
}

/**
 * 贴标授权边界说明（蓝图 §5.18 约束：授权某贴标步骤 ≠ 批准整条 Launch）。
 * @returns {string}
 */
export function labelingScopeNote() {
  return '工厂被授权执行某个贴标步骤，不代表其能批准整条 Launch；贴标通过不等于上线放行。'
}
