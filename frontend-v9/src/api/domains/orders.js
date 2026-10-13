import api from '../../shared/api/client'

/**
 * orders 域（契约 §4.2）：对应 backend/app/routers/orders.py（前缀 /orders）。
 * 非法状态流转由后端拒绝（409），前端 StateBar 预校验；物流轨迹待接入不渲染。
 * 真实筛参为 platform/keyword（后端 GET /orders 无 shop_id 筛选）。
 */

/** 订单列表：GET /orders → {items[], total}。 */
export async function fetchOrders({ page, status, shopId, platform, keyword } = {}) {
  // 契约签名保留 shopId；后端该端点不支持店铺筛选，仅透传真实支持的参数。
  void shopId
  return (await api.get('/orders', {
    params: { page_num: page, status, platform, keyword },
  })).data
}

/**
 * CSV 导入：POST /orders/import {csv_text, shop_id?} →
 * {imported, skipped, errors: ['第N行(...): 原因', ...]}。
 * errors 为后端拼好的字符串数组，逐行报告由 features/fulfillment/orderStateMachine.js
 * 的 parseImportErrors 纯函数解析为 {row, reason}。
 */
export async function importCsv({ csvText = '', shopId = null } = {}) {
  return (await api.post('/orders/import', { csv_text: csvText, shop_id: shopId })).data
}

/** 导出订单 CSV：GET /orders/export（blob 下载，utf-8-sig）。 */
export function exportOrders() {
  return api.get('/orders/export', { responseType: 'blob' })
}

/** 更新订单状态：PUT /orders/{id}/status {status}（非法流转后端 409 拒绝）。 */
export async function updateStatus(id, status) {
  return (await api.put(`/orders/${id}/status`, { status })).data
}

/** 发货：POST /orders/{id}/ship → 履约回执（生成物流单号；轨迹跟踪待接入）。 */
export async function ship(id, data = {}) {
  return (await api.post(`/orders/${id}/ship`, data)).data
}

/**
 * 演示平台订单同步：POST /orders/sync {platform, count} → 同步回执。
 * 真实店铺拉单走 shops.syncOrders(id)（POST /shops/{id}/sync_orders）。
 */
export async function syncShopOrders({ platform = 'shopee', count = 5 } = {}) {
  return (await api.post('/orders/sync', { platform, count })).data
}
