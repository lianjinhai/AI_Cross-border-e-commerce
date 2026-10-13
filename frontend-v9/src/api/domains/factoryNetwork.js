import api from '../../shared/api/client'

/**
 * factoryNetwork 域（契约 §4.2）：对应 backend/app/routers/factory_network.py
 * （前缀 /factory-network）。UX-E 仅封装**工厂门户（portal）**端点——门户是
 * FACTORY_COLLABORATOR 的自助面；机会匹配/晋升为运营侧能力，由 UX-E 后半（AI 页）按需补。
 */

/** 门户身份：GET /factory-network/portal/me → {supplier}。 */
export async function fetchPortalMe() {
  return (await api.get('/factory-network/portal/me')).data
}

/** 本厂供给目录：GET /factory-network/portal/products → {items[]}。 */
export async function fetchPortalProducts() {
  return (await api.get('/factory-network/portal/products')).data
}

/** 新增供给产品：POST /factory-network/portal/products → 目录项 DTO。 */
export async function createPortalProduct(data = {}) {
  return (await api.post('/factory-network/portal/products', data)).data
}

/** 更新供给产品（价格/产能/交期，记录确认时间）：PUT /factory-network/portal/products/{id}。 */
export async function updatePortalProduct(id, data = {}) {
  return (await api.put(`/factory-network/portal/products/${id}`, data)).data
}
