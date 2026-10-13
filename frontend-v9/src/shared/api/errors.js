/**
 * 错误规整（契约 §4.3）：`normalizeError(err) → {message, traceId?, blockers?}`。
 *
 * 页面级错误交 ErrorState 呈现，**不再重复 toast**；`traceId`/`blockers` 来自
 * 后端 `detail` envelope（{code,message,blockers,...}）或 `trace_id` 字段，
 * 缺失时字段省略（不伪造）。纯函数、可 vitest 直测。
 */

/**
 * @param {unknown} err axios 错误 / 普通 Error / 任意值。
 * @returns {{message: string, traceId?: string, blockers?: Array}} 规整结果。
 */
export function normalizeError(err) {
  const detail = err?.response?.data?.detail
  const traceId = err?.response?.data?.trace_id
    || (detail && typeof detail === 'object' ? detail.trace_id : undefined)
  const blockers = detail && typeof detail === 'object' && Array.isArray(detail.blockers)
    ? detail.blockers
    : undefined

  let message
  if (detail && typeof detail === 'object') message = detail.message
  else if (typeof detail === 'string' && detail) message = detail
  else if (err instanceof Error && err.message) message = err.message
  else if (typeof err?.message === 'string' && err.message) message = err.message
  else message = '请求失败，请稍后重试'

  const result = { message }
  if (traceId) result.traceId = String(traceId)
  if (blockers) result.blockers = blockers
  return result
}
