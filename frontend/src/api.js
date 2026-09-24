import axios from 'axios'
import { ElMessage } from './ui'
import router from './router'

const api = axios.create({ baseURL: '/api', timeout: 60000 })

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('erp_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem('erp_token')
      localStorage.removeItem('erp_user')
      // 代客标记必须一起清：否则代客期间 token 过期 → 重新登录平台账号后
      // `erp_impersonating` 仍在，守卫会把平台管理员当成租户身份，
      // `/platform-admin` 被弹回 `/dashboard`，管理员被锁在自己的控制台外。
      localStorage.removeItem('erp_impersonating')
      // 动态导入避免与 workspace.js 形成循环依赖（workspace.js 自建 axios 实例）。
      import('./workspace.js').then((m) => m.clearWorkspaceContext()).catch(() => {})
      if (router.currentRoute.value.path !== '/login') router.push('/login')
    }
    ElMessage.error(err.response?.data?.detail || '请求失败，请稍后重试')
    return Promise.reject(err)
  },
)

export const money = (v) => `$${Number(v || 0).toFixed(2)}`
export const pct = (v) => `${(Number(v || 0) * 100).toFixed(1)}%`

export default api
