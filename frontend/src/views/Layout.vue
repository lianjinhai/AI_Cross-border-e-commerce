<template>
  <el-container style="height:100vh">
    <el-aside width="220px" style="background:#1f2d3d">
      <div class="logo">🤖 AI 电商ERP</div>
      <el-menu :default-active="activeMenu" router background-color="#1f2d3d"
        text-color="#bfcbd9" active-text-color="#409EFF" style="border-right:none">
        <template v-for="group in menus" :key="group.label">
          <div class="menu-group">{{ group.label }}</div>
          <el-menu-item v-for="m in group.items" :key="m.path" :index="m.path">
            <el-icon><component :is="m.icon" /></el-icon>
            <span>{{ m.label }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div style="display:flex;align-items:center">
          <span style="font-size:16px;font-weight:600">{{ $route.meta.title }}</span>
          <el-tag v-if="isSuper" type="danger" size="small" effect="dark" style="margin-left:10px">平台控制台</el-tag>
        </div>
        <el-dropdown @command="onCommand">
          <span class="user-chip"><el-icon class="mr8"><User /></el-icon>{{ displayName }}
            <el-tag size="small" style="margin-left:8px">{{ roleLabel }}</el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-if="isImpersonating" command="leave-impersonation">返回平台控制台</el-dropdown-item>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main style="padding:0;overflow:auto">
        <!-- 只读账号提示（角色界面差异化 D4）：让用户明确知道"按钮消失是权限所致"，
             而不是以为系统故障。仅 READ_ONLY 可见。 -->
        <el-alert v-if="isReadOnly" type="info" :closable="false" show-icon
          style="margin:12px 16px 0"
          title="当前为只读账号：写操作已隐藏，如需编辑请联系管理员" />
        <router-view />
      </el-main>
    </el-container>
    <AiAssistant v-if="!isSupplier" />
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AiAssistant from './AiAssistant.vue'
import { canAdmin, roleKey } from '../permissions'
import { clearWorkspaceContext, isMembershipContext, workspaceName } from '../workspace'

const route = useRoute()
const router = useRouter()
/**
 * Phase 1.8：`userInfo` 只用于**展示**（姓名、下拉），不再参与权限判断。
 *
 * 为什么姓名仍读 localStorage：冻结契约 `docs/phase1_interfaces.md` §7 的 PII
 * 红线规定 Context API 不输出 username/display_name，`to_public_dict()` 也刻意
 * 不含该字段（后端契约测试用 `set(body) == CONTEXT_FIELDS` 严格固化）。
 * 所以姓名只能由登录响应缓存提供——这是**纯显示数据**，不构成权限来源。
 * 权限与角色一律走 `roleKey()` / `canAdmin()`（Context 优先）。
 */
const userInfo = JSON.parse(localStorage.getItem('erp_user') || 'null')
const isImpersonating = Boolean(localStorage.getItem('erp_impersonating'))
/**
 * 顶部展示名：代客态下必须显示**被代管的租户**，而不是平台管理员真名——
 * 否则运营者在租户工作台看到的是平台方姓名，既困惑又泄露平台身份。
 * 租户名来自 Context（`workspace_name`，非 PII），无需读 localStorage。
 */
const displayName = computed(() => {
  if (isImpersonating) {
    const name = workspaceName()
    if (name) return `平台代管 · ${name}`
  }
  return userInfo?.display_name || '用户'
})
const ROLE_LABELS = {
  OWNER: '管理员', OPERATOR: '运营', READ_ONLY: '只读',
  COMPLIANCE: '合规审批', PLATFORM_ADMIN: '超级管理员', FACTORY_COLLABORATOR: '工厂伙伴',
}
// 角色标签以 Context 的新枚举为准（roleKey 内部已做 legacy 映射兜底）
const roleLabel = computed(() => ROLE_LABELS[roleKey()] || roleKey() || '未知')
const isSuper = computed(() => roleKey() === 'PLATFORM_ADMIN' && !isImpersonating)
const isSupplier = computed(() => roleKey() === 'FACTORY_COLLABORATOR')
const isOwner = computed(() => roleKey() === 'OWNER')
const isCompliance = computed(() => roleKey() === 'COMPLIANCE')
const isReadOnly = computed(() => roleKey() === 'READ_ONLY')
const canManageMembers = computed(() => canAdmin())

// 超级管理员：只显示平台控制台菜单，与业务菜单完全隔离（各分区由 /platform-admin 页内 el-tabs 承载）
const platformMenus = [
  { label: '平台管理', items: [
    { path: '/platform-admin', label: '平台控制台', icon: 'Platform' },
    { path: '/platform-admin?tab=audit', label: '访问审计', icon: 'Document' },
  ]},
]

const supplierMenus = [
  { label: '工厂门户', items: [
    { path: '/factory-portal', label: '产品与产能', icon: 'OfficeBuilding' },
  ]},
]

// 租户侧业务菜单（保持不变）
const businessMenus = [
  { label: '概览', items: [
    { path: '/dashboard', label: '驾驶舱', icon: 'Odometer' },
    { path: '/bi', label: 'BI 经营分析', icon: 'TrendCharts' },
    { path: '/alerts', label: '风险巡检', icon: 'Warning' },
  ]},
  { label: '商品', items: [
    { path: '/discovery', label: '商品发现', icon: 'Search' },
    { path: '/products', label: '商品池', icon: 'Goods' },
    { path: '/listings', label: 'Listing 工作台', icon: 'Document' },
    { path: '/launch', label: '上线中心', icon: 'Position' },
    { path: '/compliance-workbench', label: '合规工作台', icon: 'Finished' },
    { path: '/compliance', label: '合规检测', icon: 'CircleCheck' },
  ]},
  { label: '采购', items: [
    { path: '/shops', label: '店铺授权', icon: 'Link' },
    { path: '/suppliers', label: '供应商', icon: 'OfficeBuilding' },
    { path: '/pricing', label: '动态定价', icon: 'Coin' },
  ]},
  { label: '运营', items: [
    { path: '/ads', label: '广告增长', icon: 'Promotion' },
    { path: '/orders', label: '订单管理', icon: 'List' },
    { path: '/refunds', label: '售后管理', icon: 'RefreshLeft' },
    { path: '/settlements', label: '账期结算', icon: 'Wallet' },
    { path: '/finance', label: '财务工作台', icon: 'Money' },
    { path: '/support', label: '智能客服', icon: 'ChatDotRound' },
  ]},
  { label: '系统', items: [
    { path: '/workflows', label: 'AI 工作流', icon: 'MagicStick' },
    { path: '/knowledge', label: '知识库', icon: 'Reading' },
    { path: '/ai-decisions', label: 'AI 决策依据', icon: 'DocumentChecked' },
    { path: '/settings', label: 'AI 设置', icon: 'Setting' },
    ...(canManageMembers.value ? [{ path: '/users', label: '用户与角色', icon: 'UserFilled' }] : []),
  ]},
]

const menus = computed(() => {
  if (isSuper.value) return platformMenus
  if (isSupplier.value) return supplierMenus
  if (isCompliance.value) {
    // 合规员菜单：工作台放首位（其职责是审批+监控，不是逛商品池）；上线中心属只读可看
    const allowed = new Set(['/compliance-workbench', '/dashboard', '/bi', '/listings', '/compliance', '/launch'])
    return businessMenus.map(g => ({ ...g, items: g.items.filter(x => allowed.has(x.path)) })).filter(g => g.items.length)
  }
  if (!isOwner.value) {
    // 非 OWNER（含 OPERATOR/READ_ONLY）：隐藏管理入口 + 合规工作台
    // （工作台是合规员的专属作业界面，其他人看到会混淆职责边界）
    const hidden = ['/settings', '/users', '/compliance-workbench']
    return businessMenus.map(g => ({ ...g, items: g.items.filter(x => !hidden.includes(x.path)) })).filter(g => g.items.length)
  }
  return businessMenus
})

// 平台菜单高亮：/platform-admin 与 /platform-admin?tab=audit 用 query 区分，其余按路径
const activeMenu = computed(() => {
  if (route.path === '/platform-admin' && route.query.tab === 'audit') return '/platform-admin?tab=audit'
  return route.path
})

function onCommand(cmd) {
  if (cmd === 'leave-impersonation') {
    const saved = JSON.parse(localStorage.getItem('erp_impersonating') || 'null')
    if (saved?.token && saved?.user) { localStorage.setItem('erp_token', saved.token); localStorage.setItem('erp_user', JSON.stringify(saved.user)) }
    localStorage.removeItem('erp_impersonating')
    // Phase 1.8：退出代客必须清掉租户 Context 缓存，否则回到平台控制台后
    // 仍会带着租户身份（`roleKey()` 会返回 OWNER/OPERATOR 而非 PLATFORM_ADMIN）。
    clearWorkspaceContext()
    window.location.href = '/platform-admin'; return
  }
  if (cmd === 'logout') {
    localStorage.removeItem('erp_token')
    localStorage.removeItem('erp_user')
    localStorage.removeItem('erp_impersonating')
    clearWorkspaceContext()
    router.push('/login')
  }
}
</script>

<style scoped>
.logo { color: #fff; font-size: 18px; font-weight: 700; padding: 20px 16px; }
.menu-group { color: #5a6d82; font-size: 12px; padding: 12px 20px 4px; }
.header { display: flex; align-items: center; justify-content: space-between;
  background: #fff; border-bottom: 1px solid #e6e6e6; }
.user-chip { cursor: pointer; display: inline-flex; align-items: center; color: #303133; }
</style>
