import axios from 'axios'
import { ElMessage } from '../ui'
import router from '../../app/router'
import { normalizeError } from './errors'

/**
 * 统一请求封装（契约 §4.3，逐字平移 frontend/src/api.js，仅按 §3.2 改登录路径）。
 *
 * - Bearer 注入：从 localStorage `erp_token` 读取；
 * - 401 → 清 token/erp_user/erp_impersonating/Context 并跳 /console/login
 *   （代客标记必须一起清，否则重新登录后守卫会把平台管理员当租户身份）；
 * - `detail` envelope 规整（对象取 message）只弹一次全局 toast（短窗去重）；
 * - 403 → **不弹 toast**，返回规整错误由页面呈 NoPermissionState 语义；
 * - 动态 import workspace 清缓存，避免与 workspace.js 循环依赖（其自建 axios 实例）。
 */
const api = axios.create({ baseURL: '/api', timeout: 60000 })

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('erp_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// 同一 message 的 toast 短窗去重：并发批量失败只提示一次，避免刷屏。
let lastToast = { message: '', at: 0 }
const TOAST_DEDUPE_MS = 1500

function toastDetail(detail, fallback) {
  const message = (detail && typeof detail === 'object' ? detail.message : detail) || fallback
  const now = Date.now()
  if (message === lastToast.message && now - lastToast.at < TOAST_DEDUPE_MS) return
  lastToast = { message, at: now }
  ElMessage.error(message)
}

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem('erp_token')
      localStorage.removeItem('erp_user')
      // 代客标记必须一起清：否则代客期间 token 过期 → 重新登录平台账号后
      // `erp_impersonating` 仍在，守卫会把平台管理员当成租户身份。
      localStorage.removeItem('erp_impersonating')
      // 动态导入避免与 workspace.js 形成循环依赖（workspace.js 自建 axios 实例）。
      import('../workspace.js').then((m) => m.clearWorkspaceContext()).catch(() => {})
      if (router.currentRoute.value.path !== '/console/login') router.push('/console/login')
      return Promise.reject(err)
    }
    // 403 不弹 toast：返回规整错误由页面呈现 NoPermissionState 语义（契约 §4.3）。
    if (status === 403) {
      return Promise.reject(err)
    }
    toastDetail(err.response?.data?.detail, '请求失败，请稍后重试')
    return Promise.reject(err)
  },
)

/** 页面级错误规整入口（errors.normalizeError），供 ErrorState 消费。 */
export const toPageError = normalizeError

export const money = (v) => `$${Number(v || 0).toFixed(2)}`
export const pct = (v) => `${(Number(v || 0) * 100).toFixed(1)}%`

export default api
