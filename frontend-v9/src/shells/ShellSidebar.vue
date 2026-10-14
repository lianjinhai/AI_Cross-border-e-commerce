<template>
  <el-menu
    :default-active="activePath"
    :default-openeds="openedEntries"
    :collapse="collapsed"
    router
    background-color="#1f2d3d"
    text-color="#bfcbd9"
    active-text-color="#409EFF"
    style="border-right:none"
  >
    <template v-for="domain in navigation" :key="domain.key">
      <!-- 可折叠入口（R3-2A：全部工具 tools）→ el-sub-menu 抽屉 -->
      <el-sub-menu v-if="domain.collapsible" :index="domain.key" class="menu-sub">
        <template #title>
          <el-icon><component :is="domain.icon" /></el-icon>
          <span>{{ domain.label }}</span>
        </template>
        <el-menu-item v-for="item in domain.children" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
      </el-sub-menu>
      <!-- 高频入口 → 分组标题 + 平铺叶子（沿用旧 8 域渲染观感） -->
      <template v-else>
        <div v-if="!collapsed" class="menu-group">{{ domain.label }}</div>
        <el-menu-item v-for="item in domain.children" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
      </template>
    </template>
  </el-menu>
</template>

<script setup>
/**
 * 侧边导航（AppShell 子件）：渲染域数组（已按角色过滤），沿用现网深色侧栏配色。
 *
 * R3-2A：导航由 8 域收敛为 4+1 入口。高频 4 入口继续「分组标题 + 平铺叶子」，
 * 「全部工具」（collapsible=true）以 Element Plus `el-sub-menu` 折叠渲染。
 * 折叠态（collapsed）下 sub-menu 自动变浮层，其余入口退化为纯图标项（既有行为）。
 *
 * `default-openeds` 动态：仅当当前路由落在某可折叠入口内时展开该入口，
 * 保证深链进入工具柜子页时对应分组可见；默认工具柜收起（低频，减负荷）。
 * badge 语义见 shared/navigation/types.js（计数未接端点前不下发）。
 */
import { computed } from 'vue'

const props = defineProps({
  navigation: { type: Array, default: () => [] },
  activePath: { type: String, default: '' },
  collapsed: { type: Boolean, default: false },
})

/** 当前路由命中的可折叠入口 key（支持详情路由前缀命中，如 /app/listings/9）。 */
const openedEntries = computed(() => (props.navigation || [])
  .filter((domain) => domain.collapsible
    && domain.children.some((child) => isWithin(child.path, props.activePath)))
  .map((domain) => domain.key))

/** path 是否命中当前路由（精确或作为父前缀，避免形近路径误判）。 */
function isWithin(base, current) {
  if (!base || !current) return false
  return current === base || current.startsWith(`${base}/`)
}
</script>

<style scoped>
.menu-group { color: #5a6d82; font-size: 12px; padding: 12px 20px 4px; }
.menu-sub :deep(.el-sub-menu__title) { font-weight: var(--font-weight-medium); }
</style>
