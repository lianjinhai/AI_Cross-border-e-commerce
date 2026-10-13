/**
 * Console 空间菜单树（契约 §2.2：4 项 + 蓝图 R1 包 3 新增 3 项，/console/*）。
 *
 * 旧 /platform-admin 单页 4 tab 按 FRONTEND_V9_NAVIGATION.md §2 拆为 4 页；
 * `?tab=audit` 的 query 子态语义废弃（audit 独立成页，见契约 §3.2 R8）。
 * /console/login 为全空间共用登录页，不入菜单。
 *
 * 蓝图 R1 包 3（PC-03/04/05，§B.3 / §5.19）新增 3 子项：
 * - /console/adapters  Adapter 认证中心（Registry 未核 → 各子能力显"尚未验证"）
 * - /console/rules     数据源与规则（admin 规则端点，维护页能力并入）
 * - /console/ai-resources  AI 资源与成本（ai 配额读未核 → 缺项显"未接入"）
 * PC-02 代客审计字段在 Tenants 页内处理，导航不变。
 */
export const CONSOLE_DOMAINS = [
  {
    key: 'console',
    label: '平台管理',
    icon: 'Platform',
    children: [
      { path: '/console/overview', label: '平台总览', icon: 'Platform' },
      { path: '/console/tenants', label: '租户管理', icon: 'OfficeBuilding' },
      { path: '/console/adapters', label: 'Adapter 认证中心', icon: 'Connection' },
      { path: '/console/rules', label: '数据源与规则', icon: 'Document' },
      { path: '/console/ai-resources', label: 'AI 资源与成本', icon: 'DataLine' },
      { path: '/console/audit', label: '访问审计', icon: 'Document' },
      { path: '/console/maintenance', label: '维护', icon: 'SetUp' },
    ],
  },
]
