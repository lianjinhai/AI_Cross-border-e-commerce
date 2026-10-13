import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, nextTick, watchEffect } from 'vue'

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
  getWorkspaceEpoch,
  hasPermission,
  loadWorkspaceContext,
  loadWorkspaces,
  subscribeWorkspaceChange,
  switchWorkspace,
} = await import('../src/shared/workspace')

const {
  canWrite,
  roleKey,
} = await import('../src/permissions/permissions')

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

/**
 * UX-01：Context 必须响应式。背景是旧实现把 Context 存在普通模块变量里，
 * `Layout.vue` 的 computed 读它时不建立依赖 → 切换 Workspace 后菜单不刷新。
 * 这两条用例锁死「读取 getContext() 即建立响应式依赖」这一根因修复。
 */
describe('workspace context reactivity', () => {
  beforeEach(() => {
    clearWorkspaceContext()
    localStorage.clear()
    client.get.mockReset()
    client.post.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('updates a computed reader when the context loads and clears', async () => {
    const seen = computed(() => getContext())
    expect(seen.value).toBeNull()

    client.get.mockResolvedValueOnce(contextResponse())
    await loadWorkspaceContext()
    expect(seen.value).toEqual(CONTEXT)

    clearWorkspaceContext()
    expect(seen.value).toBeNull()
  })

  it('drives watchEffect when the context changes', async () => {
    const observed = []
    const stop = watchEffect(() => { observed.push(getContext()) })
    // watchEffect 立即执行一次，初始为 null。
    expect(observed).toEqual([null])

    client.get.mockResolvedValueOnce(contextResponse())
    await loadWorkspaceContext()
    await nextTick()
    expect(observed.at(-1)).toEqual(CONTEXT)

    clearWorkspaceContext()
    await nextTick()
    expect(observed.at(-1)).toBeNull()
    stop()
  })
})

describe('subscribeWorkspaceChange', () => {
  beforeEach(() => {
    clearWorkspaceContext()
    localStorage.clear()
    client.get.mockReset()
    client.post.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('fires once on load and once on clear with a monotonic epoch, then stops after unsubscribe', async () => {
    const events = []
    const unsubscribe = subscribeWorkspaceChange((payload) => { events.push(payload) })

    client.get.mockResolvedValueOnce(contextResponse())
    await loadWorkspaceContext()

    expect(events).toHaveLength(1)
    expect(events[0].reason).toBe('load')
    expect(events[0].context).toEqual(CONTEXT)

    clearWorkspaceContext()

    expect(events).toHaveLength(2)
    expect(events[1].reason).toBe('clear')
    expect(events[1].context).toBeNull()
    expect(events[1].epoch).toBeGreaterThan(events[0].epoch)
    expect(getWorkspaceEpoch()).toBe(events[1].epoch)

    unsubscribe()
    clearWorkspaceContext()

    // 退订后不再收到通知。
    expect(events).toHaveLength(2)
  })

  it('keeps earlier subscribers working across multiple clears', async () => {
    const events = []
    const unsubscribe = subscribeWorkspaceChange((payload) => { events.push(payload.reason) })

    clearWorkspaceContext()
    clearWorkspaceContext()

    expect(events).toEqual(['clear', 'clear'])
    unsubscribe()
  })
})
