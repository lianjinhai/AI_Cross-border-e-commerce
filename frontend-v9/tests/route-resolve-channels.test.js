import { describe, expect, it } from 'vitest'
import router from '../src/app/router'
import { UXD_ROUTES } from '../src/app/router/routes-uxd'

/**
 * E09（R3-1A）路由唯一事实源：/app/channels 必须由 index.js 唯一挂载，
 * 展开后的完整路由表中每个 channels 族 path 只出现一次；并用 router.resolve
 * 实际解析断言命中通道是 channel/Channels.vue（而非 StubPage 占位页）。
 *
 * 命中判定方式：resolve 后取末级匹配记录的组件 loader（动态 import 函数），
 * 断言其源码文本包含 'channel/Channels.vue' 且不含 'StubPage.vue'。
 * 不 await 执行 loader——element-plus 在 vitest 中被 externalize，原生 ESM
 * import 会因 .css 扩展名报错；loader 源码断言与 dev-server 运行时验证
 * （docs 验收截图）共同构成 E09 证据链。
 */

const appChildren = () => router.options.routes.find((r) => r.path === '/app').children

const leafLoader = (path) => {
  const resolved = router.resolve(path)
  const leaf = resolved.matched[resolved.matched.length - 1]
  expect(typeof leaf.components.default).toBe('function')
  return String(leaf.components.default)
}

describe('E09 重复路由消除 — /app/channels 唯一挂载点', () => {
  it('index.js appChildren has exactly one `channels` entry, pointing at real Channels.vue', () => {
    const entries = appChildren().filter((c) => c.path === 'channels')
    expect(entries).toHaveLength(1)
    expect(entries[0].meta.title).toBe('渠道推荐')
    expect(typeof entries[0].component).toBe('function')
    expect(String(entries[0].component)).toContain('channel/Channels.vue')
    expect(String(entries[0].component)).not.toContain('StubPage.vue')
  })

  it('routes-uxd.js no longer declares the duplicate `channels` / `channels/shops/:id` paths', () => {
    const uxdPaths = UXD_ROUTES.map((r) => r.path)
    expect(uxdPaths).not.toContain('channels')
    expect(uxdPaths).not.toContain('channels/shops/:id')
  })

  it('the fully expanded route table has no duplicate channels-family paths', () => {
    const flat = router.options.routes.flatMap((r) => [r, ...(r.children || [])])
    const counts = {}
    for (const c of flat.filter((r) => ['channels', 'channels/shops', 'channels/shops/:id'].includes(r.path))) {
      counts[c.path] = (counts[c.path] || 0) + 1
    }
    expect(counts.channels).toBe(1)
    expect(counts['channels/shops']).toBe(1)
    expect(counts['channels/shops/:id']).toBe(1)
  })

  it('router.resolve("/app/channels") actually hits Channels.vue, not StubPage', () => {
    const source = leafLoader('/app/channels')
    expect(source).toContain('channel/Channels.vue')
    expect(source).not.toContain('StubPage.vue')
    const resolved = router.resolve('/app/channels')
    expect(resolved.meta.title).toBe('渠道推荐')
    expect(resolved.meta.space).toBe('app')
  })

  it('router.resolve("/app/channels/shops/42") hits ShopDetail.vue (hidden param route)', () => {
    const source = leafLoader('/app/channels/shops/42')
    expect(source).toContain('channel/ShopDetail.vue')
    expect(source).not.toContain('StubPage.vue')
    const resolved = router.resolve('/app/channels/shops/42')
    expect(resolved.params.id).toBe('42')
    expect(resolved.meta.hidden).toBe(true)
  })
})
