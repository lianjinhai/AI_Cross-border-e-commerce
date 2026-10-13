/**
 * 告警「去处理」深链映射（UX-D #24）：rule_key → 目标页（断链归零）。
 * key 清单 = backend/app/services/alerting.py DEFAULT_RULES 的 9 条规则，
 * 未收录的 key 返回 null（不渲染可点击入口，不猜深链）。
 */

export const ALERT_TARGETS = {
  stockout_risk: { path: '/app/supply/purchases', label: '去生成采购单' },
  ads_burning: { path: '/app/ads', label: '去优化广告' },
  price_below_floor: { path: '/app/pricing', label: '去调整定价' },
  policy_changed: { path: '/app/listings', label: '去复核 Listing' },
  refund_spike: { path: '/app/refunds', label: '去处理售后' },
  supplier_delay: { path: '/app/supply/suppliers', label: '去查看供应商' },
  fx_volatility: { path: '/app/analytics/finance', label: '去维护汇率' },
  shipping_degraded: { path: '/app/orders', label: '去查看订单' },
  listing_stale: { path: '/app/listings', label: '去优化 Listing' },
}

/** 深链解析：命中返回 {path, label}，未命中返回 null。 */
export function alertTarget(ruleKey) {
  return ALERT_TARGETS[ruleKey] || null
}
