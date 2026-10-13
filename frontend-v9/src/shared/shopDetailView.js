/**
 * 店铺详情/健康（CH-03）纯函数模块。
 *
 * 顶部三态（授权有效 / 商品能力已验证 / 订单能力已验证）：
 * 订单/商品能力验证端点未核（§7#8）→ 未核项显"未验证"而非 ✅。
 * 四 Tab：Product / 订单 / 同步任务 / 证书配置。
 */

/** 三态定义。 */
export const SHOP_TRISTATE = [
  { key: 'auth', label: '授权有效', verifiedField: 'auth_verified' },
  { key: 'product', label: '商品能力已验证', verifiedField: 'product_verified' },
  { key: 'order', label: '订单能力已验证', verifiedField: 'order_verified' },
]

/** 四 Tab 定义（顺序即渲染顺序）。 */
export const SHOP_TABS = [
  { key: 'product', label: '商品' },
  { key: 'orders', label: '订单' },
  { key: 'sync', label: '同步任务' },
  { key: 'cert', label: '证书配置' },
]

/**
 * 三态判定：从店铺 DTO 推导每个态的展示（纯函数）。
 * - auth：status==='authorized' → 有效；'expired'/'failed' → 失效；其余 → 未验证。
 * - product / order：端点未核（§7#8），DTO 未提供对应字段 → 一律"未验证"。
 *
 * @param {object} shop 店铺 DTO。
 * @returns {Array<{key:string,label:string,state:'valid'|'invalid'|'unverified'}>}
 */
export function shopTriStates(shop = {}) {
  const status = shop?.status || ''
  const authState = status === 'authorized' ? 'valid'
    : (status === 'expired' || status === 'failed' || status === 'pending') ? 'invalid'
    : 'unverified'
  // 商品/订单能力验证端点未核（§7#8）：仅当 DTO 显式给出已验证布尔时才显 valid，否则恒 unverified。
  const productState = shop?.product_verified === true ? 'valid' : 'unverified'
  const orderState = shop?.order_verified === true ? 'valid' : 'unverified'
  return [
    { key: 'auth', label: '授权有效', state: authState },
    { key: 'product', label: '商品能力已验证', state: productState },
    { key: 'order', label: '订单能力已验证', state: orderState },
  ]
}

/** 三态展示文案。 */
export const TRISTATE_LABEL = {
  valid: '有效',
  invalid: '失效',
  unverified: '未验证',
}

/**
 * 四 Tab 的可用性判定（纯函数）。
 * - sync Tab 恒可用（同步任务列表）；cert Tab 无证书 → 空态而非隐藏。
 *
 * @param {object} shop 店铺 DTO。
 * @returns {Array<{key,label,disabled:boolean,hint:string}>}
 */
export function shopTabStates(shop = {}) {
  void shop // 当前无端点缺项降级需求；保留参数供后续扩展
  return SHOP_TABS.map((t) => ({ ...t, disabled: false, hint: '' }))
}

/**
 * 深链构造（站内白名单）：店铺详情 path。
 * 携带 store_id（=店铺 id）与 return_to（站内白名单校验）。
 *
 * @param {string} shopId 店铺 ID。
 * @param {string} [returnTo] 回跳目标（须站内白名单，由 entityLink.js 校验）。
 * @returns {string} 形如 `/app/channels/shops/{id}?return_to=...`。
 */
export function buildShopDetailLink(shopId, returnTo = '') {
  const base = `/app/channels/shops/${shopId}`
  return returnTo ? `${base}?return_to=${encodeURIComponent(returnTo)}` : base
}
