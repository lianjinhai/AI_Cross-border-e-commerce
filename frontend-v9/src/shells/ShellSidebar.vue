<template>
  <el-menu
    :default-active="activePath"
    :collapse="collapsed"
    router
    background-color="#1f2d3d"
    text-color="#bfcbd9"
    active-text-color="#409EFF"
    style="border-right:none"
  >
    <template v-for="domain in navigation" :key="domain.key">
      <div v-if="!collapsed" class="menu-group">{{ domain.label }}</div>
      <el-menu-item v-for="item in domain.children" :key="item.path" :index="item.path">
        <el-icon><component :is="item.icon" /></el-icon>
        <template #title>{{ item.label }}</template>
      </el-menu-item>
    </template>
  </el-menu>
</template>

<script setup>
/**
 * 侧边导航（AppShell 子件）：渲染域数组（已按角色过滤），沿用现网深色侧栏配色。
 * badge/hidden 语义见 shared/navigation/types.js（计数未接端点前不下发）。
 */
defineProps({
  navigation: { type: Array, default: () => [] },
  activePath: { type: String, default: '' },
  collapsed: { type: Boolean, default: false },
})
</script>

<style scoped>
.menu-group { color: #5a6d82; font-size: 12px; padding: 12px 20px 4px; }
</style>
