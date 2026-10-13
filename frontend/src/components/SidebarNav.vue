<template>
  <el-menu
    :default-active="activePath"
    router
    background-color="#1f2d3d"
    text-color="#bfcbd9"
    active-text-color="#409EFF"
    style="border-right:none"
  >
    <template v-for="domain in domains" :key="domain.key">
      <div class="menu-group">{{ domain.label }}</div>
      <el-menu-item v-for="item in domain.children" :key="item.path" :index="item.path">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </el-menu-item>
    </template>
  </el-menu>
</template>

<script setup>
/**
 * 侧边导航（UX-02）：按 11 域渲染一级 IA。
 * 沿用现网深色侧栏配色（背景 #1f2d3d / 文本 #bfcbd9 / 高亮 #409EFF），
 * 仅把「5 组类目」替换为「11 域经营活动」结构，视觉语言不变。
 */
defineProps({
  domains: { type: Array, default: () => [] },
  activePath: { type: String, default: '' },
})
</script>

<style scoped>
.menu-group { color: #5a6d82; font-size: 12px; padding: 12px 20px 4px; }
</style>
