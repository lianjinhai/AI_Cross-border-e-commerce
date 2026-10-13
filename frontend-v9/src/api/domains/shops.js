import api from '../../shared/api/client'

/**
 * shops 域（契约 §4.2）：对应 backend/app/routers/shops.py（前缀 /shops）。
 * 列表含授权态/token 过期态；authorize 实参为店铺 id（后端
 * GET /shops/{shop_id}/authorize_url，见 Shops.vue 既有调用）。
 */

/** 店铺列表：GET /shops → {items[]（含授权态/token 过期态）}。 */
export async function fetchShops(params = {}) {
  return (await api.get('/shops', { params })).data
}

/** 发起授权：GET /shops/{shopId}/authorize_url → 授权跳转地址。 */
export async function authorize(shopId) {
  return (await api.get(`/shops/${shopId}/authorize_url`)).data
}

/** 授权码兑换：POST /shops/{shopId}/exchange_code {code}。 */
export async function exchangeCode(shopId, data = {}) {
  return (await api.post(`/shops/${shopId}/exchange_code`, data)).data
}

/** 刷新授权：POST /shops/{id}/refresh。 */
export async function refresh(id) {
  return (await api.post(`/shops/${id}/refresh`)).data
}

/** 同步订单：POST /shops/{id}/sync_orders → 同步结果。 */
export async function syncOrders(id) {
  return (await api.post(`/shops/${id}/sync_orders`)).data
}

/** 保存类目映射：POST /shops/category-mappings（shop_id = id）。 */
export async function saveCategoryMapping(id, data = {}) {
  return (await api.post('/shops/category-mappings', { shop_id: id, ...data })).data
}
