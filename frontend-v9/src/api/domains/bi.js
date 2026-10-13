import api from '../../shared/api/client'

/**
 * bi 域（契约 §4.2）：对应 backend/app/routers/bi.py（前缀 /bi）。
 * 指标卡口径展开的文案字典见 shared/biCaliber.js（纯函数可测）。
 * 后端 metric_summary 本身不含口径字段，口径说明由前端字典统一维护。
 */

/** 指标汇总：GET /bi/metrics?days= → 指标对象（gmv/net_revenue/contribution_profit...）。 */
export async function fetchMetrics({ days } = {}) {
  return (await api.get('/bi/metrics', { params: { days } })).data
}

/** 数据可信度：GET /bi/data-quality → {grade, real_order_count, ...}。 */
export async function fetchDataQuality() {
  return (await api.get('/bi/data-quality')).data
}

/** 利润趋势分析：GET /bi/profit?days= → {series[], summary, by_category[]}。 */
export async function fetchProfitAnalysis({ days } = {}) {
  return (await api.get('/bi/profit', { params: { days } })).data
}

/** 看板聚合：GET /bi/dashboard → 序列/分布数据。 */
export async function fetchTrends(query = {}) {
  return (await api.get('/bi/dashboard', { params: query })).data
}

/** AI 经营报告：GET /bi/report → {report}（后端同步返回）。 */
export async function generateReport(query = {}) {
  return (await api.get('/bi/report', { params: query })).data
}
