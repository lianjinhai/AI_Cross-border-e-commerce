import api from '../../shared/api/client'

/**
 * bi 域（契约 §4.2）：对应 backend/app/routers/bi.py（前缀 /bi）。
 * 指标数组每项含口径说明字段（BI 口径展开需求）。
 */

/** 指标列表：GET /bi/metrics → 指标数组（每项含口径说明字段）。 */
export async function fetchMetrics() {
  return (await api.get('/bi/metrics')).data
}

/** 趋势/看板序列数据：GET /bi/dashboard → 序列数据。 */
export async function fetchTrends(query = {}) {
  return (await api.get('/bi/dashboard', { params: query })).data
}

/** 生成报告：GET /bi/report → {taskId?, report}（异步进度按回执轮询，无 taskId 则同步返回）。 */
export async function generateReport(query = {}) {
  return (await api.get('/bi/report', { params: query })).data
}
