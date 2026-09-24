import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * `can(key)` 的完整测试（专家探讨 P1 修复）。
 *
 * 为什么单独一个文件：`can()` 是本轮 16 个页面按钮权限的**唯一入口**
 * （40+ 处引用），且它有两条分支——Context 路径与 legacy 兜底路径。
 * 原 `permissions.test.js` 只覆盖 canWrite/canAdmin/canApprove/routeRedirect，
 * 新增的 `can()` 完全没有测试守护：一旦它出错，16 个页面的按钮会静默
 * 消失或错误显示，且不会有任何测试变红。
 *
 * 权威事实源是**后端** `workspace_context.ROLE_PERMISSIONS`；本文件里的
 * 期望值与之手工对齐，并由后端 `tests/test_role_permissions.py` 的
 * `test_permission_keys_consistent_with_contract` 从另一侧断言，构成双向契约。
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

const { clearWorkspaceContext, loadWorkspaceContext } = await import('../src/workspace')
const { can, canAny } = await import('../src/permissions')

const PERMISSIONS = {
  OWNER: ['workspace:read', 'product:read', 'supply:read', 'listing:read', 'order:read',
    'finance:read', 'purchase:read', 'settlement:read', 'refund:read', 'compliance:read',
    'ai:read', 'workspace:write', 'product:write', 'supply:write', 'listing:write',
    'order:write', 'finance:write', 'purchase:write', 'settlement:write', 'refund:write',
    'ai:write', 'workspace:member:admin', 'compliance:approve', 'compliance:check'],
  OPERATOR: ['workspace:read', 'product:read', 'supply:read', 'listing:read', 'order:read',
    'finance:read', 'purchase:read', 'settlement:read', 'refund:read', 'compliance:read',
    'ai:read', 'workspace:write', 'product:write', 'supply:write', 'listing:write',
    'order:write', 'finance:write', 'purchase:write', 'settlement:write', 'refund:write',
    'ai:write'],
  READ_ONLY: ['workspace:read', 'product:read', 'supply:read', 'listing:read', 'order:read',
    'finance:read', 'purchase:read', 'settlement:read', 'refund:read', 'compliance:read',
    'ai:read'],
  COMPLIANCE: ['compliance:read', 'compliance:approve', 'compliance:check',
    'listing:read', 'product:read'],
  PLATFORM_ADMIN: ['platform:admin'],
  FACTORY_COLLABORATOR: ['supply:read', 'supply:write'],
}

/** 装载 Context（走真实 loadWorkspaceContext 路径，避免绕过被测代码）。 */
async function withContext(role) {
  client.get.mockResolvedValueOnce({
    data: {
      user_id: 1, workspace_id: 1, workspace_name: '测试空间', workspace_kind: 'TENANT',
      role, permissions: PERMISSIONS[role], data_scope: 'WORKSPACE_ALL',
      source: 'MEMBERSHIP', is_impersonating: false, trace_id: 't1',
    },
  })
  await loadWorkspaceContext()
}

function legacyUser(role) {
  localStorage.setItem('erp_user', JSON.stringify({ username: 'u', role }))
}

beforeEach(() => {
  localStorage.clear()
  clearWorkspaceContext()
  vi.clearAllMocks()
})

describe('can() — Context 路径（权威）', () => {
  it('OWNER 拥有全部写权限与特殊权限', async () => {
    await withContext('OWNER')
    for (const key of ['product:write', 'listing:write', 'settlement:write',
      'workspace:member:admin', 'compliance:approve', 'compliance:check']) {
      expect(can(key), `OWNER 应拥有 ${key}`).toBe(true)
    }
  })

  it('OPERATOR 有业务写权限，但没有管理/审批权限', async () => {
    await withContext('OPERATOR')
    expect(can('product:write')).toBe(true)
    expect(can('order:write')).toBe(true)
    expect(can('workspace:member:admin')).toBe(false)
    expect(can('compliance:approve')).toBe(false)
    expect(can('compliance:check')).toBe(false)
  })

  it('READ_ONLY 零写权限（只读角色的硬边界）', async () => {
    await withContext('READ_ONLY')
    const writeKeys = Object.values(PERMISSIONS).flat()
      .filter((k) => k.endsWith(':write'))
    for (const key of [...new Set(writeKeys)]) {
      expect(can(key), `READ_ONLY 不应拥有 ${key}`).toBe(false)
    }
    expect(can('product:read')).toBe(true)
  })

  it('COMPLIANCE 可检测可审批，但不能改业务数据', async () => {
    await withContext('COMPLIANCE')
    expect(can('compliance:check')).toBe(true)
    expect(can('compliance:approve')).toBe(true)
    expect(can('product:write')).toBe(false)
    expect(can('listing:write')).toBe(false)
    expect(can('order:write')).toBe(false)
    expect(can('product:read')).toBe(true)
  })

  it('PLATFORM_ADMIN 无业务权限', async () => {
    await withContext('PLATFORM_ADMIN')
    expect(can('product:write')).toBe(false)
    expect(can('compliance:check')).toBe(false)
    expect(can('product:read')).toBe(false)
  })

  it('FACTORY_COLLABORATOR 仅 supply 权限', async () => {
    await withContext('FACTORY_COLLABORATOR')
    expect(can('supply:write')).toBe(true)
    expect(can('supply:read')).toBe(true)
    expect(can('product:write')).toBe(false)
    expect(can('order:write')).toBe(false)
  })
})

describe('can() — legacy 兜底路径（工厂账号/Context 不可用）', () => {
  it('legacy admin 映射为 OWNER 能力', () => {
    legacyUser('admin')
    expect(can('product:write')).toBe(true)
    expect(can('compliance:check')).toBe(true)
    expect(can('workspace:member:admin')).toBe(true)
  })

  it('legacy operator 有业务写权限（含 compliance:check）但无管理权限', () => {
    legacyUser('operator')
    expect(can('product:write')).toBe(true)
    expect(can('workspace:member:admin')).toBe(false)
    // OPERATOR 拥有全部 _WRITE_PERMISSIONS，compliance:check 属其业务范围
    // （与后端 ROLE_PERMISSIONS 对齐，见 backend/tests/test_role_permissions.py 契约测试）
    expect(can('compliance:check')).toBe(true)
    expect(can('compliance:approve')).toBe(false)
  })

  it('legacy viewer 零写权限', () => {
    legacyUser('viewer')
    expect(can('product:write')).toBe(false)
    expect(can('order:write')).toBe(false)
  })

  it('legacy compliance_approver 可检测可审批，不能写业务', () => {
    legacyUser('compliance_approver')
    expect(can('compliance:check')).toBe(true)
    expect(can('compliance:approve')).toBe(true)
    expect(can('product:write')).toBe(false)
  })

  it('legacy supplier 仅 supply:write（工厂门户按钮可见）', () => {
    legacyUser('supplier')
    expect(can('supply:write')).toBe(true)
    expect(can('product:write')).toBe(false)
  })

  it('无用户信息时一律 false（fail-closed）', () => {
    expect(can('product:write')).toBe(false)
    expect(can('compliance:check')).toBe(false)
  })

  it('未知 legacy 角色降级为只读', () => {
    legacyUser('unknown_role')
    expect(can('product:write')).toBe(false)
  })
})

describe('canAny()', () => {
  it('任一能力满足即通过', async () => {
    await withContext('COMPLIANCE')
    expect(canAny('product:write', 'compliance:check')).toBe(true)
    expect(canAny('product:write', 'order:write')).toBe(false)
  })

  it('空参数列表为 false', async () => {
    await withContext('OWNER')
    expect(canAny()).toBe(false)
  })
})

describe('Context 优先于 legacy', () => {
  it('Context 为 COMPLIANCE 时，即使 legacy 是 admin 也按 Context 判定', async () => {
    legacyUser('admin')
    await withContext('COMPLIANCE')
    // Context 权威：不能因 legacy 是 admin 而放开写权限
    expect(can('product:write')).toBe(false)
    expect(can('compliance:check')).toBe(true)
  })
})
