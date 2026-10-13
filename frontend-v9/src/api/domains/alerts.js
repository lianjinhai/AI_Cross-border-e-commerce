import api from '../../shared/api/client'

/**
 * alerts 域（契约 §4.2）：对应 backend/app/routers/alerts.py（前缀 /alerts）。
 * 告警「去处理」深链映射见 features/optimization/alertTargets.js（纯函数可测）。
 */

/** 告警列表：GET /alerts → {items[], returned, total, counts}。 */
export async function fetchAlerts({ status, level } = {}) {
  return (await api.get('/alerts', { params: { status, level } })).data
}

/** 确认告警：PUT /alerts/{id}/ack → 告警 DTO（保留审计痕迹，不删除）。 */
export async function ackAlert(id) {
  return (await api.put(`/alerts/${id}/ack`)).data
}

/** 巡检规则列表：GET /alerts/rules → {items[]}。 */
export async function fetchAlertRules() {
  return (await api.get('/alerts/rules')).data
}

/** 更新规则：PUT /alerts/rules/{id} {enabled?, level?, threshold?} → 规则 DTO。 */
export async function updateAlertRule(id, data = {}) {
  return (await api.put(`/alerts/rules/${id}`, data)).data
}

/** 手动巡检：POST /alerts/scan → {created, skipped}。 */
export async function scanAlerts() {
  return (await api.post('/alerts/scan')).data
}
