import { describe, expect, it } from 'vitest'
import { UXE_B_ROUTES } from '../src/app/router/routes-uxe-b'

/**
 * UX-E 后半路由数组契约锁定（并行期特殊约定：不改 router/index.js，由总调度合并）。
 * meta 必须与 index.js appChildren 中对应 path 的冻结 meta 逐字一致（含 requiresOwner）。
 */
const EXPECTED = {
  'ai/workflows': { space: 'app', domain: 'AI 运营', title: 'AI 工作流' },
  'ai/knowledge': { space: 'app', domain: 'AI 运营', title: '知识库' },
  'ai/decisions': { space: 'app', domain: 'AI 运营', title: 'AI 决策依据' },
  'settings/ai': { space: 'app', domain: '设置与管理', title: 'AI 与集成设置', requiresOwner: true },
  'settings/team': { space: 'app', domain: '设置与管理', title: '用户与角色', requiresOwner: true },
}

describe('routes-uxe-b', () => {
  it('covers exactly the 5 UX-E pages with frozen meta', () => {
    expect(UXE_B_ROUTES).toHaveLength(5)
    for (const route of UXE_B_ROUTES) {
      expect(EXPECTED[route.path], `unknown path ${route.path}`).toBeDefined()
      expect(route.meta).toEqual(EXPECTED[route.path])
      expect(typeof route.component).toBe('function')
    }
    const paths = UXE_B_ROUTES.map((r) => r.path)
    expect(new Set(paths).size).toBe(5)
    expect(Object.keys(EXPECTED).every((p) => paths.includes(p))).toBe(true)
  })
})
