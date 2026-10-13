<template>
  <el-card shadow="never" class="summary">
    <div class="grid">
      <div class="cell">
        <div class="label">执行状态</div>
        <div class="value">
          <el-tag :type="executionStatusMeta(launch.execution_status).tag">
            {{ executionStatusMeta(launch.execution_status).text }}
          </el-tag>
          <span class="muted">完成 {{ progressText(launch.progress) }}</span>
        </div>
      </div>
      <div class="cell">
        <div class="label">平台状态</div>
        <div class="value">
          <el-tag :type="platformStatusMeta(launch.platform_status).tag">
            {{ platformStatusMeta(launch.platform_status).text }}
          </el-tag>
        </div>
      </div>
      <div class="cell">
        <div class="label">验证状态</div>
        <div class="value">
          <el-tag :type="verificationTag(launch.verification_status).tag">
            {{ verificationTag(launch.verification_status).text }}
          </el-tag>
        </div>
      </div>
    </div>

    <div v-if="guided" class="guided">{{ guidedText }}</div>

    <el-alert v-if="integrationBlock" type="warning" :closable="false" show-icon class="mt8"
      title="整改阻断（已完成历史记录保留，不因整改擦除）" />
    <el-alert v-else-if="blockers.length" type="warning" :closable="false" show-icon class="mt8"
      :title="`阻断 ${blockers.length} 项：${blockers[0].message || blockers[0].code}`" />

    <el-alert v-if="launch.verification_notice" type="info" :closable="false" show-icon class="mt8"
      :title="launch.verification_notice" />
    <el-alert v-if="monitoring" type="info" :closable="false" class="mt8"
      :title="`经营监控：${monitoringStatus}`" :description="monitoring.reason" />
  </el-card>
</template>

<script setup>
import { computed } from 'vue'
import { executionStatusMeta, guidedSummary, platformStatusMeta, progressText } from '../composables/launchCenter'

const props = defineProps({
  launch: { type: Object, default: () => ({}) },
  guided: { type: Boolean, default: true },
})

const VERIFICATION = {
  UNKNOWN: { text: '未知', tag: 'info' },
  UNVERIFIED: { text: '未核验', tag: 'warning' },
  VERIFIED: { text: '已核验', tag: 'success' },
}
const verificationTag = (value) => VERIFICATION[value] || { text: value || '未知', tag: 'info' }

const blockers = computed(() => props.launch.blocked_summary || [])
const integrationBlock = computed(() => props.launch.execution_status === 'COMPLETED' && blockers.value.length > 0)
const guidedText = computed(() => guidedSummary(props.launch))
const monitoring = computed(() => props.launch.monitoring || null)
const monitoringStatus = computed(() => (monitoring.value?.status === 'UNAVAILABLE' ? '未接入' : monitoring.value?.status))
</script>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.label { color: #909399; font-size: 12px; margin-bottom: 6px; }
.value { display: flex; align-items: center; gap: 8px; }
.muted { color: #909399; font-size: 12px; }
.guided { margin-top: 12px; color: #303133; }
.mt8 { margin-top: 8px; }
</style>
