import api from '../../shared/api/client'

/**
 * ai 域（契约 §4.2）：对应 backend/app/routers/ai.py（前缀 /ai）。
 * 设置读写 / Orchestrator 对话 / 决策依据链 / 调用日志。
 * 注意：PUT /ai/settings 中 llm 与 open_1688 为平台级 key（仅平台服务商可写，
 * 租户 OWNER 保存会被 403 拒绝——页面按 has_key 只读提示，不做假授权）。
 */

/** AI 设置：GET /ai/settings → {llm, platform_fees, fx, rules, open_1688}（密钥回空串 + has_key）。 */
export async function fetchAiSettings() {
  return (await api.get('/ai/settings')).data
}

/** 保存设置：PUT /ai/settings（按 key 分流写入，返回最新设置）。 */
export async function saveAiSettings(data = {}) {
  return (await api.put('/ai/settings', data)).data
}

/**
 * AI 决策依据链：GET /ai/decisions?agent=&subject_type=&subject_id=&limit= → {items[], total}。
 * 只读审计（只增不删，红线 4）。
 */
export async function fetchAiDecisions({ agent = '', subjectType = '', subjectId = null, limit = 100 } = {}) {
  return (await api.get('/ai/decisions', {
    params: { agent, subject_type: subjectType, subject_id: subjectId, limit },
  })).data
}

/** AI 调用日志：GET /ai/logs?limit= → {items[]}（不含 prompt，审计口径）。 */
export async function fetchAiLogs(limit = 50) {
  return (await api.get('/ai/logs', { params: { limit } })).data
}

/** Orchestrator 对话：POST /ai/chat {message} → {reply, intent, actions, data}。 */
export async function sendChat(message) {
  return (await api.post('/ai/chat', { message })).data
}
