import api from '../../shared/api/client'

/**
 * crossBorder 域（契约 §4.2）：对应 backend/app/routers/cross_border.py（前缀 /cross-border）。
 * 四组配置 CRUD（关税税率/物流路由/平台费率/目的国合规）+ 到岸成本试算。
 * tenant_id 为 null 的行是平台内置口径：租户只读（页面据此禁用编辑/删除）。
 * 计算口径与定价页同源（/landed-cost 转调 services/costing.calc_profit）。
 */

const crud = (segment) => ({
  /** 列表：GET /cross-border/{segment} → {items[]}。 */
  list: (params = {}) => api.get(`/cross-border/${segment}`, { params }).then((r) => r.data),
  /** 新增：POST /cross-border/{segment} → 行 DTO。 */
  create: (data) => api.post(`/cross-border/${segment}`, data).then((r) => r.data),
  /** 更新：PUT /cross-border/{segment}/{id} → {ok, id}。 */
  update: (id, data) => api.put(`/cross-border/${segment}/${id}`, data).then((r) => r.data),
  /** 删除：DELETE /cross-border/{segment}/{id} → {ok}。 */
  remove: (id) => api.delete(`/cross-border/${segment}/${id}`).then((r) => r.data),
})

/** 关税税率 CRUD。 */
export const dutyRates = crud('duty-rates')
/** 物流路由 CRUD。 */
export const logisticsRoutes = crud('logistics-routes')
/** 平台费率 CRUD。 */
export const platformFees = crud('platform-fees')
/** 目的国合规规则 CRUD。 */
export const complianceRules = crud('compliance-rules')

/**
 * 到岸成本试算：POST /cross-border/landed-cost
 * {product_id, destination_country?, price?, channel_type?, site?, qty?}
 * → 成本明细（与 /pricing/calc 同一套 costing 实现）。
 */
export async function calcLandedCost(data = {}) {
  return (await api.post('/cross-border/landed-cost', data)).data
}

/**
 * 某商品在目的国的准入要求 × 证据核验：GET /cross-border/products/{id}/compliance?country=
 * → {country, required[], missing[], expired[], satisfied[], passed, blocking[]}
 *
 * 注意 `passed=true` 且 `required=[]` 的含义是**未收录要求**，不是「无需认证」——
 * 页面必须用 `/labels` 的 basis.reasons 说清这一点，别直接渲染绿勾。
 */
export async function productCompliance(productId, { country = '' } = {}) {
  return (await api.get(`/cross-border/products/${productId}/compliance`,
    { params: { country } })).data
}

/**
 * 登记/更新一条目的国合规证据：POST /cross-border/products/{id}/compliance
 * {destination_country, requirement, evidence_ref, valid_until?, note?} → 更新后的核验结果
 */
export async function saveComplianceEvidence(productId, data = {}) {
  return (await api.post(`/cross-border/products/${productId}/compliance`, data)).data
}

/**
 * 标签包版本历史（只读，M2-E）：GET /cross-border/products/{id}/labels?country=&shop_id=&limit=
 * → {items[], basis?}；给 country 才有 basis（要求/证据/缺项/原因）。
 * **写入不在这里**：标签只能由 Launch 动作 GENERATE_LABEL / REGENERATE_LABEL 生成。
 */
export async function labelPackages(productId, { country = '', shopId = 0, limit = 20 } = {}) {
  const params = { country, limit }
  if (shopId) params.shop_id = shopId
  return (await api.get(`/cross-border/products/${productId}/labels`, { params })).data
}
