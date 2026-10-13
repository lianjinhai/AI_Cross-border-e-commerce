<template>
  <el-skeleton v-if="type === 'cards'" :rows="3" animated />
  <el-skeleton v-else-if="type === 'chart'" :rows="6" animated />
  <el-skeleton v-else :rows="8" animated />
</template>

<script setup>
/**
 * 加载态骨架（V9 第 1 批，设计系统 §2 新增）：统一 loading 呈现，
 * type：'table'（默认，多行骨架）| 'cards' | 'chart'。
 */
defineProps({
  type: { type: String, default: 'table' },
})
</script>
