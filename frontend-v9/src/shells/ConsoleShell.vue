<template>
  <AppShellCore
    space="console"
    :navigation="navigation"
    :impersonating="impersonating"
    @exit-impersonate="exitImpersonate"
  >
    <template #topbar-extras>
      <span class="console-shell__tenant">
        <el-icon><OfficeBuilding /></el-icon>
        {{ tenantLabel }}
      </span>
      <NavSearch :navigation="navigation" />
      <!-- AI 副驾驶：Console 不显示（旅程验收 J6/J7），不设装配位。 -->
    </template>
  </AppShellCore>
</template>

<script setup>
/**
 * Console 薄壳（契约 §2.1，≤60 行）：仅租户标识 + 搜索；无切换器、无副驾驶。
 * 代客横幅（常显可退出）由 AppShellCore 统一渲染：impersonating 经 impersonation
 * 模块判定，退出还原平台身份回 /console/overview。
 */
import { computed } from 'vue'
import AppShellCore from './AppShellCore.vue'
import NavSearch from '../components/NavSearch.vue'
import { CONSOLE_DOMAINS, buildDomains } from '../shared/navigation/filter'
import { ROLES } from '../permissions/permissions'
import { clearWorkspaceContext, getContext } from '../shared/workspace'
import { isImpersonating, restoreImpersonation } from '../composables/impersonation'

// PLATFORM_ADMIN(非代客) → console 树（buildDomains 单一事实源）。
const navigation = computed(() => buildDomains({
  roleKey: getContext()?.role || ROLES.PLATFORM_ADMIN,
  isImpersonating: false,
}))

const impersonating = computed(() => isImpersonating())

function exitImpersonate() {
  restoreImpersonation()
  clearWorkspaceContext()
  window.location.assign('/console/overview')
}

const tenantLabel = computed(() => getContext()?.workspace_name || '平台控制台')
</script>

<style scoped>
.console-shell__tenant {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-regular);
  font-size: var(--font-size-md);
}
</style>
