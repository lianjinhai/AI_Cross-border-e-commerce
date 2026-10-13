<template>
  <el-card class="risk-card" shadow="hover" :class="`risk-card--${alert.level}`">
    <div class="risk-card__head">
      <StatusBadge :status="alert.level" />
      <el-tag v-if="alert.status === 'open'" type="warning" size="small">待处理</el-tag>
      <el-tag v-else type="info" size="small">已确认</el-tag>
      <span class="risk-card__time">{{ alert.created_at }}</span>
    </div>
    <div class="risk-card__title">{{ alert.title }}</div>
    <div class="risk-card__detail">{{ alert.detail }}</div>
    <div class="risk-card__rule">
      <el-tag size="small" type="info" effect="plain">{{ alert.rule_key }}</el-tag>
    </div>
    <div class="risk-card__actions">
      <!-- 深链由 features/optimization/alertTargets.js 解析；无映射不渲染入口 -->
      <el-button v-if="target" size="small" type="primary" plain @click="goHandle">
        {{ target.label }}
      </el-button>
      <el-button
        v-if="writable && alert.status === 'open'"
        size="small"
        @click="$emit('ack', alert)"
      >
        确认
      </el-button>
    </div>
  </el-card>
</template>

<script setup>
/**
 * 风险告警卡（V9 第 3 批组件）：级别徽标 + 明细 + 「去处理」深链 + 确认。
 * 深链目标由页面经 alertTarget(rule_key) 解析后传入；无映射则不渲染按钮
 * （告警无处置是 V1.0 审计断链，V9 逐条消除）。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import StatusBadge from './StatusBadge.vue'

const props = defineProps({
  alert: { type: Object, required: true },
  // {path, label} | null；由 alertTarget() 产出。
  target: { type: Object, default: null },
  writable: { type: Boolean, default: false },
})

defineEmits(['ack'])

const router = useRouter()
const target = computed(() => props.target)

function goHandle() {
  if (target.value?.path) router.push(target.value.path)
}
</script>

<style scoped>
.risk-card__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.risk-card__time {
  margin-left: auto;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}
.risk-card__title {
  margin-top: var(--space-2);
  font-weight: var(--font-weight-medium);
}
.risk-card__detail {
  margin-top: var(--space-1);
  color: var(--color-text-regular);
  font-size: var(--font-size-sm);
  min-height: 20px;
}
.risk-card__rule {
  margin-top: var(--space-2);
}
.risk-card__actions {
  margin-top: var(--space-2);
  display: flex;
  gap: var(--space-2);
}
.risk-card--high {
  border-top: 2px solid var(--color-danger);
}
.risk-card--mid {
  border-top: 2px solid var(--color-warning);
}
.risk-card--low {
  border-top: 2px solid var(--color-info);
}
</style>
