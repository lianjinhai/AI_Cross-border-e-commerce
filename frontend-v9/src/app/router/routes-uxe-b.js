/**
 * UX-E 后半（AI 域与设置页）路由数组（契约 §3 meta 约定 → 蓝图 R1 扩展）。
 *
 * 特殊约定（并行期）：**不修改 src/app/router/index.js**（该文件由总调度合并），
 * 用下列条目替换 index.js appChildren 中对应 path 的 StubPage 挂载
 * （path/meta 与 index.js 现有条目逐一对应，仅 component 不同）：
 *
 *   ai/workflows  → ../../pages/aiops/Workflows.vue
 *   ai/knowledge  → ../../pages/aiops/Knowledge.vue
 *   ai/decisions  → ../../pages/aiops/AiDecisions.vue
 *   settings/ai   → ../../pages/settings/AiSettings.vue
 *   settings/team → ../../pages/settings/TeamSettings.vue
 *
 * 蓝图 R1 新增条目（包 1 路由挂载层；页面组件按 P 级落包 2/3，本表先挂占位
 * 组件保证路由可达——P1 页（AI-02/SET-01/SET-03）挂 StubPage 语义的占位，
 * P2 页（SET-04/AI-04）同理；真实页面由包 2/3 替换 component）：
 *
 *   ai/actions        → AI-02 AI 行动中心（P1，routes-uxe-b 追加区段，包 2 挂真实页）
 *   settings/workspace → SET-01 空间信息（P1，requiresOwner，包 2 挂真实页）
 *   settings/credentials → SET-03 凭据管理（P1，requiresOwner，包 2 挂真实页）
 *
 * meta 逐字沿用 index.js 冻结值（space/domain/title/requiresOwner），
 * 保证面包屑、OWNER 专属守卫（isOwnerOnlyPath）行为不变。
 * 域 meta.domain 同步蓝图 R1 8 域中文标签。
 */

/** 占位组件（本表 P1/P2 新条目先挂占位，真实页由后续包替换）。 */
const stubPage = () => import('../../app/pages/StubPage.vue')

export const UXE_B_ROUTES = [
  {
    path: 'ai/workflows',
    component: () => import('../../pages/aiops/Workflows.vue'),
    meta: { space: 'app', domain: 'AI 与自动化', title: '工作流' },
  },
  {
    path: 'ai/knowledge',
    component: () => import('../../pages/aiops/Knowledge.vue'),
    meta: { space: 'app', domain: 'AI 与自动化', title: '知识库' },
  },
  {
    path: 'ai/decisions',
    component: () => import('../../pages/aiops/AiDecisions.vue'),
    meta: { space: 'app', domain: 'AI 与自动化', title: '决策依据' },
  },
  {
    path: 'settings/ai',
    component: () => import('../../pages/settings/AiSettings.vue'),
    meta: { space: 'app', domain: '设置与管理', title: 'AI 与集成设置', requiresOwner: true },
  },
  {
    path: 'settings/team',
    component: () => import('../../pages/settings/TeamSettings.vue'),
    meta: { space: 'app', domain: '设置与管理', title: '用户与角色', requiresOwner: true },
  },
  // ── 蓝图 R1 包 1 追加区段（P1 AI-02 + SET-01/SET-03；真实页已由包 2 挂，替换只读占位） ──
  {
    path: 'ai/actions',
    component: () => import('../../pages/aiops/AiActions.vue'),
    meta: { space: 'app', domain: 'AI 与自动化', title: 'AI 行动中心' },
  },
  {
    path: 'settings/workspace',
    component: () => import('../../pages/settings/WorkspaceInfo.vue'),
    meta: { space: 'app', domain: '设置与管理', title: '空间信息', requiresOwner: true },
  },
  {
    path: 'settings/credentials',
    component: () => import('../../pages/settings/Credentials.vue'),
    meta: { space: 'app', domain: '设置与管理', title: '凭据管理', requiresOwner: true },
  },
  {
    path: 'settings/plan',
    component: stubPage,
    meta: { space: 'app', domain: '设置与管理', title: '套餐管理', requiresOwner: true },
  },
  // ── 蓝图 R1 P0 补齐：导航叶子可点（真实页未交付，先挂 StubPage 防 404，标记待接入） ──
  {
    path: 'ai/agent-runs',
    component: stubPage,
    meta: { space: 'app', domain: 'AI 与自动化', title: 'Agent 运行', requiresOwner: true },
  },
]
