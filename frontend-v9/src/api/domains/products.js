import api from '../../shared/api/client'

/**
 * products 域（契约 §4.2）：对应 backend/app/routers/products.py +
 * product_assets.py + product_channels.py（前缀均 /products）。
 * 商品 DTO 含 assets、channels 只读数据；dropship 走 purchases 链路。
 *
 * R3-1A 修正（E01/E02/E05）：
 * - fetchChannels：后端 channels_dto 返回 {product, total, channels[]}，直接透传，
 *   不猜测 .items（launch_dto.channels_dto / product_channels.py）。
 * - 素材读/写一律带 shop_id（product_assets.py：GET 要求 shop_id Query(...) 必填；
 *   AssetIn.shop_id 必填；验证 shop.market/platform 必须与素材适用范围一致）。
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

/**
 * 商品素材分页列表（E02）：GET /products/{id}/assets?shop_id=...&page_num&。
 * 后端 shop_id 为 Query(...) 必填；素材按店铺 market/platform 隔离，缺店铺上下文不得调用。
 * → {items[]（ProductAsset 全字段）， total, page, page_size}。
 */
export async function fetchAssets(id, { shopId, pageNum = 1, pageSize = 20 } = {}) {
  if (!Number.isInteger(shopId) || shopId < 1) {
    throw new Error('素材列表必须指定目标店铺 shop_id（缺店铺上下文，禁止猜测默认店铺）')
  }
  return (await api.get(`/products/${id}/assets`, {
    params: { shop_id: shopId, page_num: pageNum, page_size: pageSize },
  })).data
}

/**
 * 登记素材（E05）：POST /products/{id}/assets。
 * 后端 AssetIn（AssetRegistration + shop_id，extra=forbid）必填：
 * asset_key/expected_version/asset_type/uri/content_hash(sha256 hex64)/rights_status/
 * source/market/platform + shop_id；SUPPLIER_AUTHORIZED/LICENSED 还需 rights_evidence_ref。
 * 前端不得替后端臆造 content_hash——缺真实哈希时拒绝提交并提示登记哈希服务缺口。
 */
const ASSET_CONTENT_HASH_RE = /^[a-f0-9]{64}$/

export function isAssetContentHash(value) {
  return ASSET_CONTENT_HASH_RE.test(String(value || ''))
}

export async function addAsset(id, data = {}) {
  return (await api.post(`/products/${id}/assets`, data)).data
}

/**
 * 素材核验（E05）：POST /products/{id}/assets/{assetId}/verify。
 * 后端 ReviewIn 必填 {shop_id, expected_version, decision: VERIFIED|REJECTED,
 * evidence_ref, reason}；仅合规审批人（compliance:approve）可调用。
 */
export async function verifyAsset(id, assetId, review = {}) {
  return (await api.post(`/products/${id}/assets/${assetId}/verify`, review)).data
}

/**
 * 渠道只读聚合（E01）：GET /products/{id}/channels。
 * 后端 channels_dto → {product, total, channels:[{shop:{id,name,platform,market},
 * active_launch, history[]}]；active_launch/history 为 launch_list_item。直接透传。
 */
export async function fetchChannels(id) {
  return (await api.get(`/products/${id}/channels`)).data
}
