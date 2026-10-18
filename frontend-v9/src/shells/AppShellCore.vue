<template>
  <el-container class="shell" :class="`shell--${space}`">
    <el-aside :width="collapsed ? 'var(--layout-sidebar-collapsed)' : 'var(--layout-sidebar-width)'" class="shell__aside">
      <div class="shell__brand" @click="toggleSidebar">
        <span class="shell__brand-dot" :style="{ background: accentColor }" />
        <span v-if="!collapsed" class="shell__brand-text">{{ spaceLabel }}</span>
      </div>
      <ShellSidebar :navigation="navigation" :active-path="activePath" :collapsed="collapsed" />
    </el-aside>
    <el-container class="shell__body">
      <el-header class="shell__topbar" height="var(--layout-topbar-height)">
        <div class="shell__topbar-left">
          <!-- R3-2A：顶层上下文条槽（Workspace/店铺范围 + 任务计数条，baseline §3）。
               仅 Workspace 薄壳填充；控制台/工厂留空（:empty 自动隐藏，不留分隔符）。 -->
          <div class="shell__topbar-context"><slot name="topbar-context" /></div>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item v-for="item in breadcrumb" :key="item.label" :to="item.to">
              {{ item.label }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="shell__topbar-extras">
          <slot name="topbar-extras" />
        </div>
        <ShellTopbar
          :space="space"
          :role-key="roleKey"
          :user-name="userName"
          :impersonating="impersonating"
          @logout="logout"
          @exit-impersonate="$emit('exit-impersonate')"
        />
      </el-header>
      <ShellBanner
        :impersonating="impersonating"
        :read-only="readOnly"
        :workspace-name="workspaceName"
        @exit-impersonate="$emit('exit-impersonate')"
      >
        <slot name="banner" />
      </ShellBanner>
      <el-main class="shell__main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
/**
 * AppShell 共享内核（契约 §2.1）：布局骨架 = 侧栏 + 顶栏槽 + 内容区 + 状态横幅
 * + 面包屑。三薄壳（Workspace/Console/Factory）只注入各自的导航源、空间强调色
 * 与顶栏装配，不做巨型带分支的单组件。
 *
 * 状态横幅优先级（NAVIGATION §4）：代客中 > 只读态 > partial 提示（partial 由
 * 页面级 PartialDataBanner 语义承接）。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { roleKey as contextRoleKey, defaultLanding } from '../permissions/permissions'
import { clearWorkspaceContext, getContext } from '../shared/workspace'
import ShellSidebar from './ShellSidebar.vue'
import ShellTopbar from './ShellTopbar.vue'
import ShellBanner from './ShellBanner.vue'

const props = defineProps({
  space: { type: String, required: true }, // 'workspace' | 'console' | 'factory'
  navigation: { type: Array, default: () => [] },
  impersonating: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['exit-impersonate', 'toggle-sidebar'])

const SPACE_META = {
  workspace: { label: '经营工作台', accent: 'var(--space-accent-workspace)' },
  console: { label: '平台管理控制台', accent: 'var(--space-accent-console)' },
  factory: { label: '工厂供给门户', accent: 'var(--space-accent-factory)' },
}

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

/** 侧栏折叠切换（品牌区点击）：本地翻转 + 上报父级（兼容既有监听）。 */
function toggleSidebar() {
  collapsed.value = !collapsed.value
  emit('toggle-sidebar')
}

/**
 * 移动端自适应（R3-2B 响应式）：视口 ≤768px 自动收起侧栏为图标条，
 * 用户仍可点击品牌区展开；恢复宽屏时不强制展开（尊重用户选择）。
 */
let mobileQuery = null
function syncCollapsedOnResize(event) {
  if (event && event.matches) collapsed.value = true
}
onMounted(() => {
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    mobileQuery = window.matchMedia('(max-width: 768px)')
    if (mobileQuery.matches) collapsed.value = true
    mobileQuery.addEventListener('change', syncCollapsedOnResize)
  }
})
onUnmounted(() => {
  if (mobileQuery) mobileQuery.removeEventListener('change', syncCollapsedOnResize)
})

const spaceLabel = computed(() => SPACE_META[props.space]?.label || '')
const accentColor = computed(() => SPACE_META[props.space]?.accent || 'var(--color-primary)')
const roleKey = computed(() => contextRoleKey())
const workspaceName = computed(() => getContext()?.workspace_name || '')

const activePath = computed(() => route.path)

/** 面包屑：domain（一级域）→ title（叶），来自路由 meta（与导航树同源）。 */
const breadcrumb = computed(() => {
  const items = []
  if (route.meta?.domain && route.meta.domain !== route.meta?.title) items.push({ label: route.meta.domain })
  if (route.meta?.title) items.push({ label: route.meta.title })
  return items
})

const userName = computed(() => {
  try { return JSON.parse(localStorage.getItem('erp_user') || 'null')?.username || '' }
  catch { return '' }
})

/** 退出登录：清 token/身份/代客标记/Context，回登录页。 */
function logout() {
  localStorage.removeItem('erp_token')
  localStorage.removeItem('erp_user')
  localStorage.removeItem('erp_impersonating')
  clearWorkspaceContext()
  router.push('/console/login')
}
</script>

<style scoped>
.shell {
  min-height: 100vh;
  overflow-x: hidden;
}
.shell__aside {
  background: var(--color-sidebar);
  transition: width 0.2s;
  overflow-x: hidden;
  flex: none;
}
.shell__brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-4);
  cursor: pointer;
}
.shell__brand-dot {
  width: 10px;
  height: 10px;
  border-radius: var(--radius-round);
  flex: none;
}
.shell__brand-text {
  color: var(--color-surface);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  white-space: nowrap;
}
.shell__topbar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border-light);
}
.shell__topbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.shell__topbar-context {
  display: flex;
  align-items: center;
  padding-right: var(--space-3);
  border-right: 1px solid var(--color-border-light);
}
/* 未填充上下文条的薄壳（控制台/工厂）不留分隔符 */
.shell__topbar-context:empty { display: none; }
.shell__topbar-extras {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
}
.shell__main {
  background: var(--color-bg);
  padding: var(--layout-content-gutter);
  min-width: 0;
}
/* 窄屏（≤768）：收紧顶栏间距，隐藏上下文条（窄屏易致横向溢出），
   侧栏由 JS 自动收起为图标条（见 script）。 */
@media (max-width: 768px) {
  .shell__brand { padding: var(--space-3) var(--space-2); }
  .shell__topbar { gap: var(--space-2); }
  .shell__topbar-context { display: none; }
}
</style>
