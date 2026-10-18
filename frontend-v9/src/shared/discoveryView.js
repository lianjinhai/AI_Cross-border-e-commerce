/**
 * 商品方向研究视图纯逻辑层（B2 批次，UX-C / Discovery）。
 *
 * 诚实契约（不可违反）：
 * - 候选方向卡片从 ProductScore 行（按 total 取 Top N）派生；每张卡片的「需求」
 *   是否有合法海外市场证据，由评分 reasons 中引用的趋势词，回溯实时 trends 列表
 *   的 api/csv/builtin 谱系判定——绝不把内置演示趋势或默认估算伪装成真实需求。
 * - 供应商成本（supplier_price）只用于「利润」因子（毛利率输入），不进入「需求」
 *   因子，更不冒充海外市场数据；本层只透传原始分值，不做任何重标。
 * - 所有筛选都是真实本地语义：关键词同时作用于趋势表与候选池，类目按商品
 *   category 本地过滤；无后端数据的「市场/预算」不渲染筛选控件，只作为画像
 *   上下文 chips 展示（本页范围参考 / 待补）。
 * - 数据时间取 trends 与 scores 的 created_at 最大值；DTO 无时间戳则返回 null，
 *   由调用方渲染「更新时间未知」，绝不编造日期。
 *
 * 全部为纯函数，组件逻辑下沉于此以便 vitest 直测（前端无 @vue/test-utils）。
 */

const TREND_KW_RE = /趋势词[「『](.+?)[」』]/

/** 从评分 reasons 中解析被引用的趋势关键词（用于回溯需求证据来源）。无则 null。 */
export function extractTrendKeyword(reasons = []) {
  const list = Array.isArray(reasons) ? reasons : []
  for (const r of list) {
    if (typeof r !== 'string') continue
    const m = TREND_KW_RE.exec(r)
    if (m && m[1]) return m[1].trim()
  }
  return null
}

/**
 * 判定某评分行的「需求」证据状态。
 *  - 能匹配到 api/csv 趋势 → 有依据（verified）
 *  - 匹配到 builtin 演示趋势 / 无匹配趋势 / 趋势未加载 → 待验证（pending）
 * 返回 { status, kind, label, basis }，kind ∈ {api,csv,builtin,none}。
 */
export function resolveEvidenceStatus(score = {}, trends = []) {
  const kw = extractTrendKeyword(score && score.reasons)
  if (!kw) {
    return {
      status: 'pending',
      kind: 'none',
      label: '默认估算·待验证',
      basis: '评分未引用任何趋势词，需求为默认估算，无市场证据',
    }
  }
  const trend = (Array.isArray(trends) ? trends : []).find(
    (t) => t && (t.keyword || '') === kw,
  )
  if (!trend) {
    return {
      status: 'pending',
      kind: 'none',
      label: '默认估算·待验证',
      basis: `引用的趋势词「${kw}」未在实时趋势中找到，无法核验出处`,
    }
  }
  if (trend.source === 'api') {
    return {
      status: 'verified',
      kind: 'api',
      label: '官方API·有依据',
      basis: `需求基于官方API趋势「${kw}」`,
    }
  }
  if (trend.source === 'csv') {
    return {
      status: 'verified',
      kind: 'csv',
      label: 'CSV导入·有依据',
      basis: `需求基于CSV导入趋势「${kw}」`,
    }
  }
  return {
    status: 'pending',
    kind: 'builtin',
    label: '演示数据·待验证',
    basis: `需求基于内置演示趋势「${kw}」，非真实海外市场数据`,
  }
}

/**
 * 从 ProductScore 行派生候选方向卡片（Top N by total）。
 * productsById：product_id -> {title, category}，缺省回退为「商品 #id」。
 * 返回卡片数组，每张含四因子原始分值、model、reasons、证据状态与依据说明。
 */
export function deriveCandidateDirections({
  scores = [],
  productsById = {},
  trends = [],
  topN = 5,
} = {}) {
  const rows = Array.isArray(scores) ? scores : []
  const ranked = [...rows].sort(
    (a, b) => Number(b && b.total) - Number(a && a.total),
  )
  const n = Math.max(1, Number(topN) || 5)
  const top = ranked.slice(0, n)
  const map = productsById && typeof productsById === 'object' ? productsById : {}
  return top.map((s) => {
    const pid = s && s.product_id
    const product = map[pid] || {}
    const evidence = resolveEvidenceStatus(s, trends)
    return {
      productId: pid,
      title: product.title ? String(product.title) : `商品 #${pid}`,
      category: product.category || '',
      demand: Number(s && s.demand) || 0,
      competition: Number(s && s.competition) || 0,
      profit: Number(s && s.profit) || 0,
      risk: Number(s && s.risk) || 0,
      total: Number(s && s.total) || 0,
      model: (s && s.model) || 'rule',
      reasons: Array.isArray(s && s.reasons) ? s.reasons : [],
      evidenceStatus: evidence.status,
      evidenceKind: evidence.kind,
      evidenceLabel: evidence.label,
      evidenceBasis: evidence.basis,
    }
  })
}

/** 本地关键词筛选：趋势表按 keyword/platform 包含匹配（大小写不敏感）。 */
export function filterTrendsByKeyword(trends = [], keyword = '') {
  const k = String(keyword || '').trim().toLowerCase()
  if (!k) return trends
  return (Array.isArray(trends) ? trends : []).filter((t) => {
    const kw = (t && t.keyword || '').toLowerCase()
    const pf = (t && t.platform || '').toLowerCase()
    return kw.includes(k) || pf.includes(k)
  })
}

/** 本地关键词筛选：候选池按 标题/类目/依据说明 包含匹配。 */
export function filterCandidatesByKeyword(candidates = [], keyword = '') {
  const k = String(keyword || '').trim().toLowerCase()
  if (!k) return candidates
  return (Array.isArray(candidates) ? candidates : []).filter((c) => {
    const hay = [
      c && c.title,
      c && c.category,
      c && c.evidenceBasis,
    ].join(' ').toLowerCase()
    return hay.includes(k)
  })
}

/** 本地类目筛选：按商品 category 精确匹配（空值不过滤）。 */
export function filterCandidatesByCategory(candidates = [], category = '') {
  const c = String(category || '').trim()
  if (!c) return candidates
  return (Array.isArray(candidates) ? candidates : []).filter(
    (x) => (x && x.category || '') === c,
  )
}

/** 候选集合中出现的类目清单（去重排序），供类目下拉使用。 */
export function listCategories(candidates = []) {
  const set = new Set()
  for (const c of (Array.isArray(candidates) ? candidates : [])) {
    if (c && c.category) set.add(c.category)
  }
  return [...set].sort()
}

/**
 * 数据时间：取 rows 中 created_at 的最大值（"YYYY-MM-DD HH:MM:SS" 字典序即时间序）。
 * 无时间戳返回 null —— 调用方据此渲染「更新时间未知」。
 */
export function maxTimestamp(rows = []) {
  const times = (Array.isArray(rows) ? rows : [])
    .map((r) => (r && r.created_at) || '')
    .filter(Boolean)
  if (!times.length) return null
  return times.reduce((a, b) => (a > b ? a : b))
}

/** 合并趋势与评分的时间戳，返回最新一条（无则 null）。 */
export function freshnessTimestamp({ trends = [], scores = [] } = {}) {
  return maxTimestamp([...(Array.isArray(trends) ? trends : []), ...(Array.isArray(scores) ? scores : [])])
}

/**
 * 画像上下文 chips：budget/targetMarket/risk 三项。
 * present 为真 → 展示值 + 「本页范围参考」；为假 → 「待补」（由调用方跳 /onboarding?step=1）。
 * 不渲染为筛选控件，仅作范围参考。
 */
export function buildContextChips(profile) {
  const p = profile || {}
  const defs = [
    { key: 'budget', label: '预算' },
    { key: 'targetMarket', label: '目标市场' },
    { key: 'risk', label: '风险偏好' },
  ]
  return defs.map(({ key, label }) => {
    const value = p[key]
    const present = !!(value && String(value).trim())
    return {
      key,
      label,
      present,
      value: present ? String(value).trim() : '',
    }
  })
}
