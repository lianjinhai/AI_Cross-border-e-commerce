<template>
  <el-alert type="error" :closable="false" show-icon :title="message">
    <div v-if="traceId" class="error-state__trace">trace_id: {{ traceId }}</div>
    <div v-if="onRetry" class="error-state__actions">
      <el-button type="danger" size="small" @click="onRetry">重试</el-button>
    </div>
  </el-alert>
</template>

<script setup>
/**
 * 错误态（UX-01）：持久化内联错误提示，**不用瞬时 toast 替代**。
 * `traceId` 有值时在描述区展示 trace_id 便于排查；`onRetry` 有值时内联「重试」按钮。
 */
defineProps({
  message: { type: String, required: true },
  traceId: { type: String, default: '' },
  onRetry: { type: Function, default: null },
})
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
