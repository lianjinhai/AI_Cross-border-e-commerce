<template>
  <span class="money-value">
    <span class="money-value__amount">{{ display }}</span>
    <el-tag v-if="tag" :type="tagTone" size="small" effect="plain" class="money-value__tag">{{ tag }}</el-tag>
    <slot name="note" />
  </span>
</template>

<script setup>
/**
 * 金额展示（蓝图 §6.5，包 1 P0 全新组件）。
 *
 * 规则：必显币种 + 汇率基准日 + 估算/已结算标签；缺值不渲染 0（显"—"）；缺 fxDate 显"汇率未知"。
 * 纯函数源：shared/money.js（renderMoney / isMissing / moneyTag）。
 */
import { computed } from 'vue'
import { renderMoney, moneyTag } from '../shared/money'

const props = defineProps({
  /** 金额值（Number|String|null）。 */
  value: { type: [Number, String, null], default: null },
  /** 币种（如 USD/CNY/EUR）。 */
  currency: { type: String, default: '' },
  /** 分析币种（换算目标，与 currency 不同时显示）。 */
  analysisCurrency: { type: String, default: '' },
  /** 汇率基准日（缺=显"汇率未知"）。 */
  fxDate: { type: String, default: '' },
  /** 是否估算。 */
  estimated: { type: Boolean, default: false },
  /** 是否已结算。 */
  settled: { type: Boolean, default: false },
  /** 'unit'|'total'（影响标签文案）。 */
  unit: { type: String, default: '' },
})

const display = computed(() => {
  if (props.value === null || props.value === undefined || props.value === '') return '—'
  const num = Number(props.value)
  if (Number.isNaN(num)) return '—'
  const formatted = num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return `${formatted} ${props.currency}`.trim()
})

const tag = computed(() => moneyTag(props.estimated, props.settled))

const tagTone = computed(() => {
  if (props.estimated) return 'warning'
  if (props.settled) return 'success'
  return 'info'
})
</script>

<style scoped>
.money-value {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.money-value__amount {
  font-variant-numeric: tabular-nums;
}
.money-value__tag {
  font-size: var(--font-size-xs);
}
</style>
