<template>
  <el-card class="kpi-card metric-card" shadow="hover">
    <div class="kpi-label">{{ label }}</div>
    <el-skeleton v-if="loading" :rows="1" animated />
    <div v-else class="kpi-value" :style="{ color }">{{ displayValue }}</div>
    <div v-if="trend" class="metric-card__trend">{{ trend }}</div>
  </el-card>
</template>

<script setup>
/**
 * 指标卡（UX-04a）：收敛现网 `.kpi-card` 内联写法，统一 label/value(+loading/trend)。
 * 复用全局 `.kpi-card` 样式（见 frontend/src/styles.css），仅补趋势脚注与加载占位。
 */
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '—' },
  trend: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  color: { type: String, default: 'var(--color-text)' },
})

const displayValue = computed(() => {
  const v = props.value
  return v === null || v === undefined || v === '' ? '—' : v
})
</script>

<style scoped>
.metric-card__trend {
  margin-top: 6px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}
</style>
