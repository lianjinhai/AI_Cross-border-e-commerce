import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * B1 令牌基线契约测试（D62 签批）：
 *  1. 13 个 V9.1 语义色令牌存在且 hex 精确；
 *  2. `--color-primary` 必须解析到 `var(--v91-blue-600)`（旧名保留、值改指向）；
 *  3. 旧布局基线 220px / 56px 不得残留在 tokens.css、AppShellCore.vue、ShellSidebar.vue。
 *
 * 以文本读取断言（本仓无 CSS 自定义属性运行时解析器，且契约即源码）。
 */
// vitest 以项目根（frontend-v9）为 cwd；源码相对 cwd 解析，避免 import.meta.url 方案差异。
const ROOT = process.cwd()
const TOKENS = readFileSync(resolve(ROOT, 'src/styles/tokens.css'), 'utf8')
const APP_SHELL = readFileSync(resolve(ROOT, 'src/shells/AppShellCore.vue'), 'utf8')
const SIDEBAR = readFileSync(resolve(ROOT, 'src/shells/ShellSidebar.vue'), 'utf8')

// 13 个 V9.1 语义色令牌：名字 → 精确 hex（大小写敏感，如 #0C2654 非 #0c2654）。
const V91_TOKENS = {
  '--v91-navy-900': '#0C2654',
  '--v91-workspace-bg': '#F5F8FC',
  '--v91-surface': '#FFFFFF',
  '--v91-surface-muted': '#F9FBFE',
  '--v91-tint-blue': '#EAF2FB',
  '--v91-border': '#DCE5EF',
  '--v91-blue-600': '#236BBD',
  '--v91-blue-700': '#245A9C',
  '--v91-amber-surface': '#FFF4DE',
  '--v91-brand-gold': '#DDB85E',
  '--v91-text-strong': '#0C2654',
  '--v91-text-secondary': '#172D4B',
  '--v91-text-muted': '#3B5076',
}

describe('V9.1 设计令牌基线', () => {
  it('13 个 V9.1 语义色令牌存在且 hex 精确', () => {
    for (const [name, hex] of Object.entries(V91_TOKENS)) {
      // 宽松空白：`--v91-navy-900: #0C2654;` 或 `--v91-navy-900:  #0C2654`
      const re = new RegExp(`${name}\\s*:\\s*${hex}\\s*;`)
      expect(re.test(TOKENS), `${name} 应为 ${hex}`).toBe(true)
    }
  })

  it('布局令牌存在且精确（208/64/58/28）', () => {
    expect(/--layout-sidebar-width\s*:\s*208px\s*;/.test(TOKENS)).toBe(true)
    expect(/--layout-sidebar-collapsed\s*:\s*64px\s*;/.test(TOKENS)).toBe(true)
    expect(/--layout-topbar-height\s*:\s*58px\s*;/.test(TOKENS)).toBe(true)
    expect(/--layout-content-gutter\s*:\s*28px\s*;/.test(TOKENS)).toBe(true)
  })

  it('--color-primary 解析到 var(--v91-blue-600)（旧名保留、值改指向）', () => {
    expect(/--color-primary\s*:\s*var\(--v91-blue-600\)\s*;/.test(TOKENS)).toBe(true)
  })

  it('--color-bg / --color-sidebar 改指向 V9.1 令牌', () => {
    expect(/--color-bg\s*:\s*var\(--v91-workspace-bg\)\s*;/.test(TOKENS)).toBe(true)
    expect(/--color-sidebar\s*:\s*var\(--v91-navy-900\)\s*;/.test(TOKENS)).toBe(true)
  })

  it('EP 映射保持 :root:root 特异性（不被降级）', () => {
    expect(/:root:root\s*\{/.test(TOKENS)).toBe(true)
    expect(/--el-color-primary\s*:\s*var\(--color-primary\)/.test(TOKENS)).toBe(true)
  })

  it('深色侧栏文字/激活令牌精确（B1 修正：#C7D7EB / #245A9C / 白字）', () => {
    expect(/--v91-sidebar-text\s*:\s*#C7D7EB\s*;/.test(TOKENS)).toBe(true)
    expect(/--v91-sidebar-active-bg\s*:\s*#245A9C\s*;/.test(TOKENS)).toBe(true)
    expect(/--v91-sidebar-active-text\s*:\s*#FFFFFF\s*;/.test(TOKENS)).toBe(true)
    // 旧离谱值不得残留
    expect(TOKENS.includes('#16315C')).toBe(false)
    expect(TOKENS.includes('#C7D6EA')).toBe(false)
  })

  it('EP 主色派生梯度在 :root:root 内显式钉死（6 个 --el-color-primary-*）', () => {
    const rootRootIdx = TOKENS.indexOf(':root:root {')
    expect(rootRootIdx).toBeGreaterThan(-1)
    const pins = {
      '--el-color-primary-light-3': '#6597D1',
      '--el-color-primary-light-5': '#91B5DE',
      '--el-color-primary-light-7': '#BDD3EB',
      '--el-color-primary-light-8': '#D3E1F2',
      '--el-color-primary-light-9': '#E9F0F8',
      '--el-color-primary-dark-2': '#1C5697',
    }
    for (const [name, hex] of Object.entries(pins)) {
      const re = new RegExp(`${name}\\s*:\\s*${hex}\\s*;`)
      expect(re.test(TOKENS), `${name} 应为 ${hex}`).toBe(true)
      // 必须落在 :root:root 块内（索引在 :root:root { 之后），不被降级到普通 :root
      expect(TOKENS.search(re)).toBeGreaterThan(rootRootIdx)
    }
  })

  it('旧布局基线 220px / 56px 不在 tokens.css', () => {
    expect(TOKENS.includes('220px')).toBe(false)
    expect(TOKENS.includes('56px')).toBe(false)
  })

  it('旧布局基线 220px / 56px 不在 AppShellCore.vue', () => {
    expect(APP_SHELL.includes('220px')).toBe(false)
    expect(APP_SHELL.includes('56px')).toBe(false)
  })

  it('旧布局基线 220px / 56px 不在 ShellSidebar.vue', () => {
    expect(SIDEBAR.includes('220px')).toBe(false)
    expect(SIDEBAR.includes('56px')).toBe(false)
  })
})
