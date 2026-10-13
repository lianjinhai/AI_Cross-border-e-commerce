/**
 * StoreSwitcher / StoreScope 纯函数（蓝图 §5.1，包 1 P1 基础）。
 *
 * StoreScope 语义对齐：仅销售店铺，禁止 source 类型当销售过滤。
 * "全部/特定"两态持久化键沿用 v9_selected_shop。
 */

/**
 * 过滤销售店铺（剔除 source 类型——source 是货源，不是销售店铺）。
 * 店铺对象：{ id, name, type?, status?, ... }；type='source' 为货源类型。
 *
 * @param {Array} shops 全量店铺列表。
 * @returns {Array} 仅销售店铺。
 */
export function filterSalesShops(shops) {
  if (!Array.isArray(shops)) return []
  return shops.filter((s) => s && s.type !== 'source')
}

/**
 * 判定持久化键值：'' 或 null 表示"全部店铺"，具体 shopId 表示"特定店铺"。
 * 从 localStorage 读取并归一化。
 *
 * @returns {string} 当前 scope 值（'' = 全部）。
 */
export function resolveScopeKey() {
  try {
    const val = localStorage.getItem('v9_selected_shop')
    return val ? val : ''
  } catch {
    return ''
  }
}

/**
 * 判定是否"全部店铺"模式。
 * @param {string|number|null|undefined} shopId 当前选中值。
 * @returns {boolean} true = 全部。
 */
export function isAllShops(shopId) {
  return shopId === '' || shopId === null || shopId === undefined
}

/**
 * 获取未接店铺引导项（供 StoreSwitcher unconnected prop 消费）。
 * status 为 'pending' 或缺失 OAuth 的店铺列入。
 *
 * @param {Array} shops 店铺列表。
 * @returns {Array<{id, name, hint}>} 未接引导项。
 */
export function unconnectedShops(shops) {
  if (!Array.isArray(shops)) return []
  return shops
    .filter((s) => s && s.status === 'pending' && s.type !== 'source')
    .map((s) => ({ id: s.id, name: s.name, hint: '待连接' }))
}
