<template>
  <el-card class="kpi-card metric-card" shadow="hover">
    <div class="kpi-label">
      {{ label }}
      <el-tooltip v-if="caliber" :content="caliber" placement="top">
        <el-icon class="metric-card__caliber"><InfoFilled /></el-icon>
      </el-tooltip>
    </div>
    <el-skeleton v-if="loading" :rows="1" animated />
    <div v-else class="kpi-value" :style="{ color }">{{ displayValue }}</div>
    <div v-if="trend" class="metric-card__trend">{{ trend }}</div>
    <div v-if="$slots.chart" class="metric-card__chart">
      <slot name="chart" />
    </div>
  </el-card>
</template>

<script setup>
/**
 * 指标卡（V9 第 1 批，设计系统 §2）：值+趋势+口径说明（承接 BI 口径展开需求）。
 * partial 数据源口径缺失时 value 传 null/''，卡片按「—」呈现，绝不伪造数值。
 */
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '—' },
  trend: { type: String, default: '' },
  // 口径说明（tooltip 悬浮展示，来自 bi/metrics 的口径字段）。
  caliber: { type: String, default: '' },
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
.metric-card__caliber {
  color: var(--color-text-secondary);
  vertical-align: -2px;
  margin-left: 2px;
}
.metric-card__chart {
  margin-top: 8px;
}
</style>
