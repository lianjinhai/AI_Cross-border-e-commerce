<template>
  <el-breadcrumb separator="/">
    <el-breadcrumb-item v-for="(item, index) in items" :key="index" :to="item.to">
      {{ item.label }}
    </el-breadcrumb-item>
  </el-breadcrumb>
</template>

<script setup>
/**
 * 面包屑（UX-02）：items 为 `{label, to?}` 数组；有 `to` 的项可点击跳转，
 * 无 `to` 的项渲染为纯文本（Element Plus 在 `to` 缺省时不产生链接）。
 */
defineProps({
  items: { type: Array, default: () => [] },
})
</script>
