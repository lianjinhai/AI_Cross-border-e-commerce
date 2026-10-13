/**
 * 代客访问（impersonation）纯函数（UX-E 前半）：
 * 进入租户的快照构造 / 退出还原。localStorage 语义与旧 PlatformAdmin.vue 平移一致：
 * `erp_impersonating` = { token, user, tenant }（进入前的平台身份快照）。
 *
 * 铁律：退出代客必须**还原平台 token/user**（否则平台管理员被钉死在租户身份），
 * 并 clearWorkspaceContext（Context 模块在 token 变更后重新拉取）。
 */

/** 快照存储键（与旧前端同名，兼容既有会话）。 */
export const IMPERSONATION_KEY = 'erp_impersonating'

/**
 * 构造进入租户前的平台身份快照。
 * @param {{token: string, user: object|null, tenantName: string}} src
 */
export function buildImpersonationSnapshot({ token = '', user = null, tenantName = '' } = {}) {
  return {
    token: typeof token === 'string' ? token : '',
    user: user && typeof user === 'object' ? user : null,
    tenant: String(tenantName || ''),
  }
}

/** 解析快照（存储损坏返回 null，不抛错）。 */
export function parseImpersonationSnapshot(raw) {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return buildImpersonationSnapshot(parsed)
  } catch {
    return null
  }
}

/** 当前是否有有效的代客快照（token 存在才算，空快照视为未代客）。 */
export function isImpersonating(storage = localStorage) {
  const snapshot = parseImpersonationSnapshot(storage.getItem(IMPERSONATION_KEY))
  return Boolean(snapshot?.token)
}

/**
 * 进入租户：保存快照并写入租户 token（在调 enterTenant 拿到 token 之后调用）。
 * 返回写入的快照（供测试断言）；storage 注入便于直测。
 */
export function saveImpersonationSnapshot({ token = '', user = null, tenantName = '' } = {},
                                            newToken = '', storage = localStorage) {
  const snapshot = buildImpersonationSnapshot({ token, user, tenantName })
  storage.setItem(IMPERSONATION_KEY, JSON.stringify(snapshot))
  if (newToken) storage.setItem('erp_token', newToken)
  return snapshot
}

/**
 * 退出代客：还原平台 token/user、清除快照。返回 true 表示成功还原；
 * 无快照/快照损坏时仅清标记并返回 false（调用方继续用当前 token，不伪造身份）。
 */
export function restoreImpersonation(storage = localStorage) {
  const snapshot = parseImpersonationSnapshot(storage.getItem(IMPERSONATION_KEY))
  storage.removeItem(IMPERSONATION_KEY)
  if (!snapshot?.token) return false
  storage.setItem('erp_token', snapshot.token)
  if (snapshot.user) storage.setItem('erp_user', JSON.stringify(snapshot.user))
  return true
}
