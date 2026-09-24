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
const { can, canAdmin, canAny, canWrite } = await import('../src/permissions')

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

/**
 * Phase 1.8 / D24：Context 不可用时 `can()` **一律 false**（fail-closed）。
 *
 * 本段此前的期望值是从 `LEGACY_CAPABILITIES` 抄下来的（admin→OWNER 全套写权限、
 * supplier→supply:write 等）。那套映射已删除，理由：`erp_user` 在 localStorage
 * 可被用户篡改，用它授权等于把写按钮的可见性交给伪造输入。真实写操作后端另有
 * 独立鉴权（`require_write` 只放行 admin/operator），因此前端降级为只读不削弱安全。
 *
 * 注意这组用例的覆盖边界：它只证明「无 Context 不授权」。若有人把 `can()` 改成
 * 恒返回 false，本段仍会全绿——真正的守护是上面「Context 路径（权威）」那组，
 * 那里断言了 OWNER 拥有全部写权限。改代码时不要把两者之一删掉。
 */
describe('can() — Context 不可用时一律 false（fail-closed，D24）', () => {
  it.each(['admin', 'owner', 'operator', 'viewer', 'compliance_approver', 'supplier', 'superadmin'])(
    'legacy %s 不授予任何权限',
    (legacyRole) => {
      legacyUser(legacyRole)
      for (const key of ['product:write', 'order:write', 'supply:write', 'finance:write',
        'workspace:member:admin', 'compliance:check', 'compliance:approve', 'product:read']) {
        expect(can(key), `${legacyRole} 不应因 legacy 身份获得 ${key}`).toBe(false)
      }
    },
  )

  it('伪造 legacy admin 也拿不到写权限（真实缺陷回归）', () => {
    // 实测复现路径：改 localStorage.erp_user.role 从 viewer→admin，
    // 旧实现会让 canWrite()/can() 变 true、写按钮出现。
    legacyUser('admin')
    expect(canWrite()).toBe(false)
    expect(canAdmin()).toBe(false)
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

/**
 * G-3：工厂账号的 Context 通道（真实缺陷回归）。
 *
 * 背景：`app/auth.py` 曾把工厂账号挡在 `/api/me/*` 之外（403），工厂 Context
 * 永远为空 —— 前端只能用 legacy 兜底判断权限，这是 Phase 1.8「删除旧入口」
 * 卡住的唯一前置。现已放行只读端点（`/switch` 仍拒，工厂无可切换项）。
 *
 * 本组用例锁死「工厂账号拿 Context 时，权限判定必须走 Context 权威源」：
 * 后端 `ROLE_PERMISSIONS[FACTORY_COLLABORATOR] = {supply:read, supply:write}`。
 * 若有人误把该分支改回 legacy 兜底（或让 legacy 压过 Context），
 * 权限判定会漂移，本用例即失败。
 */
describe('G-3 factory collaborator via context', () => {
  it('从 Context 取得 supply 权限，且拿不到任何业务写权限', async () => {
    client.get.mockResolvedValueOnce({
      data: {
        user_id: 7,
        workspace_id: 3,
        workspace_name: 'api-ctx-factory',
        workspace_kind: 'FACTORY',
        role: 'FACTORY_COLLABORATOR',
        permissions: ['supply:read', 'supply:write'],
        data_scope: 'FACTORY_SELF',
        source: 'FACTORY',
        is_impersonating: false,
        trace_id: 't',
      },
    })
    await loadWorkspaceContext()
    expect(can('supply:write')).toBe(true)
    expect(can('supply:read')).toBe(true)
    // 工厂身份的边界：除 supply 外一律不得授权
    for (const key of ['order:write', 'product:write', 'finance:write',
      'workspace:member:admin', 'compliance:approve']) {
      expect(can(key), `${key} 不应授予工厂账号`).toBe(false)
    }
  })
})
