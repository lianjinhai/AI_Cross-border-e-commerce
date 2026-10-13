import api from '../../shared/api/client'

/**
 * products 域（契约 §4.2）：对应 backend/app/routers/products.py +
 * product_assets.py + product_channels.py（前缀均 /products）。
 * 商品 DTO 含 assets、channels 只读数据；dropship 走 purchases 链路。
 */

/** 商品列表：GET /products → {items[], total}。 */
export async function fetchProducts({ page, keyword, source } = {}) {
  return (await api.get('/products', {
    params: { page_num: page, keyword, source },
  })).data
}

/** 商品详情：GET /products/{id} → 商品 DTO（含 assets、channels 只读）。 */
export async function fetchProduct(id) {
  return (await api.get(`/products/${id}`)).data
}

/** 创建商品：POST /products → 商品 DTO。 */
export async function createProduct(data = {}) {
  return (await api.post('/products', data)).data
}

/** 更新商品：PUT /products/{id} → 商品 DTO。 */
export async function updateProduct(id, data = {}) {
  return (await api.put(`/products/${id}`, data)).data
}

/** URL 采集：POST /products/collect_url {url} → 标准化结果。 */
export async function scrapeByUrl({ url } = {}) {
  return (await api.post('/products/collect_url', { url })).data
}

/** 源码解析采集（强反爬站点兜底）：POST /products/collect_html {url, html}。 */
export async function collectFromHtml({ url = '', html = '' } = {}) {
  return (await api.post('/products/collect_html', { url, html })).data
}

/** 演示源批量采集：POST /products/collect {source_platform, keyword, count}。 */
export async function collectDemo({ sourcePlatform = '1688', keyword = '', count = 5 } = {}) {
  return (await api.post('/products/collect', {
    source_platform: sourcePlatform, keyword, count,
  })).data
}

/** 导出商品 CSV（blob 下载）。 */
export async function exportCsv() {
  return api.get('/products/export', { responseType: 'blob' })
}

/** 触发标准化：POST /products/{id}/standardize → 标准化结果。 */
export async function standardize(id) {
  return (await api.post(`/products/${id}/standardize`)).data
}

/** 一键铺货下单：POST /purchases/dropship（走 purchases 链路）→ 采购单 DTO。 */
export async function createDropshipOrder(id, data = {}) {
  return (await api.post('/purchases/dropship', { product_id: id, ...data })).data
}

/** 商品素材列表：GET /products/{id}/assets。 */
export async function fetchAssets(id) {
  return (await api.get(`/products/${id}/assets`)).data
}

/** 新增素材：POST /products/{id}/assets。 */
export async function addAsset(id, data = {}) {
  return (await api.post(`/products/${id}/assets`, data)).data
}

/** 素材核验：POST /products/{id}/assets/{assetId}/verify。 */
export async function verifyAsset(id, assetId) {
  return (await api.post(`/products/${id}/assets/${assetId}/verify`)).data
}

/** 渠道只读列表：GET /products/{id}/channels。 */
export async function fetchChannels(id) {
  return (await api.get(`/products/${id}/channels`)).data
}
