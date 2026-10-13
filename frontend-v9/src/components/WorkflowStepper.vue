<template>
  <el-card shadow="never" class="stepper">
    <el-steps :active="current" :align-center="mode === 'guided'" finish-status="success">
      <el-step
        v-for="(step, i) in steps" :key="step.key"
        :title="step.label"
        :description="mode === 'guided' ? step.hint : ''"
        :status="stepStatus(i)"
        class="stepper__step"
        @click="goto(i)"
      />
    </el-steps>
    <div class="stepper__body">
      <slot name="step-content" :step="steps[current]" :index="current" />
    </div>
    <div class="stepper__nav">
      <el-button size="small" :disabled="current === 0" @click="goto(current - 1)">上一步</el-button>
      <el-button
        v-if="current < steps.length - 1" size="small" type="primary"
        :disabled="!canAdvance" @click="goto(current + 1)"
      >下一步</el-button>
    </div>
  </el-card>
</template>

<script setup>
/**
 * 分步流程骨架（V9 第 2 批，设计系统 §2）：GUIDED 上线/Listing 流/下单向导。
 * LaunchStepPanel 泛化：props steps（{key,label,hint}）、current、mode、canAdvance；
 * 步骤内容由 #step-content 作用域插槽承载（单页分步流，无路由断点）。
 */
import { computed } from 'vue'

const props = defineProps({
  steps: { type: Array, required: true },
  // 支持数字索引或步骤 key；超界回 0。
  current: { type: [Number, String], default: 0 },
  mode: { type: String, default: 'guided' }, // 'guided' | 'professional'
  // 下一步是否放行由调用方按当前步校验给出。
  canAdvance: { type: Boolean, default: true },
})

const emit = defineEmits(['update:current', 'step-change'])

const current = computed(() => {
  const raw = props.current
  if (typeof raw === 'number') return Math.min(Math.max(raw, 0), props.steps.length - 1)
  const i = props.steps.findIndex((s) => s.key === raw)
  return i === -1 ? 0 : i
})

function stepStatus(index) {
  if (index < current.value) return 'success'
  if (index === current.value) return 'process'
  return 'wait'
}

function goto(index) {
  if (index < 0 || index > props.steps.length - 1 || index === current.value) return
  emit('update:current', index)
  emit('step-change', props.steps[index])
}
</script>

<style scoped>
.stepper__step {
  cursor: pointer;
}
.stepper__body {
  margin-top: var(--space-4);
}
.stepper__nav {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
</style>
