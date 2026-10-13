/**
 * 平台控制台纯函数（UX-E 前半，旧 PlatformAdmin.vue 逻辑平移）：
 * 徽标查表 / 授权到期判定 / 统计卡 / 清空结果文本化。组件只消费，vitest 直测。
 */

/** 套餐徽标（查表；未知值退化 info）。 */
export const PLANS = {
  trial: { text: '试用版', type: 'info' },
  pro: { text: '专业版', type: 'primary' },
  enterprise: { text: '企业版', type: 'warning' },
}

export function planTag(plan) {
  return PLANS[plan] || { text: plan || '—', type: 'info' }
}

/** 租户状态徽标。 */
export const STATUSES = {
  active: { text: '正常', type: 'success' },
  suspended: { text: '停用', type: 'danger' },
}

export function statusTag(status) {
  return STATUSES[status] || { text: status || '未知', type: 'info' }
}

/** 授权到期：license_until 缺失或非法日期一律视为未过期（不误伤）。 */
export function isExpired(licenseUntil, now = Date.now()) {
  if (!licenseUntil) return false
  const t = new Date(licenseUntil).getTime()
  return !Number.isNaN(t) && t < now
}

/** 平台规则包的平台名展示标签。 */
export const PLATFORM_LABELS = {
  1688: '1688（阿里巴巴）',
  shopee: 'Shopee',
  tiktok: 'TikTok Shop',
  amazon: 'Amazon SP-API',
}

export function platformLabel(value) {
  return PLATFORM_LABELS[value] || value || '—'
}

/** 数字兜底：null/undefined → 0。 */
export function n(v) {
  return v == null ? 0 : v
}

/** 大数格式化：null/undefined → '—'。 */
export function fmt(v) {
  return v == null ? '—' : Number(v).toLocaleString()
}

/** 总览 → 统计卡（顺序冻结：与旧页 6 卡一致）。 */
export function statCardsFromOverview(overview = {}) {
  return [
    { label: '租户总数', value: fmt(overview.tenants) },
    { label: '正常租户', value: fmt(overview.active) },
    { label: '停用租户', value: fmt(overview.suspended) },
    { label: '30 天内到期', value: fmt(overview.expiring_in_30d) },
    { label: '用户总数', value: fmt(overview.users) },
    { label: '订单总数', value: fmt(overview.orders_total) },
  ]
}

/** 清空演示数据结果 → 文本（{products: 3, ...} → "products 3，…"）。 */
export function purgeResultText(result) {
  if (result && typeof result === 'object') {
    return Object.entries(result).map(([k, v]) => `${k} ${v}`).join('，')
  }
  return result != null ? String(result) : ''
}

/**
 * 列表响应归一：后端部分端点返回裸数组 / {items} / {tenants} 三态（旧页平移）。
 */
export function normalizeList(data) {
  if (Array.isArray(data)) return { items: data, total: data.length }
  const items = data?.items || data?.tenants || data?.logs || []
  return { items, total: data?.total ?? items.length }
}
