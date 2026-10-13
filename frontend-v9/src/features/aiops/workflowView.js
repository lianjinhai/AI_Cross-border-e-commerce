/**
 * AI 工作流视图模型（UX-E #20，纯函数）。
 *
 * 运行向导（WorkflowStepper 消费方）：模板 steps → 分步说明；
 * 运行历史恢复：失败/阻塞运行置顶排序；运行详情：步骤状态映射。
 * 所有取值对照 backend/app/workflows/engine.py 与 models.py 字段，不伪造。
 */

/** Agent → 中文名（与旧 Workflows.vue 一致，逐字迁移）。 */
export const AGENT_LABELS = {
  discovery: '市场发现',
  product: '商品分析',
  supplier: '供应链',
  compliance: '合规',
  listing: 'Listing',
  pricing: '定价',
  ads: '广告',
}

export function agentLabel(agent) {
  return AGENT_LABELS[agent] || agent
}

/** 运行状态中：失败/阻塞/部分成功可恢复（与旧页恢复按钮条件一致）。 */
export const RECOVERABLE_RUN_STATUSES = ['failed', 'blocked', 'partial']

export function isRecoverableRun(run) {
  return RECOVERABLE_RUN_STATUSES.includes(run?.status)
}

/**
 * 运行历史排序（矩阵 #20「失败运行卡片置顶」）：可恢复组在前，
 * 组内按 created_at 倒序。不修改原数组。
 */
export function sortRunsForRecovery(runs = []) {
  return [...runs].sort((a, b) => {
    const ra = isRecoverableRun(a) ? 0 : 1
    const rb = isRecoverableRun(b) ? 0 : 1
    if (ra !== rb) return ra - rb
    return String(b.created_at || '').localeCompare(String(a.created_at || ''))
  })
}

/** 模板步骤参数 → 人读说明（运行向导 hint；无参数给明确文案，不渲染空串）。 */
export function paramsHint(params = {}) {
  const entries = Object.entries(params || {})
  if (!entries.length) return '该步骤无参数，自动执行'
  return entries
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join('；')
    .slice(0, 120)
}

/**
 * 模板 → 运行向导分步模型（WorkflowStepper props.steps）：
 * 首步为运行说明，中间为模板各步骤（agent·action + 参数说明），末步为确认。
 */
export function runWizardSteps(template) {
  return [
    {
      key: 'intro',
      label: '运行说明',
      hint: template?.description || '按模板编排自动执行各步骤',
    },
    ...((template?.steps || []).map((s, i) => ({
      key: `step-${i}`,
      label: `${agentLabel(s.agent)}·${s.action}`,
      hint: paramsHint(s.params),
    }))),
    {
      key: 'confirm',
      label: '确认运行',
      hint: '提交后立即执行；失败/阻塞运行可在运行历史一键恢复',
    },
  ]
}

/** 工作流步骤状态 → el-steps status（逐字迁移旧 stepStatus）。 */
const STEP_STATUS_MAP = {
  success: 'success',
  running: 'process',
  failed: 'error',
  blocked: 'error',
  pending: 'wait',
  skipped: 'wait',
}

export function stepFlowStatus(status) {
  return STEP_STATUS_MAP[status] || 'wait'
}

/** 步骤描述摘要（逐字迁移旧 stepDesc：错误优先，output 首键摘要，最多 150 字）。 */
export function stepDesc(step) {
  if (step?.error) return `错误：${step.error}`
  const output = step?.output || {}
  const keys = Object.keys(output).filter((k) => k !== 'context_patch')
  if (!keys.length) return step?.status || ''
  const k = keys[0]
  const v = output[k]
  const summary = Array.isArray(v)
    ? `${k}: ${v.length} 条`
    : typeof v === 'object'
      ? `${k}: ${JSON.stringify(v).slice(0, 120)}`
      : `${k}: ${v}`
  return summary.slice(0, 150)
}

/** 运行详情步骤高亮位：首个非 success 步骤索引；全部成功则为步数。 */
export function runActiveStep(steps = []) {
  const idx = steps.findIndex((s) => s.status !== 'success')
  return idx === -1 ? steps.length : idx
}
