import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import router from '../src/router'

/**
 * 路由回归守卫：后端能力必须在前端有可达入口。
 *
 * 为什么单独测这一层：新增页面若只写了 .vue 却没挂进 router.js，
 * 后端接口再完整用户也用不到（本轮就修过这个缺口）。这里把
 * 「已接通的 AI 原生能力页面」固化下来，删除或改名会直接失败。
 */
const REQUIRED_PATHS = [
  '/dashboard', '/discovery', '/products', '/listings', '/compliance',
  '/shops', '/suppliers', '/pricing', '/ads', '/orders', '/refunds',
  '/settlements', '/support', '/workflows', '/knowledge', '/bi', '/finance',
  '/alerts', '/ai-decisions', '/users', '/settings', '/platform-admin',
  '/factory-portal',
]

const allPaths = () => {
  const layout = router.options.routes.find((r) => r.path === '/')
  return (layout?.children || []).map((c) => `/${c.path}`)
}

describe('router coverage', () => {
  it('registers every business page as a child of the layout route', () => {
    const paths = allPaths()
    const missing = REQUIRED_PATHS.filter((p) => !paths.includes(p))
    expect(missing, `未注册的路由: ${missing.join(', ')}`).toEqual([])
  })

  it('lazy-loads every page so route-level code splitting keeps working', () => {
    const layout = router.options.routes.find((r) => r.path === '/')
    const eager = (layout?.children || []).filter((c) => typeof c.component !== 'function')
    expect(eager.map((c) => c.path), '以下路由未使用懒加载').toEqual([])
  })

  it('keeps the AI-native capability pages wired to real components', async () => {
    const expected = {
      '/alerts': 'Alerts.vue',
      '/ai-decisions': 'AiDecisions.vue',
    }
    const layout = router.options.routes.find((r) => r.path === '/')
    for (const [path, file] of Object.entries(expected)) {
      const route = (layout?.children || []).find((c) => `/${c.path}` === path)
      expect(route, `${path} 未注册`).toBeTruthy()
      // Vite 会把 './views/X.vue' 重写成内部动态 import，故按文件名匹配
      expect(String(route.component), `${path} 未指向 ${file}`).toContain(file)
      // 落盘校验：文件必须真实存在且是 SFC（防死链），不真实 import 以免拖入
      // 整个 Element Plus 造成超时。
      // 注：vitest 会把 import.meta.url 重写成 http://localhost，故用 cwd 定位。
      const filePath = resolve(process.cwd(), 'src/views', file)
      expect(existsSync(filePath), `${file} 文件不存在`).toBe(true)
      const source = readFileSync(filePath, 'utf8')
      expect(source, `${file} 不是合法 SFC`).toContain('<template>')
    }
  })
})
