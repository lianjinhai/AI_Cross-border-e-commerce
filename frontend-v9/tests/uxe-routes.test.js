import { describe, expect, it } from 'vitest'
import { UXE_B_ROUTES } from '../src/app/router/routes-uxe-b'

/**
 * UX-E 后半路由数组契约锁定（并行期特殊约定：不改 router/index.js，由总调度合并）。
 * meta 必须与 index.js appChildren 中对应 path 的冻结 meta 逐字一致（含 requiresOwner）。
 * 蓝图 R1：AI 域 domain 标签同步"AI 与自动化"，新增 4 条 P1/P2 条目。
 */
const EXPECTED = {
  'ai/workflows': { space: 'app', domain: 'AI 与自动化', title: '工作流' },
  'ai/knowledge': { space: 'app', domain: 'AI 与自动化', title: '知识库' },
  'ai/decisions': { space: 'app', domain: 'AI 与自动化', title: '决策依据' },
  'settings/ai': { space: 'app', domain: '设置与管理', title: 'AI 与集成设置', requiresOwner: true },
  'settings/team': { space: 'app', domain: '设置与管理', title: '用户与角色', requiresOwner: true },
  // ── 蓝图 R1 包 1 追加（P1/P2，占位组件） ──
  'ai/actions': { space: 'app', domain: 'AI 与自动化', title: 'AI 行动中心' },
  'settings/workspace': { space: 'app', domain: '设置与管理', title: '空间信息', requiresOwner: true },
  'settings/credentials': { space: 'app', domain: '设置与管理', title: '凭据管理', requiresOwner: true },
  'settings/plan': { space: 'app', domain: '设置与管理', title: '套餐管理', requiresOwner: true },
  // ── 蓝图 R1 P0 补齐：导航叶子可点（真实页未交付，先挂 StubPage 防 404，标记待接入） ──
  'ai/agent-runs': { space: 'app', domain: 'AI 与自动化', title: 'Agent 运行', requiresOwner: true },
}

describe('routes-uxe-b', () => {
  it('covers exactly the 10 UX-E pages with frozen meta', () => {
    expect(UXE_B_ROUTES).toHaveLength(10)
    for (const route of UXE_B_ROUTES) {
      expect(EXPECTED[route.path], `unknown path ${route.path}`).toBeDefined()
      expect(route.meta).toEqual(EXPECTED[route.path])
      expect(typeof route.component).toBe('function')
    }
    const paths = UXE_B_ROUTES.map((r) => r.path)
    expect(new Set(paths).size).toBe(10)
    expect(Object.keys(EXPECTED).every((p) => paths.includes(p))).toBe(true)
  })
})
