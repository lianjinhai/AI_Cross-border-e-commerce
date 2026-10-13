/**
 * Console 空间菜单树（契约 §2.2：4 项，/console/*）。
 *
 * 旧 /platform-admin 单页 4 tab 按 FRONTEND_V9_NAVIGATION.md §2 拆为 4 页；
 * `?tab=audit` 的 query 子态语义废弃（audit 独立成页，见契约 §3.2 R8）。
 * /console/login 为全空间共用登录页，不入菜单。
 */
export const CONSOLE_DOMAINS = [
  {
    key: 'console',
    label: '平台管理',
    icon: 'Platform',
    children: [
      { path: '/console/overview', label: '平台总览', icon: 'Platform' },
      { path: '/console/tenants', label: '租户管理', icon: 'OfficeBuilding' },
      { path: '/console/audit', label: '访问审计', icon: 'Document' },
      { path: '/console/maintenance', label: '维护', icon: 'SetUp' },
    ],
  },
]
