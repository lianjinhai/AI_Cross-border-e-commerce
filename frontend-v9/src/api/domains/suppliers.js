import api from '../../shared/api/client'

/**
 * suppliers 域（契约 §4.2）：对应 backend/app/routers/suppliers.py（前缀 /suppliers）。
 * 供应商库列表 / 详情 / 新增 / AI 评分 / 补货预警 / 货源匹配（真实端点 1:1 薄封装）。
 */

/** 供应商列表：GET /suppliers → {items[]}（含最近一次 score_total）。 */
export async function fetchSuppliers() {
  return (await api.get('/suppliers')).data
}

/** 供应商详情：GET /suppliers/{id} → 供应商 DTO（含 offers、score）。 */
export async function fetchSupplier(id) {
  return (await api.get(`/suppliers/${id}`)).data
}

/** 新增供应商：POST /suppliers → 供应商 DTO。 */
export async function createSupplier(data = {}) {
  return (await api.post('/suppliers', data)).data
}

/** AI 综合评分：POST /suppliers/{id}/score → 评分结果（含 total/reasons）。 */
export async function scoreSupplier(id) {
  return (await api.post(`/suppliers/${id}/score`)).data
}

/**
 * 补货预警（AI 销量预测）：GET /suppliers/forecast。
 * 返回含 shortages[]（部分通道包 context_patch，由页面兜底解包）。
 */
export async function fetchForecast(productId) {
  return (await api.get('/suppliers/forecast', {
    params: { product_id: productId },
  })).data
}

/** 货源匹配：POST /suppliers/match {product_id} → 最优货源匹配结果。 */
export async function matchBest(productId) {
  return (await api.post('/suppliers/match', { product_id: productId })).data
}

/** 按商品查报价：GET /suppliers/offers?product_id= → {items[]}。 */
export async function fetchOffers(productId) {
  return (await api.get('/suppliers/offers', { params: { product_id: productId } })).data
}
