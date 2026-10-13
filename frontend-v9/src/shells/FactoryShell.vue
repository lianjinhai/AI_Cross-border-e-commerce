<template>
  <AppShellCore space="factory" :navigation="navigation">
    <template #topbar-extras>
      <span class="factory-shell__name">
        <el-icon><OfficeBuilding /></el-icon>
        {{ factoryName }}
      </span>
      <!-- 工厂账号隐藏副驾驶（旅程验收 J6/J7）；顶栏无搜索/切换器。 -->
    </template>
  </AppShellCore>
</template>

<script setup>
/**
 * Factory 薄壳（契约 §2.1，≤60 行）：仅工厂名（只读标识，无副驾驶）。
 * 导航源 = factory 树（FACTORY_COLLABORATOR 专属）。
 */
import { computed } from 'vue'
import AppShellCore from './AppShellCore.vue'
import { FACTORY_DOMAINS } from '../shared/navigation/filter'
import { getContext } from '../shared/workspace'

const navigation = computed(() => FACTORY_DOMAINS)

const factoryName = computed(() => getContext()?.workspace_name || '工厂供给门户')
</script>

<style scoped>
.factory-shell__name {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-regular);
  font-size: var(--font-size-md);
}
</style>
