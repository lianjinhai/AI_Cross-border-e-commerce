/**
 * Phase 1.7 Workspace Context 接入层。
 *
 * 循环依赖处理方案：`api.js` 的默认导出带有 401 拦截器，而 401 时也需要清理
 * Context。若 `api.js` 反向 import 本模块就会形成环，因此这里**不**从 `api.js`
 * 导入，而是用 `axios.create` 自建一个同 baseURL 的轻量实例（同样的 Bearer
 * 注入逻辑），`api.js` 侧用动态 `import('./workspace.js')` 清理缓存，避免环。
 *
 * 响应式契约（UX-01）：Context 存于模块级 `ref`，所有 getter 读 `contextRef.value`，
 * 使调用方的 `computed` / `watchEffect` 能建立响应式依赖——这是修复「切换 Workspace
 * 后菜单/数据不刷新」的根因（旧实现把 Context 存在普通变量里，computed 读它时不产生
 * 依赖）。`getContext()` 返回缓存的引用本身（不返回深拷贝），保证读取即建立依赖。
 *
 * PII 红线：只缓存 Context 快照本身，不写入 token / 密码，也不新增
 * localStorage 键；失败日志仅输出错误状态与 trace_id。
 */
import axios from 'axios'
import { ref } from 'vue'

const client = axios.create({ baseURL: '/api', timeout: 60000 })

client.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('erp_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// 响应式 Context 缓存：必须用 ref 存储，调用方读 getContext() 才能建立依赖。
const contextRef = ref(null)
let loading = null
// 每次 clear 递增 epoch；在途请求发现 epoch 变化就丢弃过期结果，
// 避免登出/401 清理后被慢响应写回旧 Context。
let epoch = 0

// 变更订阅者集合（load / clear 时通知）。注意：集合在 clear 之后**不清空**，
// 保证订阅关系可跨多次 clear 复用；退订由 subscribeWorkspaceChange 返回的函数负责。
const listeners = new Set()

/**
 * 通知所有订阅者。回调参数 `{ context, epoch, reason }`，reason ∈ 'load' | 'clear'。
 * 单个监听器抛错不应影响其它监听器与主流程，故逐个 try/catch。
 */
function notifyListeners(reason) {
  const payload = { context: contextRef.value, epoch, reason }
  for (const listener of listeners) {
    try {
      listener(payload)
    } catch (err) {
      console.warn('[workspace] Context 变更监听器执行失败', {
        reason,
        message: err?.message ?? String(err),
      })
    }
  }
}

/** 加载并缓存当前 Workspace Context；失败返回 null（不抛出）。 */
export async function loadWorkspaceContext() {
  if (loading) return loading
  const myEpoch = epoch
  loading = (async () => {
    try {
      const { data } = await client.get('/me/workspace-context')
      if (myEpoch !== epoch) return null
      contextRef.value = data && typeof data === 'object' ? data : null
      notifyListeners('load')
      return contextRef.value
    } catch (err) {
      contextRef.value = null
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

/** 清空缓存（登出 / 401 时调用），并通知订阅者。 */
export function clearWorkspaceContext() {
  contextRef.value = null
  loading = null
  epoch += 1
  notifyListeners('clear')
}

/** 当前 epoch（每次 clear 递增）；供调用方判断快照新鲜度。 */
export function getWorkspaceEpoch() {
  return epoch
}

/**
 * 订阅 Workspace Context 变更（load 成功 / clear 各触发一次）。
 *
 * 返回 `unsubscribe` 函数；退订只移除对应监听器，不影响集合中其它订阅者。
 */
export function subscribeWorkspaceChange(listener) {
  if (typeof listener !== 'function') {
    throw new TypeError('subscribeWorkspaceChange 需要一个函数监听器')
  }
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 同步返回缓存快照（引用本身，非深拷贝），可能为 null；读取即建立响应式依赖。 */
export function getContext() {
  return contextRef.value
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
  if (contextRef.value) return contextRef.value
  if (!localStorage.getItem('erp_token')) return null
  return loadWorkspaceContext()
}

/** Context 可用时返回布尔值；Context 为 null 时返回 null 表示“未知”。 */
export function hasPermission(key) {
  const ctx = contextRef.value
  if (!ctx) return null
  const permissions = Array.isArray(ctx.permissions) ? ctx.permissions : []
  return permissions.includes(key)
}

/** 返回新角色枚举（大写）；无 Context 返回 null。 */
export function contextRole() {
  return contextRef.value?.role ?? null
}

export function workspaceId() {
  return contextRef.value?.workspace_id ?? null
}

/** 当前用户 id（Context 唯一来源；无 Context 为 null）。 */
export function contextUserId() {
  return contextRef.value?.user_id ?? null
}

export function workspaceName() {
  return contextRef.value?.workspace_name ?? ''
}

export function workspaceKind() {
  return contextRef.value?.workspace_kind ?? ''
}

export function contextSource() {
  return contextRef.value?.source ?? null
}

/** Context 是否来自真实 Membership（目标态）而非 legacy 兜底。 */
export function isMembershipContext() {
  return contextRef.value?.source === 'MEMBERSHIP'
}

/** 切换活动 Workspace；成功后重新加载 Context（失败不改动缓存）。 */
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
