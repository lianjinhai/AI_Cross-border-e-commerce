<template>
  <el-menu
    :default-active="activePath"
    :default-openeds="openedEntries"
    :collapse="collapsed"
    router
    class="shell-menu"
    style="border-right:none"
  >
    <template v-for="domain in navigation" :key="domain.key">
      <!-- B1：五个一级入口全部以 el-sub-menu 抽屉渲染（含原高频四域）。
           默认收起；仅含当前路由的域自动展开（见 openedEntries）。
           折叠态（collapsed）下所有 sub-menu 自动变浮层，减负荷、保持全页可达。 -->
      <el-sub-menu :index="domain.key" class="menu-sub">
        <template #title>
          <el-icon><component :is="domain.icon" /></el-icon>
          <span>{{ domain.label }}</span>
        </template>
        <el-menu-item v-for="item in domain.children" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
      </el-sub-menu>
    </template>
  </el-menu>
</template>

<script setup>
/**
 * 侧边导航（AppShell 子件）：渲染域数组（已按角色过滤）。
 *
 * B1（D62）：侧栏视觉上只展示五个一级入口。实现方式——无论域是否带 `collapsible`，
 * 一律以 Element Plus `el-sub-menu` 渲染（渲染层改动，路径不变）。`default-openeds`
 * 动态：仅当当前路由落在某域 children 内时展开该域，保证深链进入子页时对应分组可见；
 * 默认所有柜子收起（低频减负荷）。折叠态下 sub-menu 自动变浮层。
 *
 * 颜色（UI-07 令牌合规）：不再传 `background-color`/`text-color`/`active-text-color`
 * 字面量，改用 Element Plus 菜单 CSS 变量 + `--v91-*` 语义令牌（见 scoped style）。
 *
 * badge 语义见 shared/navigation/types.js（计数未接端点前不下发，本组件不渲染）。
 */
import { computed } from 'vue'

const props = defineProps({
  navigation: { type: Array, default: () => [] },
  activePath: { type: String, default: '' },
  collapsed: { type: Boolean, default: false },
})

/** 当前路由命中的一级入口 key（默认收起，仅展开含当前路由的入口）。
 *  支持详情路由前缀命中，如 /app/listings/9。 */
const openedEntries = computed(() => (props.navigation || [])
  .filter((domain) => domain.children
    && domain.children.some((child) => isWithin(child.path, props.activePath)))
  .map((domain) => domain.key))

/** path 是否命中当前路由（精确或作为父前缀，避免形近路径误判）。 */
function isWithin(base, current) {
  if (!base || !current) return false
  return current === base || current.startsWith(`${base}/`)
}
</script>

<style scoped>
/**
 * 深色侧栏配色全部走 `--v91-*` 语义令牌 + Element Plus 菜单变量，零字面量。
 * 通过 `:deep` 覆盖 EP 菜单默认（浅色）背景/文字变量，使其适配 navy-900 底。
 */
.shell-menu {
  --el-menu-bg-color: var(--v91-navy-900);
  --el-menu-text-color: var(--v91-sidebar-text);
  --el-menu-active-color: var(--v91-blue-600);
  --el-menu-hover-bg-color: var(--v91-sidebar-active-bg);
  background-color: var(--v91-navy-900);
  border-right: none;
}
.shell-menu :deep(.el-sub-menu__title) {
  font-weight: var(--font-weight-medium);
}
.shell-menu :deep(.el-menu-item.is-active) {
  color: var(--v91-sidebar-active-text);
  background-color: var(--v91-sidebar-active-bg);
}
.shell-menu :deep(.el-menu-item:hover),
.shell-menu :deep(.el-sub-menu__title:hover) {
  background-color: var(--v91-sidebar-active-bg);
}
</style>
