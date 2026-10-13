<template>
  <div class="state-wrapper">
    <el-skeleton v-if="state === 'loading'" :rows="4" animated />

    <slot v-else-if="state === 'empty'" name="empty">
      <EmptyState :reason="emptyReason || 'NO_DATA'" :hint="emptyHint" />
    </slot>

    <EmptyState v-else-if="state === 'nopermission'" reason="NO_PERMISSION" />

    <slot v-else-if="state === 'error'" name="error">
      <ErrorState :message="error" :trace-id="traceId" :on-retry="onRetry" />
    </slot>

    <slot v-else />
  </div>
</template>

<script setup>
/**
 * 状态包装器（UX-01）：统一 10 态模型中的可复用子集
 * （loading / empty / error / nopermission / ready），减少各页手写 v-loading / el-empty。
 * empty 与 error 支持 `#empty` / `#error` 具名插槽覆盖默认渲染。
 */
import EmptyState from './EmptyState.vue'
import ErrorState from './ErrorState.vue'

defineProps({
  state: { type: String, default: 'ready' },
  error: { type: String, default: '' },
  traceId: { type: String, default: '' },
  emptyReason: { type: String, default: '' },
  emptyHint: { type: String, default: '' },
  onRetry: { type: Function, default: null },
})
</script>
