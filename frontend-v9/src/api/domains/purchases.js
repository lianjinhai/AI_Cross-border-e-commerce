import api from '../../shared/api/client'

/**
 * purchases 域（契约 §4.2）：对应 backend/app/routers/purchases.py（前缀 /purchases）。
 * 状态机：draft → submitted → received；draft/submitted 可 cancelled（后端 409 拦非法流转）。
 */

/** 采购单列表：GET /purchases → {items[], total}。 */
export async function fetchPurchases({ page, status, supplierId } = {}) {
  return (await api.get('/purchases', {
    params: { page_num: page, status, supplier_id: supplierId },
  })).data
}

/**
 * 创建采购单：POST /purchases {product_id, qty, supplier_id?, note?} → 采购单 DTO。
 * supplier_id 缺省时后端自动选最优货源报价。
 */
export async function createPurchase(data = {}) {
  return (await api.post('/purchases', data)).data
}

/**
 * 一键从预测生成：POST /purchases/from_forecast {product_ids?, qty_multiplier?} →
 * {created[], skipped[]}（商用门禁未通过时 created 为空、skipped 带原因）。
 */
export async function generateFromForecast({ productIds = [], qtyMultiplier = 1.0 } = {}) {
  return (await api.post('/purchases/from_forecast', {
    product_ids: productIds, qty_multiplier: qtyMultiplier,
  })).data
}

/** 更新采购单：PUT /purchases/{id} {qty?/status?/note?}（非法流转后端 409 拒绝）。 */
export async function updatePurchase(id, data = {}) {
  return (await api.put(`/purchases/${id}`, data)).data
}

/** 收货入库：POST /purchases/{id}/receive {qty?} → {ok, in_stock_added, onhand_now, purchase}。 */
export async function receivePurchase(id, data = {}) {
  return (await api.post(`/purchases/${id}/receive`, data)).data
}

/** 取消采购单：DELETE /purchases/{id}（已收货不可取消，后端 400 拒绝）。 */
export async function removePurchase(id) {
  return (await api.delete(`/purchases/${id}`)).data
}
