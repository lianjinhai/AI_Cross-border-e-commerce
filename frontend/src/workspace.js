/**
 * Phase 1.7 Workspace Context 接入层。
 *
 * 循环依赖处理方案：`api.js` 的默认导出带有 401 拦截器，而 401 时也需要清理
 * Context。若 `api.js` 反向 import 本模块就会形成环，因此这里**不**从 `api.js`
 * 导入，而是用 `axios.create` 自建一个同 baseURL 的轻量实例（同样的 Bearer
 * 注入逻辑），`api.js` 侧用动态 `import('./workspace.js')` 清理缓存，避免环。
 *
 * PII 红线：只缓存 Context 快照本身，不写入 token / 密码，也不新增
 * localStorage 键；失败日志仅输出错误状态与 trace_id。
 */
import axios from 'axios'

const client = axios.create({ baseURL: '/api', timeout: 60000 })

client.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('erp_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

let context = null
let loading = null
// 每次 clear 递增 epoch；在途请求发现 epoch 变化就丢弃过期结果，
// 避免登出/401 清理后被慢响应写回旧 Context。
let epoch = 0

/** 加载并缓存当前 Workspace Context；失败返回 null（不抛出）。 */
export async function loadWorkspaceContext() {
  if (loading) return loading
  const myEpoch = epoch
  loading = (async () => {
    try {
      const { data } = await client.get('/me/workspace-context')
      if (myEpoch !== epoch) return null
      context = data && typeof data === 'object' ? data : null
      return context
    } catch (err) {
      context = null
      console.warn('[workspace] 加载 Workspace Context 失败', {
        status: err?.response?.status ?? null,
        traceId: err?.response?.data?.trace_id ?? null,
      })
      return null
    } finally {
      loading = null
    }
  })()
  return loading
}

/** 清空缓存（登出 / 401 时调用）。 */
export function clearWorkspaceContext() {
  context = null
  loading = null
  epoch += 1
}

/** 同步返回缓存快照，可能为 null。 */
export function getContext() {
  return context
}

/**
 * 确保 Context 可用：已缓存则直接返回，否则在「有 token」时拉取一次。
 *
 * 为什么单独抽成函数而不是写在路由守卫里：守卫是路由库内部机制，
 * 测试只能靠真实导航触发（会连带加载 .vue 组件），既慢又脆。
 * 抽出来后可以独立断言「F5 刷新会重新拉取」这一行为契约。
 *
 * 无 token 或拉取失败都返回 null，由调用方决定兜底策略（不抛异常）。
 */
export async function ensureWorkspaceContext() {
  if (context) return context
  if (!localStorage.getItem('erp_token')) return null
  return loadWorkspaceContext()
}

/** Context 可用时返回布尔值；Context 为 null 时返回 null 表示“未知”。 */
export function hasPermission(key) {
  if (!context) return null
  const permissions = Array.isArray(context.permissions) ? context.permissions : []
  return permissions.includes(key)
}

/** 返回新角色枚举（大写）；无 Context 返回 null。 */
export function contextRole() {
  return context?.role ?? null
}

export function workspaceId() {
  return context?.workspace_id ?? null
}

/** 当前用户 id（Context 唯一来源；无 Context 为 null）。 */
export function contextUserId() {
  return context?.user_id ?? null
}

export function workspaceName() {
  return context?.workspace_name ?? ''
}

export function workspaceKind() {
  return context?.workspace_kind ?? ''
}

export function contextSource() {
  return context?.source ?? null
}

/** Context 是否来自真实 Membership（目标态）而非 legacy 兜底。 */
export function isMembershipContext() {
  return context?.source === 'MEMBERSHIP'
}

/**
 * Phase 1.8：把 Context 归一化成「路由分流用的身份快照」。
 *
 * 为什么需要这一层：`routeRedirect` / `defaultLanding` 需要的是
 * 「这个用户该去哪个首页、能进哪些页」，而 Context 与 legacy `erp_user`
 * 的字段名不同（`role` 大写枚举 vs 小写角色、`source` vs 无）。
 * 把差异收敛在这一个函数里，路由策略本身保持纯函数、可单测。
 *
 * 返回 null 表示「没有可用身份」（未登录或 Context 与 legacy 都拿不到）。
 *
 * `impersonating` 语义：superadmin 代客进入租户后必须当普通租户身份看，
 * 不能再去平台控制台。优先用 Context 的 `is_impersonating`（后端已透传），
 * 无 Context 时回退 localStorage 标记（代客会话是前端自管的）。
 */
export function identitySnapshot() {
  const impersonating = Boolean(context?.is_impersonating)
    || Boolean(localStorage.getItem('erp_impersonating'))
  if (context) {
    return {
      source: context.source,
      role: context.role,
      workspaceId: context.workspace_id ?? null,
      impersonating,
      fromContext: true,
    }
  }
  return null
}

/** 切换活动 Workspace；成功后重新加载 Context。 */
export async function switchWorkspace(id) {
  try {
    await client.post(`/me/workspaces/${id}/switch`)
  } catch (err) {
    console.warn('[workspace] 切换 Workspace 失败', {
      status: err?.response?.status ?? null,
      traceId: err?.response?.data?.trace_id ?? null,
    })
    return false
  }
  await loadWorkspaceContext()
  return true
}

/** 返回当前用户可访问的 Workspace 列表；失败返回空数组。 */
export async function loadWorkspaces() {
  try {
    const { data } = await client.get('/me/workspaces')
    return Array.isArray(data?.items) ? data.items : []
  } catch (err) {
    console.warn('[workspace] 加载 Workspace 列表失败', {
      status: err?.response?.status ?? null,
      traceId: err?.response?.data?.trace_id ?? null,
    })
    return []
  }
}
