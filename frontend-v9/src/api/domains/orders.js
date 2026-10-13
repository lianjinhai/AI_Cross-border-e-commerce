import api from '../../shared/api/client'

/**
 * orders 域（契约 §4.2）：对应 backend/app/routers/orders.py（前缀 /orders）。
 * 非法状态流转由后端拒绝，前端 StateBar 预校验；物流轨迹待接入不渲染。
 */

/** 订单列表：GET /orders → {items[], total}。 */
export async function fetchOrders({ page, status, shopId } = {}) {
  return (await api.get('/orders', {
    params: { page_num: page, status, shop_id: shopId },
  })).data
}

/**
 * CSV 导入：POST /orders/import {csv_text} → {ok[], errors:[{row, reason}]}。
 * 后端入参为 csv_text 文本（见 Orders.vue 既有调用），文件读取由视图层完成。
 */
export async function importCsv({ csvText = '' } = {}) {
  return (await api.post('/orders/import', { csv_text: csvText })).data
}

/** 更新订单状态：PUT /orders/{id}/status {status}（非法流转由后端拒绝）。 */
export async function updateStatus(id, status) {
  return (await api.put(`/orders/${id}/status`, { status })).data
}

/** 发货：POST /orders/{id}/ship → 履约回执。 */
export async function ship(id, data = {}) {
  return (await api.post(`/orders/${id}/ship`, data)).data
}

/** 店铺订单同步：POST /orders/sync {shop_id} → 同步回执。 */
export async function syncShopOrders(shopId) {
  return (await api.post('/orders/sync', { shop_id: shopId })).data
}
