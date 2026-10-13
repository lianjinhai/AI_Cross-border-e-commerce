/**
 * UX-E 后半（AI 域与设置页）路由数组（契约 §3 meta 约定）。
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
 * meta 逐字沿用 index.js 冻结值（space/domain/title/requiresOwner），
 * 保证面包屑、OWNER 专属守卫（isOwnerOnlyPath）行为不变。
 */

export const UXE_B_ROUTES = [
  {
    path: 'ai/workflows',
    component: () => import('../../pages/aiops/Workflows.vue'),
    meta: { space: 'app', domain: 'AI 运营', title: 'AI 工作流' },
  },
  {
    path: 'ai/knowledge',
    component: () => import('../../pages/aiops/Knowledge.vue'),
    meta: { space: 'app', domain: 'AI 运营', title: '知识库' },
  },
  {
    path: 'ai/decisions',
    component: () => import('../../pages/aiops/AiDecisions.vue'),
    meta: { space: 'app', domain: 'AI 运营', title: 'AI 决策依据' },
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
]
