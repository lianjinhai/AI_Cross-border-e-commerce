import { createRouter, createWebHistory } from 'vue-router'
import { currentUser, routeRedirect } from './permissions'
import { ensureWorkspaceContext, getContext } from './workspace'

/**
 * 路由表。UX-02 为每条业务路由**新增** `meta.domain`（一级域中文标签，取值与
 * `frontend/src/composables/navigation.js` 的 domain.label 同源），供面包屑渲染；
 * `meta.title` 逐字保留不变（回归保护：frontend/tests/router.test.js 会读源码）。
 * 仅新增 meta 字段，不改既有 path / name / component 语义。
 */
const routes = [
  { path: '/login', component: () => import('./views/Login.vue') },
  {
    path: '/',
    component: () => import('./views/Layout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', component: () => import('./views/Dashboard.vue'), meta: { title: '驾驶舱', domain: '首页' } },
      { path: 'discovery', component: () => import('./views/Discovery.vue'), meta: { title: '商品发现', domain: '市场机会' } },
      { path: 'products', component: () => import('./views/Products.vue'), meta: { title: '商品池', domain: '商品经营' } },
      { path: 'listings', component: () => import('./views/Listings.vue'), meta: { title: 'Listing 工作台', domain: '商品经营' } },
      { path: 'compliance', component: () => import('./views/Compliance.vue'), meta: { title: '合规检测', domain: '商品经营' } },
      { path: 'compliance-workbench', component: () => import('./views/ComplianceWorkbench.vue'), meta: { title: '合规工作台', domain: '商品经营' } },
      { path: 'launch', component: () => import('./views/LaunchCenter.vue'), meta: { title: '上线中心', domain: '商品经营' } },
      { path: 'launch/:id', component: () => import('./views/LaunchDetail.vue'), meta: { title: '上线流程详情', domain: '商品经营' } },
      { path: 'shops', component: () => import('./views/Shops.vue'), meta: { title: '店铺授权', domain: '销售渠道' } },
      { path: 'suppliers', component: () => import('./views/Suppliers.vue'), meta: { title: '供应商', domain: '货源中心' } },
      { path: 'factory-portal', component: () => import('./views/FactoryPortal.vue'), meta: { title: '工厂供给门户', domain: '工厂门户' } },
      { path: 'pricing', component: () => import('./views/Pricing.vue'), meta: { title: '动态定价', domain: '经营优化' } },
      { path: 'ads', component: () => import('./views/Ads.vue'), meta: { title: '广告增长', domain: '经营优化' } },
      { path: 'orders', component: () => import('./views/Orders.vue'), meta: { title: '订单管理', domain: '订单履约' } },
      { path: 'refunds', component: () => import('./views/Refunds.vue'), meta: { title: '售后管理', domain: '客户售后' } },
      { path: 'settlements', component: () => import('./views/Settlements.vue'), meta: { title: '账期结算', domain: '订单履约' } },
      { path: 'support', component: () => import('./views/Support.vue'), meta: { title: '智能客服', domain: '客户售后' } },
      { path: 'workflows', component: () => import('./views/Workflows.vue'), meta: { title: 'AI 工作流', domain: 'AI 运营' } },
      { path: 'knowledge', component: () => import('./views/Knowledge.vue'), meta: { title: '知识库', domain: 'AI 运营' } },
      { path: 'bi', component: () => import('./views/BI.vue'), meta: { title: 'BI 经营分析', domain: '数据分析' } },
      { path: 'finance', component: () => import('./views/Finance.vue'), meta: { title: '财务工作台', domain: '数据分析' } },
      { path: 'alerts', component: () => import('./views/Alerts.vue'), meta: { title: '风险巡检', domain: '经营优化' } },
      { path: 'ai-decisions', component: () => import('./views/AiDecisions.vue'), meta: { title: 'AI 决策依据', domain: 'AI 运营' } },
      { path: 'users', component: () => import('./views/Users.vue'), meta: { title: '用户与角色', domain: '设置与管理', admin: true } },
      { path: 'settings', component: () => import('./views/Settings.vue'), meta: { title: 'AI 设置', domain: '设置与管理' } },
      { path: 'platform-admin', component: () => import('./views/PlatformAdmin.vue'), meta: { title: '平台管理', domain: '平台管理' } },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes })

/**
 * 启动引导：有 token 但内存里没有 Context 时先加载一次。
 *
 * 为什么必须有：`loadWorkspaceContext()` 此前只在登录成功时调用，用户按 F5
 * 刷新后 Context 归 null，所有 `hasPermission()` 都返回 null（未知），
 * 权限判断只能落回 legacy 分支——一旦 Phase 1.8 删掉 legacy，刷新后管理员
 * 会直接失去写权限。放在守卫里（而非 main.js）是因为守卫是唯一的必经路径，
 * 且已具备 token 判定。
 *
 * 失败不阻断跳转：Context 拿不到时按 legacy 兜底，用户至少还能用。
 */
router.beforeEach(async (to) => {
  const authenticated = Boolean(localStorage.getItem('erp_token'))
  if (authenticated) await ensureWorkspaceContext()
  return routeRedirect({
    path: to.path,
    authenticated,
    // Phase 1.8：身份以 Context 为准（角色/来源/代客标记），legacy 仅在
    // Context 不可用时兜底（请求失败 / 网络异常场景，见 permissions.js 说明）。
    // 两者都要传：`routeRedirect` 内部保证 Context 胜出，legacy 只做兜底。
    // 漏传 `user` 会让兜底分支拿到空角色——工厂账号进不去门户、管理员进不去
    // `/users`、合规审批员反而被放行到 `/orders`（越权）。
    user: currentUser(),
    context: getContext(),
    impersonating: Boolean(localStorage.getItem('erp_impersonating')),
  })
})

export default router
