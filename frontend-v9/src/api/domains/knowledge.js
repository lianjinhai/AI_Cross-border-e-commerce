import api from '../../shared/api/client'

/**
 * knowledge 域（契约 §4.2）：对应 backend/app/routers/knowledge.py（前缀 /knowledge）。
 * 文档 CRUD + RAG 检索 + 客服知识候选（M4：只沉淀人工验证过的答案，红线）。
 */

/** 文档列表：GET /knowledge/docs → {items[], total}（keyword 模糊匹配 title/content）。 */
export async function fetchDocs({ keyword = '', page = 1, pageSize = 15 } = {}) {
  return (await api.get('/knowledge/docs', {
    params: { keyword, page_num: page, page_size: pageSize },
  })).data
}

/** 新建文档：POST /knowledge/docs {title, content, source, tags, enabled} → 文档 DTO。 */
export async function createDoc(data = {}) {
  return (await api.post('/knowledge/docs', data)).data
}

/** 更新文档：PUT /knowledge/docs/{id}（未传 tags/enabled 时后端保留原值）。 */
export async function updateDoc(docId, data = {}) {
  return (await api.put(`/knowledge/docs/${docId}`, data)).data
}

/** 删除文档：DELETE /knowledge/docs/{id} → {ok}（后端自动解除候选引用）。 */
export async function deleteDoc(docId) {
  return (await api.delete(`/knowledge/docs/${docId}`)).data
}

/** RAG 语义检索：GET /knowledge/search?q=&top_k= → {items[]}（含相关度 score）。 */
export async function searchDocs(q, topK = 4) {
  return (await api.get('/knowledge/search', { params: { q, top_k: topK } })).data
}

/** 知识候选列表：GET /knowledge/candidates?status=&limit= → {items[], total}。 */
export async function fetchCandidates({ status = '', limit = 200 } = {}) {
  return (await api.get('/knowledge/candidates', { params: { status, limit } })).data
}

/** 人工补写答案：POST /knowledge/candidates/{id}/answer {answer} → 候选 DTO（answer_source 变 operator）。 */
export async function answerCandidate(candidateId, answer) {
  return (await api.post(`/knowledge/candidates/${candidateId}/answer`, { answer })).data
}

/** 采纳为知识文档：POST /knowledge/candidates/{id}/approve {answer} → {doc_id, ...}。 */
export async function approveCandidate(candidateId, answer = '') {
  return (await api.post(`/knowledge/candidates/${candidateId}/approve`, { answer })).data
}

/** 拒绝候选：POST /knowledge/candidates/{id}/reject → 候选 DTO。 */
export async function rejectCandidate(candidateId) {
  return (await api.post(`/knowledge/candidates/${candidateId}/reject`)).data
}

/** 撤销自动入库：POST /knowledge/candidates/{id}/revoke → {doc_removed, ...}（删除已生成文档）。 */
export async function revokeCandidate(candidateId) {
  return (await api.post(`/knowledge/candidates/${candidateId}/revoke`)).data
}

/** 学习配置：GET /knowledge/learning/settings → {auto_learn_enabled, auto_learn_threshold, hint}。 */
export async function fetchLearningSettings() {
  return (await api.get('/knowledge/learning/settings')).data
}

/** 更新学习配置：PUT /knowledge/learning/settings {auto_learn_enabled, auto_learn_threshold} → 配置。 */
export async function updateLearningSettings(data = {}) {
  return (await api.put('/knowledge/learning/settings', data)).data
}
