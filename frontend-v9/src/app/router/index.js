import { createRouter, createWebHistory } from 'vue-router'
import { currentUser, routeRedirect } from '../../permissions/permissions'
import { ensureWorkspaceContext, getContext } from '../../shared/workspace'
import { legacyRedirectTarget } from './legacy-redirects'

/**
 * 三空间路由表（契约 §3）。
 *
 * meta 约定（§3.1）：{space, domain, title, hidden?, requiresOwner?}；
 * - space：'app'|'console'|'factory'，守卫与 AppShell 选壳依据；
 * - domain：一级域中文标签（与导航树 domain.label 同源），面包屑渲染；
 * - title：页标题（document.title + 面包屑叶）；hidden：参数详情路由不入侧栏；
 * - requiresOwner：仅 /app/settings/* 标注，非 OWNER 守卫拦截。
 *
 * 页面组件：UX-B 阶段统一挂 StubPage 占位（真实页面由 UX-C/D/E 交付），
 * 路由 path/meta/懒加载结构按契约一次冻结，后续阶段只替换 component。
 * 旧路径 302：见 legacy-redirects.js（查表 redirect，R8 显式判断 query.tab）。
 */
const stub = () => import('../../app/pages/StubPage.vue')

const appChildren = [
  { path: '', component: stub, meta: { space: 'app', domain: '首页', title: '经营工作台' } },
  { path: 'market/discovery', component: stub, meta: { space: 'app', domain: '市场机会', title: '商品发现' } },
  { path: 'products', component: stub, meta: { space: 'app', domain: '商品经营', title: '商品池' } },
  { path: 'products/:id', component: stub, meta: { space: 'app', domain: '商品经营', title: '商品详情', hidden: true } },
  { path: 'listings', component: stub, meta: { space: 'app', domain: '商品经营', title: 'Listing 工作台' } },
  { path: 'listings/:id', component: stub, meta: { space: 'app', domain: '商品经营', title: 'Listing 详情', hidden: true } },
  { path: 'compliance', component: stub, meta: { space: 'app', domain: '商品经营', title: '合规报告中心' } },
  { path: 'compliance/approvals', component: stub, meta: { space: 'app', domain: '商品经营', title: '合规工作台' } },
  { path: 'launch', component: stub, meta: { space: 'app', domain: '商品经营', title: '上线中心' } },
  { path: 'launch/:id', component: stub, meta: { space: 'app', domain: '商品经营', title: '上线流程详情', hidden: true } },
  { path: 'channels/shops', component: stub, meta: { space: 'app', domain: '销售渠道', title: '店铺授权' } },
  { path: 'supply/suppliers', component: stub, meta: { space: 'app', domain: '货源中心', title: '供应商库' } },
  { path: 'supply/purchases', component: stub, meta: { space: 'app', domain: '货源中心', title: '采购单' } },
  { path: 'pricing', component: stub, meta: { space: 'app', domain: '经营优化', title: '动态定价' } },
  { path: 'ads', component: stub, meta: { space: 'app', domain: '经营优化', title: '广告增长' } },
  { path: 'orders', component: stub, meta: { space: 'app', domain: '订单履约', title: '订单管理' } },
  { path: 'refunds', component: stub, meta: { space: 'app', domain: '客户售后', title: '售后管理' } },
  { path: 'settlements', component: stub, meta: { space: 'app', domain: '订单履约', title: '账期结算' } },
  { path: 'support', component: stub, meta: { space: 'app', domain: '客户售后', title: '智能客服' } },
  { path: 'risk/alerts', component: stub, meta: { space: 'app', domain: '经营优化', title: '风险巡检' } },
  { path: 'analytics/bi', component: stub, meta: { space: 'app', domain: '数据分析', title: 'BI 经营分析' } },
  { path: 'analytics/finance', component: stub, meta: { space: 'app', domain: '数据分析', title: '财务工作台' } },
  { path: 'analytics/landed-cost', component: stub, meta: { space: 'app', domain: '数据分析', title: '到岸成本配置' } },
  { path: 'ai/workflows', component: stub, meta: { space: 'app', domain: 'AI 运营', title: 'AI 工作流' } },
  { path: 'ai/knowledge', component: stub, meta: { space: 'app', domain: 'AI 运营', title: '知识库' } },
  { path: 'ai/decisions', component: stub, meta: { space: 'app', domain: 'AI 运营', title: 'AI 决策依据' } },
  { path: 'settings/ai', component: stub, meta: { space: 'app', domain: '设置与管理', title: 'AI 与集成设置', requiresOwner: true } },
  { path: 'settings/team', component: stub, meta: { space: 'app', domain: '设置与管理', title: '用户与角色', requiresOwner: true } },
]

const consoleChildren = [
  { path: 'overview', component: stub, meta: { space: 'console', domain: '平台管理', title: '平台总览' } },
  { path: 'tenants', component: stub, meta: { space: 'console', domain: '平台管理', title: '租户管理' } },
  { path: 'audit', component: stub, meta: { space: 'console', domain: '平台管理', title: '访问审计' } },
  { path: 'maintenance', component: stub, meta: { space: 'console', domain: '平台管理', title: '维护' } },
]

const factoryChildren = [
  { path: 'products', component: stub, meta: { space: 'factory', domain: '工厂门户', title: '产品与产能' } },
]

const routes = [
  // ── 旧路径 302 查表（契约 §3.2，30 条；未命中旧路径由 catch-all 落 404） ──
  ...legacyRedirectTable(),
  // ── 登录（全空间共用） ──
  { path: '/console/login', component: stub, meta: { space: 'console', title: '登录' } },
  // ── 三空间外壳（AppShell 三薄壳选型依据 meta.space） ──
  {
    path: '/app',
    component: () => import('../../shells/WorkspaceShell.vue'),
    children: appChildren,
  },
  {
    path: '/console',
    component: () => import('../../shells/ConsoleShell.vue'),
    redirect: '/console/overview',
    children: consoleChildren,
  },
  {
    path: '/factory',
    component: () => import('../../shells/FactoryShell.vue'),
    children: factoryChildren,
  },
  // ── 错误页（契约 §3.3.3：404/403/500） ──
  { path: '/404', component: () => import('../errors/NotFound.vue'), meta: { title: '页面不存在' } },
  { path: '/403', component: () => import('../errors/Forbidden.vue'), meta: { title: '无访问权限' } },
  { path: '/500', component: () => import('../errors/ServerError.vue'), meta: { title: '服务异常' } },
  // ── 未匹配路由 → /404（不做静默 /app 兜底） ──
  { path: '/:pathMatch(.*)*', redirect: '/404' },
]

/** 把 302 查表展开为 vue-router redirect 路由（R8 的 /platform-admin 用函数 redirect）。 */
function legacyRedirectTable() {
  return [
    { path: '/login', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/', redirect: '/app' },
    { path: '/dashboard', redirect: '/app' },
    { path: '/discovery', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/products', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/listings', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/compliance', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/compliance-workbench', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/launch', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/launch/:id', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/shops', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/suppliers', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/factory-portal', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/pricing', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/ads', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/orders', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/refunds', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/settlements', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/support', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/workflows', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/knowledge', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/bi', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/finance', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/alerts', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/ai-decisions', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/users', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    { path: '/settings', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
    // R8：/platform-admin 与 /platform-admin?tab=audit 同 path 异 query。
    { path: '/platform-admin', redirect: (to) => legacyRedirectTarget(to) ?? '/404' },
  ]
}

const router = createRouter({ history: createWebHistory(), routes })

/**
 * 全局守卫（契约 §3.3，语义平移旧 frontend/src/router.js）：
 * 1. 有 token 先 ensureWorkspaceContext()（刷新不丢权限，现行约定）；
 * 2. routeRedirect() 判定（permissions.js，路径查 §3.2 表）；
 * 3. 命中 meta.title 时同步 document.title。
 * 失败不阻断跳转：Context 拿不到时按 legacy 兜底，用户至少还能用。
 */
router.beforeEach(async (to) => {
  const authenticated = Boolean(localStorage.getItem('erp_token'))
  if (authenticated) await ensureWorkspaceContext()
  const redirect = routeRedirect({
    path: to.path,
    authenticated,
    // 身份以 Context 为准（角色/来源/代客标记），legacy 仅在 Context 不可用时兜底。
    // 两者都要传：routeRedirect 内部保证 Context 胜出，legacy 只做兜底。
    user: currentUser(),
    context: getContext(),
    impersonating: Boolean(localStorage.getItem('erp_impersonating')),
  })
  if (redirect) return redirect
  if (to.meta?.title) document.title = `${to.meta.title} · AI 电商ERP`
  return true
})

export default router
