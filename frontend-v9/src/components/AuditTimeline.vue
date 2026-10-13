<template>
  <template v-if="steps.length">
    <el-timeline class="audit-timeline">
      <el-timeline-item
        v-for="step in steps"
        :key="step.key"
        :type="typeOf(step.state)"
        :hollow="step.state === 'pending'"
        :timestamp="step.time || undefined"
      >
        <div class="audit-timeline__label">{{ step.label }}</div>
        <div v-if="step.description" class="audit-timeline__desc">{{ step.description }}</div>
      </el-timeline-item>
    </el-timeline>
  </template>
  <EmptyState v-else reason="NO_DATA" hint="暂无状态流转记录" />
</template>

<script setup>
/**
 * 审计时间线（V9 第 3 批组件）：状态机可视化原子，供订单/退款等行展开复用。
 * steps 由各状态机纯函数产出（refundTimeline / orderTimeline），形状：
 * { key, label, description?, time?, state: 'done'|'current'|'pending'|'error' }。
 */
import EmptyState from './EmptyState.vue'

defineProps({
  steps: { type: Array, default: () => [] },
})

function typeOf(state) {
  if (state === 'done') return 'success'
  if (state === 'current') return 'primary'
  if (state === 'error') return 'danger'
  return 'info'
}
</script>

<style scoped>
.audit-timeline {
  padding: var(--space-2) var(--space-2) 0;
}
.audit-timeline__label {
  font-size: var(--font-size-sm);
}
.audit-timeline__desc {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  margin-top: 2px;
}
</style>
