import api from '../../shared/api/client'

/**
 * auth 域（契约 §4.2）：对应 backend/app/routers/auth.py（前缀 /auth）。
 * 1:1 薄封装 + DTO 转换；签名模式同 FRONTEND_V9_CONTRACTS.md §4.2。
 */

/** 登录：POST /auth/login → {token, user}。 */
export async function login({ username, password } = {}) {
  return (await api.post('/auth/login', { username, password })).data
}

/** 成员列表：GET /auth/users → {items[]}（成员 DTO）。 */
export async function listUsers(params = {}) {
  return (await api.get('/auth/users', { params })).data
}

/** 创建成员：POST /auth/users → 成员 DTO。 */
export async function createUser(data = {}) {
  return (await api.post('/auth/users', data)).data
}

/** 更新成员：PUT /auth/users/{id} → 成员 DTO。 */
export async function updateUser(id, data = {}) {
  return (await api.put(`/auth/users/${id}`, data)).data
}
