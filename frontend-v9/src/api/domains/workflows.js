import api from '../../shared/api/client'

/**
 * workflows 域（契约 §4.2）：对应 backend/app/routers/workflows.py（前缀 /workflows）。
 * LEGACY_AUTOMATION 流：模板 / 运行 / 历史 / 恢复（resume 走后端安全检查点）。
 */

/** 模板列表：GET /workflows/templates → {items[]}（含 key/name/description/steps[{agent,action,params}]）。 */
export async function fetchTemplates() {
  return (await api.get('/workflows/templates')).data
}

/**
 * 运行模板：POST /workflows/run {template_key, context} → 运行 DTO（含 steps[]）。
 * 后端 404 = 模板不存在；写权限由 require_write 服务端把关。
 */
export async function runWorkflow(templateKey, context = {}) {
  return (await api.post('/workflows/run', { template_key: templateKey, context })).data
}

/** 运行历史：GET /workflows/runs?limit= → {items[]}（created_at 倒序，上限 100）。 */
export async function fetchRuns(limit = 20) {
  return (await api.get('/workflows/runs', { params: { limit } })).data
}

/** 运行详情：GET /workflows/runs/{id} → 运行 DTO（含 steps[]，按 seq 排序）。 */
export async function fetchRun(runId) {
  return (await api.get(`/workflows/runs/${runId}`)).data
}

/** 恢复失败/阻塞运行：POST /workflows/runs/{id}/resume → 运行 DTO。 */
export async function resumeRun(runId) {
  return (await api.post(`/workflows/runs/${runId}/resume`)).data
}
