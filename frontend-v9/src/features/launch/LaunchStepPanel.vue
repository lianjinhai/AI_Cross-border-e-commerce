<template>
  <el-card shadow="never" class="panel">
    <template v-if="step">
      <div class="head">
        <span class="name">{{ step.step_name || step.step_code }}</span>
        <el-tag size="small" :type="executionStatusMeta(step.step_status).tag">
          {{ executionStatusMeta(step.step_status).text }}
        </el-tag>
      </div>

      <el-descriptions :column="1" border size="small" class="mt8">
        <el-descriptions-item label="说明">
          {{ step.business_type }} · {{ step.execution_mode }} · 执行者 {{ step.actor || '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="要求（evidence_requirements）">
          {{ evidenceText(step.evidence_requirements) }}
        </el-descriptions-item>
        <el-descriptions-item label="缺项（missing_evidence）">
          <span :class="{ missing: step.missing_evidence?.length }">{{ evidenceText(step.missing_evidence) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="证据（evidence_refs）">
          {{ evidenceText(step.evidence_refs) }}
        </el-descriptions-item>
        <el-descriptions-item label="外部反馈">
          状态 {{ notConnected(external.status) }} · 引用 {{ notConnected(external.reference) }} ·
          类型 {{ notConnected(external.type) }}
        </el-descriptions-item>
        <el-descriptions-item label="责任人">
          {{ step.assigned_user_id == null ? '未指派' : `用户 #${step.assigned_user_id}` }}
        </el-descriptions-item>
      </el-descriptions>

      <div class="sub">执行结果（result）</div>
      <pre class="result">{{ resultText }}</pre>

      <template v-if="professional">
        <div class="sub">专业字段（raw）</div>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item v-for="field in fields" :key="field.label" :label="field.label">
            {{ field.value }}
          </el-descriptions-item>
        </el-descriptions>
      </template>

      <div class="sub">可执行动作</div>
      <div class="actions">
        <div v-for="entry in actions" :key="entry.action" class="action">
          <!-- 不可执行一律 disabled（默认动作按钮语义），权限不足同样不可点；原因旁展示。 -->
          <NextActionButton :action="entry.action" :executable="entry.executable && canManage"
            :reason="entry.disabled_reason" @run="$emit('run', entry)" />
          <!-- NotConfiguredState 语义已并入 EmptyState 家族（V9 设计系统 §2）：未接入能力显式声明 -->
          <el-alert v-if="isNotConnected(entry)" type="info" :closable="false" class="not-connected"
            :title="`${entry.action}：该能力尚未接入`">
            <span class="not-connected__detail">{{ entry.disabled_reason }}</span>
          </el-alert>
        </div>
        <span v-if="!actions.length" class="muted">该步骤无可执行动作</span>
        <span v-if="!canManage" class="muted">只读账号：写操作已隐藏</span>
      </div>
    </template>
    <el-empty v-else description="请选择时间线上的步骤" :image-size="70" />
  </el-card>
</template>

<script setup>
import { computed } from 'vue'
import {
  NOT_CONNECTED, evidenceText, executionStatusMeta, notConnected, professionalFields,
} from '../../composables/launchCenter'
import NextActionButton from './NextActionButton.vue'

const props = defineProps({
  step: { type: Object, default: null },
  professional: { type: Boolean, default: false },
  canManage: { type: Boolean, default: false },
})
defineEmits(['run'])

const external = computed(() => props.step?.external || {})
const actions = computed(() => props.step?.available_actions || [])
const fields = computed(() => professionalFields(props.step || {}))
const resultText = computed(() => {
  const result = props.step?.result
  if (!result || !Object.keys(result).length) return '未接入'
  return JSON.stringify(result, null, 2)
})

/** 原因即「未接入」时，额外显式声明能力缺失（UX-03）。 */
function isNotConnected(entry) {
  const reason = entry?.disabled_reason
  return typeof reason === 'string' && reason.includes(NOT_CONNECTED)
}
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.name { font-weight: 600; }
.mt8 { margin-top: 8px; }
.sub { font-weight: 600; margin: 12px 0 6px; }
.result { background: #f5f7fa; border-radius: 4px; padding: 8px; font-size: 12px;
  max-height: 160px; overflow: auto; margin: 0; white-space: pre-wrap; word-break: break-all; }
.actions { display: flex; flex-direction: column; gap: 6px; }
.action { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.missing { color: var(--color-warning); }
.muted { color: var(--color-text-disabled); font-size: 12px; }
.not-connected { margin-top: 4px; }
.not-connected__detail { font-size: 12px; }
</style>
