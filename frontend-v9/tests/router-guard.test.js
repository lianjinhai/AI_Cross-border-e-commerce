import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * 启动引导回归：F5 刷新后必须重新拉取 Workspace Context。
 *
 * 缺陷背景（Phase 1.8 前置）：`loadWorkspaceContext()` 原先只在登录成功时调用，
 * 刷新页面后 Context 归 null，所有 `hasPermission()` 返回 null（未知），权限判断
 * 只能落回 legacy 分支。若不修就删 legacy，管理员刷新后会直接失去写权限。
 *
 * 测的是 `ensureWorkspaceContext()` 这一行为契约（守卫在每次导航时调用它），
 * 而不是通过真实导航触发——后者会连带加载 .vue 组件，慢且脆。
 */
const client = {
  get: vi.fn(),
  post: vi.fn(),
  interceptors: { request: { use: vi.fn() } },
}

vi.mock('axios', () => ({
  default: { create: vi.fn(() => client), get: vi.fn() },
}))

const {
  clearWorkspaceContext,
  ensureWorkspaceContext,
  getContext,
  hasPermission,
} = await import('../src/shared/workspace')

const CONTEXT = {
  user_id: 1,
  workspace_id: 10,
  role: 'OWNER',
  permissions: ['order:write', 'workspace:member:admin'],
  source: 'MEMBERSHIP',
}

describe('ensureWorkspaceContext (route guard bootstrap)', () => {
  beforeEach(() => {
    localStorage.clear()
    client.get.mockReset()
    client.get.mockResolvedValue({ data: CONTEXT })
    clearWorkspaceContext()
  })

  it('fetches the context when a token exists but memory is empty (F5 refresh)', async () => {
    localStorage.setItem('erp_token', 'tok')
    expect(getContext()).toBeNull()

    const ctx = await ensureWorkspaceContext()

    expect(client.get).toHaveBeenCalledWith('/me/workspace-context')
    expect(ctx).toEqual(CONTEXT)
    // 关键：能力判断此时必须读 Context，而不是回退 legacy
    expect(hasPermission('order:write')).toBe(true)
  })

  it('reuses the cached context instead of refetching on every navigation', async () => {
    localStorage.setItem('erp_token', 'tok')
    await ensureWorkspaceContext()
    await ensureWorkspaceContext()
    await ensureWorkspaceContext()
    expect(client.get).toHaveBeenCalledTimes(1)
  })

  it('skips the request entirely when there is no token', async () => {
    expect(await ensureWorkspaceContext()).toBeNull()
    expect(client.get).not.toHaveBeenCalled()
  })

  it('returns null without throwing when the request fails', async () => {
    localStorage.setItem('erp_token', 'tok')
    client.get.mockRejectedValue(new Error('network down'))

    expect(await ensureWorkspaceContext()).toBeNull()
    expect(getContext()).toBeNull()
  })
})
