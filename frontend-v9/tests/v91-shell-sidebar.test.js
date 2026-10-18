import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { WORKSPACE_DOMAINS } from '../src/shared/navigation/workspace-navigation'

/**
 * B1 侧栏五入口收敛 + UI-07 令牌合规（源码级断言，本仓无 @vue/test-utils）。
 *  - 导航结构：WORKSPACE_DOMAINS 冻结为 5 个一级入口（mybiz/goods/orders/revenue/tools）；
 *  - ShellSidebar 以 `v-for` 遍历全部域并统一以 `el-sub-menu` 渲染（无高频域平铺分支）；
 *  - ShellSidebar 不得残留硬编码色值 prop / 字面 hex（颜色改由 --v91-* 令牌驱动）。
 */
// vitest 以项目根（frontend-v9）为 cwd；源码相对 cwd 解析，避免 import.meta.url 方案差异。
const SIDEBAR = readFileSync(resolve(process.cwd(), 'src/shells/ShellSidebar.vue'), 'utf8')

const FROZEN_KEYS = ['mybiz', 'goods', 'orders', 'revenue', 'tools']

describe('B1 侧栏五入口收敛', () => {
  it('导航结构冻结为 5 个一级入口（路径不变、零隐藏页面）', () => {
    expect(WORKSPACE_DOMAINS.map((d) => d.key)).toEqual(FROZEN_KEYS)
    // 五入口下叶子总数需覆盖既有功能（R3-2A 铁律：不隐藏任何既有页面）
    const leaves = WORKSPACE_DOMAINS.reduce((n, d) => n + (d.children?.length || 0), 0)
    expect(leaves).toBeGreaterThanOrEqual(30)
  })

  it('ShellSidebar 遍历全部域并以 el-sub-menu 统一渲染（默认收起、含当前路由的域自动展开）', () => {
    expect(SIDEBAR).toContain('v-for="domain in navigation"')
    expect(SIDEBAR).toContain('<el-sub-menu')
    // 旧「高频域平铺 el-menu-item 叶子 + 分组标题」分支已移除
    expect(SIDEBAR).not.toContain('v-if="domain.collapsible"')
    expect(SIDEBAR).not.toContain('menu-group')
  })

  it('ShellSidebar 保留 default-active / 路由行为（路径零改动）', () => {
    expect(SIDEBAR).toContain(':default-active="activePath"')
    expect(SIDEBAR).toContain('router')
    expect(SIDEBAR).toContain('openedEntries')
  })
})

describe('B1 UI-07 侧栏令牌合规（无硬编码色值）', () => {
  it('无硬编码色值 prop（background-color / text-color / active-text-color 字面量）', () => {
    expect(SIDEBAR).not.toMatch(/background-color\s*=\s*"/)
    expect(SIDEBAR).not.toMatch(/text-color\s*=\s*"/)
    expect(SIDEBAR).not.toMatch(/active-text-color\s*=\s*"/)
    // 旧值不应再出现
    expect(SIDEBAR).not.toContain('#1f2d3d')
    expect(SIDEBAR).not.toContain('#bfcbd9')
    expect(SIDEBAR).not.toContain('#409EFF')
  })

  it('无字面 hex 残留（颜色全部走 --v91-* 令牌 + EP 菜单变量）', () => {
    expect(SIDEBAR).not.toMatch(/#[0-9A-Fa-f]{3,6}/)
  })

  it('颜色由 --v91-* 语义令牌驱动', () => {
    expect(SIDEBAR).toContain('var(--v91-navy-900)')
    expect(SIDEBAR).toContain('var(--v91-sidebar-text)')
    expect(SIDEBAR).toContain('var(--v91-blue-600)')
  })
})
