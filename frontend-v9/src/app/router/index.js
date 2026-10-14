import { createRouter, createWebHistory } from 'vue-router'
import { currentUser, routeRedirect } from '../../permissions/permissions'
import { ensureWorkspaceContext, getContext } from '../../shared/workspace'
import { UXD_ROUTES } from './routes-uxd'
import { UXE_A_CONSOLE_CHILDREN, UXE_A_FACTORY_CHILDREN, UXE_A_ROOT } from './routes-uxe-a'
import { UXE_B_ROUTES } from './routes-uxe-b'
import { legacyRedirectTarget } from './legacy-redirects'

/**
 * 三空间路由表（契约 §3 → 蓝图 R1 导航重组）。
 *
 * meta 约定（§3.1）：{space, domain, title, hidden?, requiresOwner?}；
 * - space：'app'|'console'|'factory'，守卫与 AppShell 选壳依据；
 * - domain：一级域中文标签（与导航树 domain.label 同源，蓝图 R1 8 域），面包屑渲染；
 * - title：页标题（document.title + 面包屑叶）；hidden：参数详情路由不入侧栏；
 * - requiresOwner：仅 /app/settings/* 标注，非 OWNER 守卫拦截。
 *
 * 页面组件：UX-B 阶段统一挂 StubPage 占位，后续阶段（UX-C/D/E）以 routes-uxd.js /
 * routes-uxe-a.js / routes-uxe-b.js 数组与页内直挂组件替换（routes-*.js 为各阶段
 * 单一事实源，保留供测试引用）。
 * 旧路径 302：见 legacy-redirects.js（查表 redirect，R8 显式判断 query.tab）。
 *
 * 蓝图 R1 新增：
 * - /app/tasks（WK-02 TaskCenter）
 * - /onboarding（ONB-01~03 三屏合一，hidden 顶层）
 * - /app/market/candidates（MK-03）
 * - /app/market/opportunity/:id（MK-02，hidden）
 * - 替换 compliance 两条 stub → 真实组件
 */
const stub = () => import('../../app/pages/StubPage.vue')

// ── UX-C 交付页面（按 IMPLEMENTATION_PLAN §2；未交付页仍挂 StubPage） ──
const home = () => import('../../pages/home/WorkspaceHome.vue')
const discovery = () => import('../../pages/market/Discovery.vue')
const products = () => import('../../pages/product/Products.vue')
const productDetail = () => import('../../pages/product/ProductDetail.vue')
const listings = () => import('../../pages/product/Listings.vue')
const launchCenter = () => import('../../pages/product/LaunchCenter.vue')
const launchDetail = () => import('../../pages/product/LaunchDetail.vue')
const shops = () => import('../../pages/channel/Shops.vue')

// ── 蓝图 R1 包 1 新增页面 ──
const taskCenter = () => import('../../pages/home/TaskCenter.vue')
const onboarding = () => import('../../pages/onboarding/Onboarding.vue')
const opportunityDetail = () => import('../../pages/market/OpportunityDetail.vue')
const candidates = () => import('../../pages/market/Candidates.vue')
const compliance = () => import('../../pages/compliance/Compliance.vue')
const approvals = () => import('../../pages/compliance/Approvals.vue')
// E09（R3-1A）：`channels` 路由的唯一挂载点在 index.js（指向真实 Channels.vue）。
// routes-uxd.js 不再重复声明同 path，消除「占位页先命中」的展开顺序风险。
const channels = () => import('../../pages/channel/Channels.vue')

const appChildren = [
  // ── 工作台域 ──
  { path: '', component: home, meta: { space: 'app', domain: '工作台', title: '经营首页' } },
  { path: 'tasks', component: taskCenter, meta: { space: 'app', domain: '工作台', title: '我的待办' } },
  // ── 发现与商品域 ──
  { path: 'market/discovery', component: discovery, meta: { space: 'app', domain: '发现与商品', title: '市场机会' } },
  { path: 'market/candidates', component: candidates, meta: { space: 'app', domain: '发现与商品', title: '商品候选池' } },
  { path: 'market/opportunity/:id', component: opportunityDetail, meta: { space: 'app', domain: '发现与商品', title: '机会详情', hidden: true } },
  { path: 'products', component: products, meta: { space: 'app', domain: '发现与商品', title: '商品库' } },
  { path: 'products/:id', component: productDetail, meta: { space: 'app', domain: '发现与商品', title: '商品详情', hidden: true } },
  { path: 'products/assets', component: stub, meta: { space: 'app', domain: '发现与商品', title: '素材中心' } },
  { path: 'listings', component: listings, meta: { space: 'app', domain: '发现与商品', title: 'Listing 工作台' } },
  { path: 'listings/:id', component: stub, meta: { space: 'app', domain: '发现与商品', title: 'Listing 详情', hidden: true } },
  { path: 'compliance', component: compliance, meta: { space: 'app', domain: '发现与商品', title: '合规报告' } },
  { path: 'compliance/approvals', component: approvals, meta: { space: 'app', domain: '发现与商品', title: '合规工作台' } },
  { path: 'launch', component: launchCenter, meta: { space: 'app', domain: '发现与商品', title: '上线中心' } },
  { path: 'launch/:id', component: launchDetail, meta: { space: 'app', domain: '发现与商品', title: '上线流程详情', hidden: true } },
  // ── 渠道与店铺域（E09：channels 唯一挂载点在此；channels/shops/:id 与
  //    routes-uxd.js 的 CH-03 一致，ShopDetail 已交付，非占位页）──
  { path: 'channels', component: channels, meta: { space: 'app', domain: '渠道与店铺', title: '渠道推荐' } },
  { path: 'channels/shops', component: shops, meta: { space: 'app', domain: '渠道与店铺', title: '店铺管理' } },
  { path: 'channels/shops/:id', component: () => import('../../pages/channel/ShopDetail.vue'),
    meta: { space: 'app', domain: '渠道与店铺', title: '店铺详情', hidden: true } },
  // ── UX-E 后半：AI 域与设置页 5 条（routes-uxe-b.js 单一事实源） ──
  ...UXE_B_ROUTES,
  // ── UX-D 经营闭环页 12 条（routes-uxd.js 单一事实源，path/meta 与冻结表一致） ──
  ...UXD_ROUTES,
]

// ── 顶层 hidden /onboarding（ONB-01~03 三屏合一，step query 切屏） ──
const onboardingRoute = {
  path: '/onboarding',
  component: onboarding,
  meta: { space: 'app', domain: '工作台', title: '新手引导', hidden: true },
}

const consoleChildren = [
  // ── UX-E 前半：控制台 4 页（routes-uxe-a.js 单一事实源） ──
  ...UXE_A_CONSOLE_CHILDREN,
]

const factoryChildren = [
  // ── UX-E 前半：工厂门户主页（routes-uxe-a.js 单一事实源） ──
  ...UXE_A_FACTORY_CHILDREN,
]

const routes = [
  // ── 旧路径 302 查表（契约 §3.2，30 条；未命中旧路径由 catch-all 落 404） ──
  ...legacyRedirectTable(),
  // ── 登录（全空间共用，壳外独立页；UX-E 前半真实组件） ──
  ...UXE_A_ROOT,
  // ── 顶层 hidden /onboarding（壳外独立页，meta.space='app' 但不用 WorkspaceShell） ──
  onboardingRoute,
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
