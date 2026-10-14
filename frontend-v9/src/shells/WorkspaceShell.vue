<template>
  <AppShellCore
    space="workspace"
    :navigation="navigation"
    :impersonating="impersonating"
    :read-only="readOnly"
    @exit-impersonate="exitImpersonate"
  >
    <template #topbar-context>
      <!-- R3-2A 顶层上下文条：Workspace + 店铺范围 + 任务三计数（持续可见） -->
      <ShellContextBar
        :workspace-name="workspaceName"
        :shop-scope="shopScope"
        :counts="counts"
      />
    </template>
    <template #topbar-extras>
      <WorkspaceSwitcher :workspaces="workspaces" :active-id="activeWorkspaceId" @switch="onSwitchWorkspace" />
      <StoreSwitcher v-model="selectedShopId" :shops="shops" />
      <NavSearch :navigation="navigation" />
      <!-- 装配位（UX-E 已交付）：AiCopilot FAB+抽屉（features/aicopilot，Workspace 常显、
           工厂/控制台外壳不装配，天然满足「工厂账号不显示」）。 -->
      <AiCopilot />
      <!-- 待装配：TaskCenter（UX-C，workbench/todo 前 N 条 + 未读数）、
           NotificationBell（UX-C，alerts 新告警聚合）。 -->
    </template>
  </AppShellCore>
</template>

<script setup>
/**
 * Workspace 薄壳（契约 §2.1）：装配 WorkspaceSwitcher + StoreSwitcher +
 * 全局搜索 + AI 副驾驶（UX-E）；导航源 = 三空间菜单树按角色过滤（数据装配见 composables/workspaceShell.js）。
 * R3-2A：新增 #topbar-context 顶栏上下文条（Workspace/店铺范围 + 任务三计数）。
 */
import AppShellCore from './AppShellCore.vue'
import ShellContextBar from './ShellContextBar.vue'
import WorkspaceSwitcher from '../components/WorkspaceSwitcher.vue'
import StoreSwitcher from '../components/StoreSwitcher.vue'
import NavSearch from '../components/NavSearch.vue'
import AiCopilot from '../features/aicopilot/AiCopilot.vue'
import { useWorkspaceShell } from '../composables/workspaceShell'

const {
  workspaces, shops, selectedShopId, impersonating, readOnly,
  activeWorkspaceId, navigation, onSwitchWorkspace, exitImpersonate,
  workspaceName, shopScope, counts,
} = useWorkspaceShell()
</script>
