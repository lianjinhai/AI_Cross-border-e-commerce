import api from '../../shared/api/client'
import { newIdempotencyKey } from '../../composables/launchCenter'

/**
 * launch 域（契约 §4.2）：对应 backend/app/routers/launch.py（前缀 /launch）。
 * 沿用 composables/launchCenter.js 封装逻辑平移；三条铁律不变：
 *   1. 写路径必须带 `Idempotency-Key` 头 + body `expected_revision`（缺一即 409/422）；
 *   2. 列表响应字段是 **`page_num`**；服务端先 Scope 后分页；
 *   3. 错误体是 `err.response.data.detail` 对象。
 */

/** 上线流程列表：GET /launch → {items[], total}。 */
export async function fetchLaunches({ page, filters = {}, view } = {}) {
  return (await api.get('/launch', {
    params: { page_num: page, ...(view ? { view } : {}), ...filters },
  })).data
}

/** 创建上线流程：POST /launch {product_id, shop_id,...} → 流程 DTO。 */
export async function createLaunch(data = {}) {
  return (await api.post('/launch', data, {
    headers: { 'Idempotency-Key': newIdempotencyKey('launch') },
  })).data
}

/** 流程详情：GET /launch/{id} → {steps[], timeline[], mode:'GUIDED'|'PROFESSIONAL',...}。 */
export async function fetchLaunch(id) {
  return (await api.get(`/launch/${id}`)).data
}

/** 执行步骤动作：POST /launch/{id}/actions/{action} → 步骤回执。 */
export async function runStepAction(id, stepId, action, payload = {}, opts = {}) {
  return (await api.post(`/launch/${id}/actions/${action}`,
    { step_code: stepId, expected_revision: opts.expectedRevision, payload },
    { headers: { 'Idempotency-Key': opts.idempotencyKey || newIdempotencyKey(`launch-${id}-${action}`) } },
  )).data
}

/** 同步流程：POST /launch/{id}/sync（仅支持 refresh 模式）→ 同步回执。 */
export async function syncLaunch(id, expectedRevision) {
  return (await api.post(`/launch/${id}/sync`,
    { mode: 'refresh', expected_revision: expectedRevision },
  )).data
}
