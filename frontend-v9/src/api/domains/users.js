import api from '../../shared/api/client'

/**
 * users 域（契约 §4.2）：对应 backend/app/routers/auth.py 的 /auth/users 组。
 * 角色提交值为后端唯一接受的 legacy 小写（admin/compliance_approver/operator/viewer），
 * 展示层用 features/settings/roleGuides.js 的 ROLE_ENUM 映射为大写枚举。
 */

/** 成员列表：GET /auth/users → {items[], total}（identity_snapshot，仅 OWNER/admin 可调）。 */
export async function fetchUsers() {
  return (await api.get('/auth/users', { params: { page_size: 100 } })).data
}

/** 新增成员：POST /auth/users {username, password, role, display_name} → 用户 DTO。 */
export async function createUser(data = {}) {
  return (await api.post('/auth/users', data)).data
}

/** 更新成员：PUT /auth/users/{id} {role?, display_name?, password?, status?}（password 留空不改）。 */
export async function updateUser(userId, data = {}) {
  return (await api.put(`/auth/users/${userId}`, data)).data
}

/** 删除成员：DELETE /auth/users/{id} → {ok}（后端禁止删除自己，400 兜底）。 */
export async function deleteUser(userId) {
  return (await api.delete(`/auth/users/${userId}`)).data
}
