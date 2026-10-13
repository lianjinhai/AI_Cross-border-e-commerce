import api from '../../shared/api/client'

/**
 * discovery 域（UX-C 实现）：对应 backend/app/routers/discovery.py（前缀 /discovery）。
 * 趋势（含来源如实区分 api/csv/builtin）/ 关键词扩展 / 选品评分 / 一键选品 /
 * 商品真实经营表现（数据飞轮，演示数据不计入）。
 */

/** 趋势列表：GET /discovery/trends → {items[]}。 */
export async function fetchTrends() {
  return (await api.get('/discovery/trends')).data
}

/** AI 扫描趋势：POST /discovery/trends/scan → {items[]}。 */
export async function scanTrends() {
  return (await api.post('/discovery/trends/scan')).data
}

/** 趋势来源分布：GET /discovery/trends/source → {has_real_data, hint, ...}。 */
export async function fetchTrendSource() {
  return (await api.get('/discovery/trends/source')).data
}

/** 导入真实趋势 CSV：POST /discovery/trends/import {csv_text} → {imported, updated, errors[]}。 */
export async function importTrends({ csvText = '', platformDefault = 'csv' } = {}) {
  return (await api.post('/discovery/trends/import', {
    csv_text: csvText, platform_default: platformDefault,
  })).data
}

/** 关键词扩展：POST /discovery/expand {keyword} → {keywords[]}。 */
export async function expandKeywords(keyword) {
  return (await api.post('/discovery/expand', { keyword })).data
}

/** 一键选品：POST /discovery/pick {limit} → {items[]}（机会分最高候选）。 */
export async function pickCandidates(limit = 3) {
  return (await api.post('/discovery/pick', { limit })).data
}

/** 选品评分分页：GET /discovery/scores → {items[], total}。 */
export async function fetchScores({ page, productId } = {}) {
  return (await api.get('/discovery/scores', {
    params: { page_num: page, product_id: productId },
  })).data
}

/** 单品重评分：POST /discovery/score/{productId} → 评分 DTO。 */
export async function scoreProduct(productId) {
  return (await api.post(`/discovery/score/${productId}`)).data
}

/** 商品真实经营表现：GET /discovery/performance/{productId}?window_days → 表现 DTO。 */
export async function fetchPerformance(productId, windowDays = 30) {
  return (await api.get(`/discovery/performance/${productId}`, {
    params: { window_days: windowDays },
  })).data
}
