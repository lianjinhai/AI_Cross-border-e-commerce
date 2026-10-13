<template>
  <StatusTag :status="status" />
</template>

<script setup>
/**
 * RunStatus（UX-01 起）改为 StatusTag 的薄封装：
 * 6 个引用页保持 `<RunStatus :status="x" />` 用法不变，props 仍为 `status: String`，
 * 视觉与行为零变化。
 */
import StatusTag from '../components/StatusTag.vue'

defineProps({ status: String })
</script>
