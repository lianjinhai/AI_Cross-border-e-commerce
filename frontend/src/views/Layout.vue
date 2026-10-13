<template>
  <el-container style="height:100vh">
    <el-aside width="220px" style="background:#1f2d3d">
      <div class="logo">🤖 AI 电商ERP</div>
      <SidebarNav :domains="menus" :active-path="activeMenu" />
    </el-aside>
    <el-container>
      <el-header class="header">
        <div style="display:flex;align-items:center">
          <PageHeader :title="$route.meta.title">
            <template #breadcrumb>
              <Breadcrumb :items="breadcrumbItems" />
            </template>
          </PageHeader>
          <el-tag v-if="isSuper" type="danger" size="small" effect="dark" style="margin-left:10px">平台控制台</el-tag>
        </div>
        <div style="display:flex;align-items:center;gap:12px">
          <WorkspaceSwitcher />
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
        </div>
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
import WorkspaceSwitcher from '../components/WorkspaceSwitcher.vue'
import SidebarNav from '../components/SidebarNav.vue'
import PageHeader from '../components/PageHeader.vue'
import Breadcrumb from '../components/Breadcrumb.vue'
import { buildDomains } from '../composables/navigation'
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
const isReadOnly = computed(() => roleKey() === 'READ_ONLY')
const canManageMembers = computed(() => canAdmin())

/**
 * 11 域一级导航（UX-02）：菜单结构与角色过滤抽到 `composables/navigation.js`。
 * roleKey() 读 Workspace Context（响应式，UX-01 已修），切换 Workspace 后菜单自动重算。
 */
const menus = computed(() => buildDomains({
  roleKey: roleKey(),
  canManageMembers: canManageMembers.value,
}))

/**
 * 面包屑：一级域（路由 meta.domain）→ 当前页（meta.title）。
 * meta.domain 取中文域名标签，与 navigation.js 的 domain.label 同源，全站统一。
 */
const breadcrumbItems = computed(() => {
  const items = []
  if (route.meta.domain) items.push({ label: route.meta.domain })
  if (route.meta.title) items.push({ label: route.meta.title })
  return items
})

// 平台菜单高亮：/platform-admin 与 /platform-admin?tab=audit 用 query 区分，其余按路径；
// 详情页 /launch/:id 归一到 /launch，保证「上线中心」菜单持续高亮。
const activeMenu = computed(() => {
  if (route.path === '/platform-admin' && route.query.tab === 'audit') return '/platform-admin?tab=audit'
  if (route.path.startsWith('/launch/')) return '/launch'
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
.header { display: flex; align-items: center; justify-content: space-between;
  background: #fff; border-bottom: 1px solid #e6e6e6; }
.user-chip { cursor: pointer; display: inline-flex; align-items: center; color: #303133; }
</style>
