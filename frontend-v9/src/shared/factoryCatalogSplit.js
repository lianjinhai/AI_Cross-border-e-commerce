/**
 * 工厂目录拆分纯函数（蓝图 R1 包 3 · FP-02 catalog + FP-03 capability）。
 *
 * 既有 FactoryProducts.vue（path /factory/products）承载"商品目录 + 报价产能"两类字段。
 * §B.3 将其拆为：
 *   - FP-02 商品/SKU 目录（catalog）：身份/品类/图片等**商品主档**字段
 *   - FP-03 报价/库存/产能（capability）：报价/MOQ/币种/库存时效等**供货能力**字段
 *
 * 现有 /factory/products 路由保留（仍是主入口），拆分以字段切分呈现，避免破坏 302/深链。
 * 组件（FactoryProducts / Capability）消费本模块决定各页渲染哪些列。
 */

/** FP-02 商品目录列（商品主档：不含报价/MOQ/币种/库存时效）。 */
export const CATALOG_COLUMNS = [
  { key: 'factory_sku', label: '工厂 SKU' },
  { key: 'title', label: '产品' },
  { key: 'category', label: '类目' },
  { key: 'status', label: '状态' },
]

/** FP-03 供货能力列（报价/MOQ/币种/库存时效）。 */
export const CAPABILITY_COLUMNS = [
  { key: 'currency', label: '币种' },
  { key: 'unit_price', label: '出厂价' },
  { key: 'moq', label: 'MOQ' },
  { key: 'lead_days', label: '交期/天' },
  { key: 'monthly_capacity', label: '月产能' },
  { key: 'available_qty', label: '库存' },
]

/** 全列（catalog ∪ capability，供 FactoryProducts 合并展示，保持既有主入口完整）。 */
export const ALL_COLUMNS = [
  ...CATALOG_COLUMNS,
  ...CAPABILITY_COLUMNS,
]

/** 某列归属：'catalog' | 'capability' | null。 */
export function columnGroup(key) {
  if (CATALOG_COLUMNS.some((c) => c.key === key)) return 'catalog'
  if (CAPABILITY_COLUMNS.some((c) => c.key === key)) return 'capability'
  return null
}

/**
 * 把目录行按拆分切出两个子行对象（商品主档行 / 供货能力行）。
 * 用于 catalog 页与 capability 页各自取所需字段，不做字段重复实现。
 *
 * @param {object} row 完整目录行（factoryCatalog 产出的字段集）。
 * @returns {{catalog:object, capability:object}}
 */
export function splitCatalogRow(row = {}) {
  const catalog = {}
  const capability = {}
  for (const key of Object.keys(row)) {
    if (CATALOG_COLUMNS.some((c) => c.key === key)) catalog[key] = row[key]
    else if (CAPABILITY_COLUMNS.some((c) => c.key === key)) capability[key] = row[key]
  }
  // 保留主键便于行级操作/深链（仅当行确实带 id，避免空对象多出 undefined 键）
  if (row.id != null) {
    catalog.id = row.id
    capability.id = row.id
  }
  return { catalog, capability }
}

/** capability 页是否需写权限（报价/MOQ/币种/库存可维护 → 需 supply:write）。 */
export function capabilityRequiresWrite() {
  return true
}
