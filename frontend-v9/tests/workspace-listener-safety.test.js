import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * UX-01 / UX-02 验收补测（QA 独立验证）。
 *
 * 覆盖既有 tests/workspace.test.js **未覆盖**的订阅边界：
 *  1) 单个监听器抛异常不应中断其它监听器，也不应影响主流程（load/clear 的返回值）。
 *  2) clear 之后再次 load，订阅者仍能收到 'load' 通知（订阅关系跨 clear 复用）。
 *  3) 退订一个监听器不影响集合中其它订阅者。
 *  4) 传入非函数监听器抛 TypeError（fail-fast 契约）。
 *
 * 只断言 `frontend/src/workspace.js` 对外可观测的行为，不修改 src。
 */

const client = {
  get: vi.fn(),
  post: vi.fn(),
  interceptors: { request: { use: vi.fn() } },
}

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => client),
    get: vi.fn(),
  },
}))

const {
  clearWorkspaceContext,
  getContext,
  loadWorkspaceContext,
  subscribeWorkspaceChange,
} = await import('../src/shared/workspace')

const CONTEXT = {
  user_id: 1,
  workspace_id: 10,
  workspace_name: '泉州工厂',
  workspace_kind: 'TENANT',
  role: 'OPERATOR',
  permissions: ['order:read', 'order:write'],
  source: 'MEMBERSHIP',
}

const contextResponse = (context = CONTEXT) => ({ data: context })

describe('subscribeWorkspaceChange listener safety', () => {
  beforeEach(() => {
    clearWorkspaceContext()
    localStorage.clear()
    client.get.mockReset()
    client.post.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('a throwing listener does not block other listeners nor the load flow', async () => {
    const healthy = []
    const boom = () => { throw new Error('listener exploded') }
    const unsubscribeBoom = subscribeWorkspaceChange(boom)
    const unsubscribeHealthy = subscribeWorkspaceChange((p) => healthy.push(p.reason))

    client.get.mockResolvedValueOnce(contextResponse())

    // 主流程返回值不受坏监听器影响。
    const loaded = await loadWorkspaceContext()
    expect(loaded).toEqual(CONTEXT)
    expect(getContext()).toEqual(CONTEXT)

    // 好监听器仍收到 'load'。
    expect(healthy).toEqual(['load'])

    // clear 同理：坏监听器抛错不阻断好监听器。
    clearWorkspaceContext()
    expect(healthy).toEqual(['load', 'clear'])
    expect(console.warn).toHaveBeenCalled()

    unsubscribeBoom()
    unsubscribeHealthy()
  })

  it('keeps notifying after clear followed by a fresh load', async () => {
    const reasons = []
    const unsubscribe = subscribeWorkspaceChange((p) => reasons.push(p.reason))

    clearWorkspaceContext() // 先订阅后 clear
    expect(reasons).toEqual(['clear'])

    client.get.mockResolvedValueOnce(contextResponse())
    await loadWorkspaceContext() // clear 之后再 load
    expect(reasons).toEqual(['clear', 'load'])

    unsubscribe()
  })

  it('unsubscribing one listener leaves the others subscribed', () => {
    const a = []
    const b = []
    const unsubA = subscribeWorkspaceChange((p) => a.push(p.reason))
    subscribeWorkspaceChange((p) => b.push(p.reason))

    unsubA()
    clearWorkspaceContext()

    expect(a).toEqual([])
    expect(b).toEqual(['clear'])
  })

  it('throws a TypeError for a non-function listener', () => {
    expect(() => subscribeWorkspaceChange(null)).toThrow(TypeError)
    expect(() => subscribeWorkspaceChange('nope')).toThrow(TypeError)
  })
})
