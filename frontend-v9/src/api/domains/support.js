import api from '../../shared/api/client'

/**
 * support 域（契约 §4.2）：对应 backend/app/routers/support.py（前缀 /support）。
 * 会话状态 open/closed；AI 自动回复为真实落库端点（后端无「仅草稿」端点），
 * 「AI 建议可编辑后发送」由页面取回执文本填入输入框人工发送实现。
 */

/** 会话列表：GET /support/conversations → {items[], total}（含 last_message 摘要）。 */
export async function fetchConversations({ status, page } = {}) {
  return (await api.get('/support/conversations', {
    params: { status, page_num: page, page_size: 50 },
  })).data
}

/** 会话详情：GET /support/conversations/{id} → 会话 DTO（含 messages[]）。 */
export async function fetchConversation(id) {
  return (await api.get(`/support/conversations/${id}`)).data
}

/** 新建会话：POST /support/conversations {platform, buyer_name, content} → DTO。 */
export async function createConversation(data = {}) {
  return (await api.post('/support/conversations', data)).data
}

/** 人工回复：POST /support/conversations/{id}/reply {content} → 消息 DTO。 */
export async function reply(id, content) {
  return (await api.post(`/support/conversations/${id}/reply`, { content })).data
}

/**
 * AI 自动回复：POST /support/conversations/{id}/auto_reply →
 * {reply, intent, ...}（AI 消息真实落库；回执文本供「引用编辑后发送」）。
 */
export async function requestAutoReply(id) {
  return (await api.post(`/support/conversations/${id}/auto_reply`)).data
}

/** 关闭会话：POST /support/conversations/{id}/close → 会话 DTO（关闭后不可再回复）。 */
export async function closeConversation(id) {
  return (await api.post(`/support/conversations/${id}/close`)).data
}
