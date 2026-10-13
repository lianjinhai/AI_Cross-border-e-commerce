<template>
  <AppShellCore
    space="workspace"
    :navigation="navigation"
    :impersonating="impersonating"
    :read-only="readOnly"
    @exit-impersonate="exitImpersonate"
  >
    <template #topbar-extras>
      <WorkspaceSwitcher :workspaces="workspaces" :active-id="activeWorkspaceId" @switch="onSwitchWorkspace" />
      <StoreSwitcher v-model="selectedShopId" :shops="shops" />
      <NavSearch :navigation="navigation" />
      <!-- 装配位（后续阶段交付，不放可点击占位入口）：
           TaskCenter（UX-C，workbench/todo 前 N 条 + 未读数）、
           NotificationBell（UX-C，alerts 新告警聚合）、
           AiCopilot FAB+抽屉（UX-E features/aicopilot，Workspace 常显）。 -->
    </template>
  </AppShellCore>
</template>

<script setup>
/**
 * Workspace 薄壳（契约 §2.1，≤60 行）：装配 WorkspaceSwitcher + StoreSwitcher +
 * 全局搜索；导航源 = 三空间菜单树按角色过滤（数据装配见 composables/workspaceShell.js）。
 */
import AppShellCore from './AppShellCore.vue'
import WorkspaceSwitcher from '../components/WorkspaceSwitcher.vue'
import StoreSwitcher from '../components/StoreSwitcher.vue'
import NavSearch from '../components/NavSearch.vue'
import { useWorkspaceShell } from '../composables/workspaceShell'

const {
  workspaces, shops, selectedShopId, impersonating, readOnly,
  activeWorkspaceId, navigation, onSwitchWorkspace, exitImpersonate,
} = useWorkspaceShell()
</script>
