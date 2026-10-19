/**
 * 商品池派生设计阶段（B3 衍生设计，无原型底图——刻意：商品池为列表优先页面，
 * 阶段信号由后端 `signals` 派生，不做图像化重排）。
 *
 * 阶段阶梯（诚实、不可臆造）：
 * - signals 缺失/null → UNKNOWN，渲染「—」（绝不给假阶段）。
 * - offers_count = 0 → 未接货源（琥珀，待比选）。
 * - offers_count > 0 且 channels_count = 0 → 货源就绪（可进入经营）。
 * - channels_count > 0 → 渠道准备中（已铺渠道）。
 *
 * 主动作随阶段变化：
 * - 未接货源 → 去比选 → /app/supply/matching?product_id={id}
 * - 其余 → 查看经营中心 → /app/products/{id}
 */

/**
 * 由 signals 派生阶段。
 * @param {object|null|undefined} signals {offers_count, channels_count, assets_verified_count}
 * @returns {{key:string, label:string, tone:string}}
 */
export function stageFromSignals(signals) {
  // 缺 signals 或缺失关键字段（offers_count）→ 视为 absent，渲染「—」，绝不编造阶段。
  if (!signals || typeof signals !== 'object' || !('offers_count' in signals)) {
    return { key: 'UNKNOWN', label: '—', tone: 'neutral' }
  }
  const offersCount = Number(signals.offers_count ?? 0)
  const channelsCount = Number(signals.channels_count ?? 0)

  if (offersCount === 0) {
    return { key: 'NO_SOURCE', label: '未接货源', tone: 'warning' }
  }
  if (channelsCount === 0) {
    return { key: 'SOURCE_READY', label: '货源就绪', tone: 'success' }
  }
  return { key: 'CHANNEL_PREPARING', label: '渠道准备中', tone: 'info' }
}

/**
 * 由 signals + 商品 id 派生主动作。
 * @param {object|null|undefined} signals
 * @param {number|string} id 商品 id。
 * @returns {{label:string, path:string}}
 */
export function primaryAction(signals, id) {
  const stage = stageFromSignals(signals)
  if (stage.key === 'NO_SOURCE') {
    return { label: '去比选', path: `/app/supply/matching?product_id=${id}` }
  }
  return { label: '查看经营中心', path: `/app/products/${id}` }
}
