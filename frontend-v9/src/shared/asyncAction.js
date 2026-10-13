/**
 * 异步操作状态机（蓝图 §6.4，包 1 P0 共享组件纯函数下沉）。
 *
 * 状态机：提交中→成功/失败/409(状态已变→刷新,不丢输入)/超时(UNCERTAIN:"结果待核查")。
 * 超时后只允许"重新查询状态"，禁盲重试副作用。
 */

/** 状态枚举。 */
export const ASYNC_STATES = {
  IDLE: 'IDLE',
  SUBMITTING: 'SUBMITTING',
  SUCCESS: 'SUCCESS',
  FAILED: 'FAILED',
  CONFLICT: 'CONFLICT',       // 409 状态已变
  UNCERTAIN: 'UNCERTAIN',     // 超时/结果待核查
}

/** 事件枚举。 */
export const ASYNC_EVENTS = {
  SUBMIT: 'SUBMIT',
  RESOLVED: 'RESOLVED',       // 正常响应（成功/失败/409 由 classifyResult 分流）
  TIMEOUT: 'TIMEOUT',
  REQUERY: 'REQUERY',         // 重新查询状态
  RESET: 'RESET',            // 重置到 IDLE
}

/**
 * 分类 API 响应结果。
 * 成功 → 'SUCCESS'；HTTP 409 → 'CONFLICT'；其他非 2xx → 'FAILED'。
 * 超时/网络错误 → 'TIMEOUT'。
 *
 * @param {object} response { status?: number, data?: any, isTimeout?: boolean, isNetworkError?: boolean }
 * @returns {string} ASYNC_STATES 之一。
 */
export function classifyResult(response) {
  if (!response || typeof response !== 'object') return ASYNC_STATES.FAILED
  if (response.isTimeout) return ASYNC_STATES.UNCERTAIN
  if (response.isNetworkError) return ASYNC_STATES.UNCERTAIN
  const status = response.status ?? 0
  if (status >= 200 && status < 300) return ASYNC_STATES.SUCCESS
  if (status === 409) return ASYNC_STATES.CONFLICT
  return ASYNC_STATES.FAILED
}

/**
 * 状态机转移：根据当前状态 + 事件 → 下一状态。
 * 非法转移返回当前状态（不变）。
 *
 * 合法转移：
 * IDLE + SUBMIT → SUBMITTING
 * SUBMITTING + RESOLVED → SUCCESS/FAILED/CONFLICT（由 classifyResult 决定，此处传 event detail）
 * SUBMITTING + TIMEOUT → UNCERTAIN
 * UNCERTAIN + REQUERY → SUBMITTING（重新查询，非重新提交副作用）
 * SUCCESS + RESET → IDLE
 * FAILED + RESET → IDLE
 * CONFLICT + RESET → IDLE
 *
 * @param {string} current 当前状态。
 * @param {string} event 事件。
 * @param {object} [detail] 附加信息（如 classifyResult 的返回值）。
 * @returns {string} 下一状态。
 */
export function nextState(current, event, detail = {}) {
  if (current === ASYNC_STATES.IDLE && event === ASYNC_EVENTS.SUBMIT) return ASYNC_STATES.SUBMITTING
  if (current === ASYNC_STATES.SUBMITTING && event === ASYNC_EVENTS.RESOLVED) {
    const result = detail.result || ASYNC_STATES.FAILED
    if (result === ASYNC_STATES.SUCCESS) return ASYNC_STATES.SUCCESS
    if (result === ASYNC_STATES.CONFLICT) return ASYNC_STATES.CONFLICT
    return ASYNC_STATES.FAILED
  }
  if (current === ASYNC_STATES.SUBMITTING && event === ASYNC_EVENTS.TIMEOUT) return ASYNC_STATES.UNCERTAIN
  if (current === ASYNC_STATES.UNCERTAIN && event === ASYNC_EVENTS.REQUERY) return ASYNC_STATES.SUBMITTING
  if (event === ASYNC_EVENTS.RESET) return ASYNC_STATES.IDLE
  return current // 非法转移不变
}

/**
 * 生成幂等键（客户端侧，服务端仍做 CAS 校验）。
 * 格式：{objectType}:{objectId}:{action}:{timestamp}
 *
 * @param {object} p
 * @param {string} p.objectType 对象类型（如 'product','order'）。
 * @param {string|number} p.objectId 对象 ID。
 * @param {string} p.action 动作码。
 * @param {number} [p.timestamp] 时间戳（默认 Date.now()）。
 * @returns {string}
 */
export function buildIdempotencyKey({ objectType = '', objectId = '', action = '', timestamp = 0 } = {}) {
  const ts = timestamp || Date.now()
  return `${objectType}:${objectId}:${action}:${ts}`
}
