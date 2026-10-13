<template>
  <div class="section-state">
    <LoadingState v-if="state === 'loading'" :type="loadingType" />

    <slot v-else-if="state === 'empty'" name="empty">
      <EmptyState :reason="emptyReason || 'NO_DATA'" :hint="emptyHint" />
    </slot>

    <EmptyState v-else-if="state === 'nopermission'" reason="NO_PERMISSION" />

    <slot v-else-if="state === 'error'" name="error">
      <ErrorState :message="error" :trace-id="traceId" @retry="$emit('retry')" />
    </slot>

    <slot v-else />
  </div>
</template>

<script setup>
/**
 * 区块状态包装（UX-C 内部件）：统一 10 态模型中的可复用子集
 * （loading / empty / error / nopermission / ready），由 EmptyState 家族组合而成；
 * empty 与 error 支持 `#empty` / `#error` 具名插槽覆盖默认渲染。
 */
import EmptyState from './EmptyState.vue'
import ErrorState from './ErrorState.vue'
import LoadingState from './LoadingState.vue'

defineProps({
  state: { type: String, default: 'ready' },
  error: { type: String, default: '' },
  traceId: { type: String, default: '' },
  emptyReason: { type: String, default: '' },
  emptyHint: { type: String, default: '' },
  loadingType: { type: String, default: 'table' },
})

defineEmits(['retry'])
</script>
