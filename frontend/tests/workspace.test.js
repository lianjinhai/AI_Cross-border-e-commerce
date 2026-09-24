import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * workspace.js 用 axios.create 自建实例，这里 mock 掉 axios 模块，
 * 让 create() 返回一个可由测试驱动的假 client。
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
  contextRole,
  getContext,
  hasPermission,
  loadWorkspaceContext,
  loadWorkspaces,
  switchWorkspace,
} = await import('../src/workspace')

const {
  canWrite,
  roleKey,
} = await import('../src/permissions')

const CONTEXT = {
  user_id: 1,
  workspace_id: 10,
  workspace_name: '泉州工厂',
  workspace_kind: 'TENANT',
  role: 'OPERATOR',
  permissions: ['order:read', 'order:write'],
  data_scope: 'WORKSPACE_ALL',
  source: 'MEMBERSHIP',
  is_impersonating: false,
  trace_id: 'trace-1',
}

const contextResponse = (context = CONTEXT) => ({ data: context })
const errorResponse = (status = 500) => {
  const err = new Error(`request failed with ${status}`)
  err.response = { status, data: {} }
  return err
}

describe('workspace context cache', () => {
  beforeEach(() => {
    clearWorkspaceContext()
    localStorage.clear()
    client.get.mockReset()
    client.post.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('caches the context snapshot after a successful load', async () => {
    client.get.mockResolvedValueOnce(contextResponse())

    const loaded = await loadWorkspaceContext()

    expect(client.get).toHaveBeenCalledWith('/me/workspace-context')
    expect(loaded).toEqual(CONTEXT)
    expect(getContext()).toEqual(CONTEXT)
    expect(contextRole()).toBe('OPERATOR')
  })

  it('reports permission state: true / false / unknown', async () => {
    client.get.mockResolvedValueOnce(contextResponse())
    await loadWorkspaceContext()
    expect(hasPermission('order:write')).toBe(true)
    expect(hasPermission('workspace:member:admin')).toBe(false)

    clearWorkspaceContext()
    expect(hasPermission('order:write')).toBeNull()
  })

  it('returns null and keeps the cache empty when loading fails', async () => {
    client.get.mockRejectedValueOnce(errorResponse(500))

    const loaded = await loadWorkspaceContext()

    expect(loaded).toBeNull()
    expect(getContext()).toBeNull()
  })

  it('clears the cache on logout', async () => {
    client.get.mockResolvedValueOnce(contextResponse())
    await loadWorkspaceContext()
    expect(getContext()).not.toBeNull()

    clearWorkspaceContext()

    expect(getContext()).toBeNull()
    expect(hasPermission('order:write')).toBeNull()
  })
})

describe('capability resolution: context is the only authority (D24)', () => {
  beforeEach(() => {
    clearWorkspaceContext()
    localStorage.clear()
    client.get.mockReset()
    client.post.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('grants write to an OPERATOR context holding order:write', async () => {
    client.get.mockResolvedValueOnce(contextResponse())
    await loadWorkspaceContext()

    expect(canWrite()).toBe(true)
  })

  it('denies write for a READ_ONLY context even when legacy storage says admin', async () => {
    localStorage.setItem('erp_user', JSON.stringify({ role: 'admin' }))
    client.get.mockResolvedValueOnce(contextResponse({
      ...CONTEXT,
      role: 'READ_ONLY',
      permissions: ['order:read'],
    }))
    await loadWorkspaceContext()

    expect(canWrite()).toBe(false)
  })

  /**
   * D24：清掉 Context 后写权限必须变 false（旧实现会回退 legacy admin → true）。
   * 这两条用例锁死「Context 生命周期」与「权限可见性」的联动：登出/401 清理
   * Context 后，界面必须立刻退化为只读，而不是靠 localStorage 残留继续给按钮。
   */
  it('drops write access after the context is cleared (no legacy re-grant)', async () => {
    localStorage.setItem('erp_user', JSON.stringify({ role: 'admin' }))
    client.get.mockResolvedValueOnce(contextResponse({ ...CONTEXT, role: 'READ_ONLY', permissions: [] }))
    await loadWorkspaceContext()
    expect(canWrite()).toBe(false)

    clearWorkspaceContext()

    expect(canWrite()).toBe(false)
  })

  it('never grants write from the legacy role alone', () => {
    localStorage.setItem('erp_user', JSON.stringify({ role: 'admin' }))
    expect(canWrite()).toBe(false)
    localStorage.setItem('erp_user', JSON.stringify({ role: 'superadmin' }))
    expect(canWrite()).toBe(false)
  })
})

describe('roleKey mapping without a context', () => {
  beforeEach(() => {
    clearWorkspaceContext()
    localStorage.clear()
  })

  it.each([
    ['admin', 'OWNER'],
    ['operator', 'OPERATOR'],
    ['viewer', 'READ_ONLY'],
    ['compliance_approver', 'COMPLIANCE'],
    ['superadmin', 'PLATFORM_ADMIN'],
    ['supplier', 'FACTORY_COLLABORATOR'],
  ])('maps legacy %s to %s', (legacy, expected) => {
    localStorage.setItem('erp_user', JSON.stringify({ role: legacy }))

    expect(roleKey()).toBe(expected)
  })

  it('prefers the context role when a context is cached', async () => {
    localStorage.setItem('erp_user', JSON.stringify({ role: 'admin' }))
    client.get.mockResolvedValueOnce(contextResponse({ ...CONTEXT, role: 'COMPLIANCE' }))
    await loadWorkspaceContext()

    expect(roleKey()).toBe('COMPLIANCE')
  })
})

describe('workspace switching', () => {
  beforeEach(() => {
    clearWorkspaceContext()
    localStorage.clear()
    client.get.mockReset()
    client.post.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('reloads the context after a successful switch', async () => {
    client.get.mockResolvedValueOnce(contextResponse())
    await loadWorkspaceContext()
    client.post.mockResolvedValueOnce({ data: { ok: true, workspace_id: 22 } })
    client.get.mockResolvedValueOnce(contextResponse({
      ...CONTEXT,
      workspace_id: 22,
      workspace_name: '第二 Workspace',
    }))

    const ok = await switchWorkspace(22)

    expect(ok).toBe(true)
    expect(client.post).toHaveBeenCalledWith('/me/workspaces/22/switch')
    expect(client.get).toHaveBeenLastCalledWith('/me/workspace-context')
    expect(getContext().workspace_id).toBe(22)
  })

  it('returns false and preserves the cached context when the switch fails', async () => {
    client.get.mockResolvedValueOnce(contextResponse())
    await loadWorkspaceContext()
    client.post.mockRejectedValueOnce(errorResponse(403))

    const ok = await switchWorkspace(99)

    expect(ok).toBe(false)
    expect(getContext()).toEqual(CONTEXT)
  })
})

describe('workspace listing', () => {
  beforeEach(() => {
    clearWorkspaceContext()
    localStorage.clear()
    client.get.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('returns the items array on success and [] on failure', async () => {
    client.get.mockResolvedValueOnce({ data: { items: [{ id: 1, name: 'A' }], total: 1 } })
    expect(await loadWorkspaces()).toEqual([{ id: 1, name: 'A' }])

    client.get.mockRejectedValueOnce(errorResponse(500))
    expect(await loadWorkspaces()).toEqual([])
  })
})
