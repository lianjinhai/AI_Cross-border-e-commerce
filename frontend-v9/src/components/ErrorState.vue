<template>
  <el-alert type="error" :closable="false" show-icon :title="message">
    <div v-if="traceId" class="error-state__trace">trace_id: {{ traceId }}</div>
    <div class="error-state__actions">
      <el-button type="danger" size="small" @click="$emit('retry')">重试</el-button>
    </div>
  </el-alert>
</template>

<script setup>
/**
 * 错误态（V9 第 1 批，设计系统 §2）：持久化内联错误提示，**不用瞬时 toast 替代**。
 * `traceId` 有值时展示 trace_id 便于排查；重试统一走 emit('retry')，
 * 错误数据来自 shared/api/errors.js 的 normalizeError。
 */
defineProps({
  message: { type: String, required: true },
  traceId: { type: String, default: '' },
})

defineEmits(['retry'])
</script>

<style scoped>
.error-state__trace {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  word-break: break-all;
}
.error-state__actions {
  margin-top: 8px;
}
</style>
