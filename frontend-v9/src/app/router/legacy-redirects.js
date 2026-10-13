/**
 * 旧路径 → 新路径 302 映射表（契约 §3.2，30 条全量有对应，无孤儿）。
 *
 * - 实现为查表数据 + 纯函数 `legacyRedirectTarget(to)`，供路由表注册 redirect
 *   与单测直测（R8：/platform-admin 与 /platform-admin?tab=audit 同 path 异
 *   query，**必须显式判断 to.query.tab**）；
 * - 带 `:id` 的旧路径透传参数与 query；
 * - 查表未命中的旧路径统一落 404（不做静默 /app 兜底，便于暴露映射遗漏）。
 */

/** 30 行映射（含 /platform-admin 的 query 分支标记）。 */
export const LEGACY_REDIRECTS = [
  { from: '/login', to: '/console/login', note: '全空间共用' },
  { from: '/', to: '/app', note: '外壳根' },
  { from: '/dashboard', to: '/app', note: '经营工作台（矩阵#3）' },
  { from: '/discovery', to: '/app/market/discovery', note: '#4' },
  { from: '/products', to: '/app/products', note: '#5' },
  { from: '/listings', to: '/app/listings', note: '#6' },
  { from: '/compliance', to: '/app/compliance', note: '#7 定位改为报告中心' },
  { from: '/compliance-workbench', to: '/app/compliance/approvals', note: '#8 合规员默认落地' },
  { from: '/launch', to: '/app/launch', note: '#9' },
  { from: '/launch/:id', to: '/app/launch/:id', note: '#10 id 透传' },
  { from: '/shops', to: '/app/channels/shops', note: '#11' },
  { from: '/suppliers', to: '/app/supply/suppliers', note: '#12 拆分' },
  { from: '/factory-portal', to: '/factory/products', note: '#13' },
  { from: '/pricing', to: '/app/pricing', note: '#14' },
  { from: '/ads', to: '/app/ads', note: '#15' },
  { from: '/orders', to: '/app/orders', note: '#16' },
  { from: '/refunds', to: '/app/refunds', note: '#17' },
  { from: '/settlements', to: '/app/settlements', note: '#18' },
  { from: '/support', to: '/app/support', note: '#19' },
  { from: '/workflows', to: '/app/ai/workflows', note: '#20' },
  { from: '/knowledge', to: '/app/ai/knowledge', note: '#21' },
  { from: '/bi', to: '/app/analytics/bi', note: '#22' },
  { from: '/finance', to: '/app/analytics/finance', note: '#23' },
  { from: '/alerts', to: '/app/risk/alerts', note: '#24' },
  { from: '/ai-decisions', to: '/app/ai/decisions', note: '#25' },
  { from: '/users', to: '/app/settings/team', note: '#26' },
  { from: '/settings', to: '/app/settings/ai', note: '#27' },
  // R8：同 path 异 query —— 守卫/重定向必须显式判断 to.query.tab（#28）
  { from: '/platform-admin', to: '/console/overview', note: '#28 拆 4 页：/console/tenants、/console/maintenance 随迁', queryBranch: true },
  { from: '/platform-admin?tab=audit', to: '/console/audit', note: 'query 子态独立成页，query 语义废弃', queryBranch: true },
]

/** 含 :id 的旧路径 → 新路径段（参数透传）。 */
const PARAM_REDIRECTS = [
  { from: '/launch/:id', to: '/app/launch/:id' },
]

/** /platform-admin 的 R8 query 分支：显式判断 to.query.tab。 */
function platformAdminTarget(query = {}) {
  return query.tab === 'audit' ? '/console/audit' : '/console/overview'
}

/**
 * 查表：旧路径 → 新目标（vue-router redirect 目标形态：字符串或 location 对象）。
 * 未命中返回 null（由 catch-all 落 404，不做静默兜底）。
 *
 * @param {{path: string, params?: object, query?: object}} to vue-router 目标位置。
 * @returns {string|{path:string, query?:object}|null}
 */
export function legacyRedirectTarget(to) {
  const path = to?.path
  if (typeof path !== 'string') return null
  const query = to?.query || {}
  const keepQuery = Object.keys(query).length ? { query } : undefined

  // R8：/platform-admin 同 path 异 query；query 子态语义废弃 → 目标不透传 query。
  if (path === '/platform-admin') {
    return platformAdminTarget(query)
  }

  const plain = LEGACY_REDIRECTS.find((r) => r.from === path && !r.queryBranch && !r.from.includes(':'))
  if (plain) {
    // /login 之外一律保留 query（如 return_to 等站内回跳参数）。
    return keepQuery ? { path: plain.to, query } : plain.to
  }

  for (const rule of PARAM_REDIRECTS) {
    const seg = rule.from.split('/')
    const actual = path.split('/')
    if (seg.length !== actual.length) continue
    let ok = true
    const params = {}
    for (let i = 0; i < seg.length; i += 1) {
      if (seg[i].startsWith(':')) params[seg[i].slice(1)] = actual[i]
      else if (seg[i] !== actual[i]) { ok = false; break }
    }
    if (ok) {
      const target = rule.to.replace(/:([a-z]+)/g, (_, name) => encodeURIComponent(params[name] || ''))
      return keepQuery ? { path: target, query } : target
    }
  }
  return null
}
