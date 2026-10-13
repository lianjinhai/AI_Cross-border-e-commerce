import api from '../../shared/api/client'

/**
 * admin 域（契约 §4.2）：对应 backend/app/routers/admin.py（前缀 /admin）。
 * 平台服务商（superadmin）专属：租户管理 / 代客访问 / 审计 / 总览。
 * 代客 enter 仅签发目标租户 token；凭据（admin_password）后端一次性返回，前端不缓存。
 */

/** 平台总览：GET /admin/overview → {tenants, active, suspended, expiring_in_30d, users, orders_total}。 */
export async function fetchOverview() {
  return (await api.get('/admin/overview')).data
}

/** 租户列表：GET /admin/tenants → {items[]（含 stats 用量）, total}。 */
export async function fetchTenants({ page, pageSize = 15 } = {}) {
  return (await api.get('/admin/tenants', { params: { page_num: page, page_size: pageSize } })).data
}

/** 开通租户：POST /admin/tenants → 租户 DTO + admin_username/admin_password（一次性）。 */
export async function createTenant(data = {}) {
  return (await api.post('/admin/tenants', data)).data
}

/** 更新租户：PUT /admin/tenants/{id}（续期 license_days / 停启用 status / 备注）。 */
export async function updateTenant(id, data = {}) {
  return (await api.put(`/admin/tenants/${id}`, data)).data
}

/** 代客进入：POST /admin/tenants/{id}/enter → {token, tenant, hint}（服务端已记录审计）。 */
export async function enterTenant(id) {
  return (await api.post(`/admin/tenants/${id}/enter`)).data
}

/** 代客访问审计：GET /admin/access_logs → {items[]}。 */
export async function fetchAccessLogs({ limit = 50 } = {}) {
  return (await api.get('/admin/access_logs', { params: { limit } })).data
}

/** 全平台 AI 调用日志：GET /admin/ai_logs → {items[]}（不含 prompt）。 */
export async function fetchAiLogs({ limit = 100 } = {}) {
  return (await api.get('/admin/ai_logs', { params: { limit } })).data
}
