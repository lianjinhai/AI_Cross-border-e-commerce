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

/** 添加店铺：POST /shops → 店铺 DTO。 */
export async function createShop(data = {}) {
  return (await api.post('/shops', data)).data
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

/** 保存类目映射：POST /shops/category-mappings {platform, system_category, platform_category_id, note}。 */
export async function saveCategoryMapping(data = {}) {
  return (await api.post('/shops/category-mappings', data)).data
}

/** 平台元数据：GET /shops/platforms → {items[]（label/markets/auth_model/能力位）}。 */
export async function fetchPlatforms() {
  return (await api.get('/shops/platforms')).data
}

/** 更新店铺配置：PUT /shops/{id}。 */
export async function updateShop(id, data = {}) {
  return (await api.put(`/shops/${id}`, data)).data
}

/** 删除店铺：DELETE /shops/{id}。 */
export async function removeShop(id) {
  return (await api.delete(`/shops/${id}`)).data
}

/** 类目映射列表：GET /shops/category-mappings → {items[]}。 */
export async function fetchCategoryMappings() {
  return (await api.get('/shops/category-mappings')).data
}

/** 删除类目映射：DELETE /shops/category-mappings/{id}。 */
export async function removeCategoryMapping(id) {
  return (await api.delete(`/shops/category-mappings/${id}`)).data
}

/** TikTok/店铺上架条件预检：GET /shops/{shopId}/listing_readiness/{listingId}。 */
export async function fetchListingReadiness(shopId, listingId) {
  return (await api.get(`/shops/${shopId}/listing_readiness/${listingId}`)).data
}

/** 平台规则包列表：GET /shops/platform_rules → {items[]}（维护页用）。 */
export async function fetchPlatformRules() {
  return (await api.get('/shops/platform_rules')).data
}

/** 检查规则更新：POST /shops/platform_rules/{platform}/check_updates → {updated, hint?}。 */
export async function checkPlatformRuleUpdates(platform) {
  return (await api.post(`/shops/platform_rules/${platform}/check_updates`)).data
}

/** 清空演示数据：POST /shops/purge_demo_data → {deleted: {...}}（不可恢复）。 */
export async function purgeDemoData() {
  return (await api.post('/shops/purge_demo_data')).data
}
