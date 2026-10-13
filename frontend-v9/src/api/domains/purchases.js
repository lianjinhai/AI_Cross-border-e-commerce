import api from '../../shared/api/client'

/**
 * purchases 域（契约 §4.2）：对应 backend/app/routers/purchases.py（前缀 /purchases）。
 */

/** 采购单列表：GET /purchases → {items[], total}。 */
export async function fetchPurchases({ page, status, supplierId } = {}) {
  return (await api.get('/purchases', {
    params: { page_num: page, status, supplier_id: supplierId },
  })).data
}

/** 创建采购单：POST /purchases → 采购单 DTO。 */
export async function createPurchase(data = {}) {
  return (await api.post('/purchases', data)).data
}

/** 一键从预测生成：POST /purchases/from_forecast {supplier_id} → 生成结果。 */
export async function generateFromForecast(supplierId) {
  return (await api.post('/purchases/from_forecast', { supplier_id: supplierId })).data
}
