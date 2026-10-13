/**
 * 工厂供给目录纯函数（UX-E，旧 FactoryPortal.vue 平移）：
 * 表单初值 / 行→表单 / 表单→PUT/POST 载荷。组件只消费，vitest 直测。
 */

/** 尽调状态徽标（旧页 statusText 查表平移为 tag 形态）。 */
export const VERIFICATION_TAGS = {
  candidate: { text: '候选', type: 'info' },
  contacting: { text: '接洽中', type: 'warning' },
  verified: { text: '已尽调', type: 'success' },
  rejected: { text: '未通过', type: 'danger' },
  suspended: { text: '已暂停', type: 'warning' },
}

/** 表单初值（capabilityText/imageText 为文本态，提交时拆分）。 */
export function emptyCatalogForm() {
  return {
    id: null, factory_sku: '', title: '', category: '', capabilityText: '',
    unit_price: 1, currency: 'CNY', moq: 1, lead_days: 7,
    monthly_capacity: 0, available_qty: 0, imageText: '', status: 'active', attrs: {},
  }
}

/** 目录行 → 表单（capabilities/images 数组文本化）。 */
export function catalogRowToForm(row = {}) {
  return {
    ...emptyCatalogForm(),
    ...row,
    capabilityText: (row.capabilities || []).join(','),
    imageText: (row.images || []).join(','),
  }
}

/** 中英文逗号/空白拆分（能力标签与图片链接共用）。 */
function splitList(text) {
  return String(text || '').split(/[,，]/).map((x) => x.trim()).filter(Boolean)
}

/** 表单 → POST/PUT 载荷（键集与后端 portal 端点一致，不发送多余键）。 */
export function catalogFormToPayload(form = {}) {
  return {
    factory_sku: String(form.factory_sku || '').trim(),
    title: String(form.title || '').trim(),
    category: String(form.category || '').trim(),
    capabilities: splitList(form.capabilityText),
    attrs: form.attrs || {},
    images: splitList(form.imageText),
    unit_price: form.unit_price,
    currency: String(form.currency || 'CNY').trim(),
    moq: form.moq,
    lead_days: form.lead_days,
    monthly_capacity: form.monthly_capacity,
    available_qty: form.available_qty,
    status: form.status || 'active',
  }
}
