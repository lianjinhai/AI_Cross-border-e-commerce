<template>
  <div class="page">
    <PageHeader title="风险巡检" subtitle="AI 主动巡检（只告警不执行） · 每条告警可「去处理」直达对应域">
      <template #actions>
        <el-select v-model="filterLevel" size="small" style="width: 110px" @change="load">
          <el-option label="全部级别" value="" />
          <el-option label="高" value="high" />
          <el-option label="中" value="mid" />
          <el-option label="低" value="low" />
        </el-select>
        <el-select v-model="filterStatus" size="small" style="width: 110px" @change="load">
          <el-option label="全部状态" value="" />
          <el-option label="待处理" value="open" />
          <el-option label="已确认" value="acked" />
        </el-select>
        <el-button v-if="writable" type="primary" size="small" :loading="scanning" @click="scan">
          立即巡检
        </el-button>
      </template>
    </PageHeader>

    <el-row :gutter="16" class="mb16">
      <el-col :span="6"><MetricCard label="高风险告警" :value="String(counts.high ?? 0)" color="var(--color-danger)" /></el-col>
      <el-col :span="6"><MetricCard label="中风险告警" :value="String(counts.mid ?? 0)" color="var(--color-warning)" /></el-col>
      <el-col :span="6"><MetricCard label="低风险告警" :value="String(counts.low ?? 0)" /></el-col>
      <el-col :span="6"><MetricCard label="待处理" :value="String(counts.open ?? 0)" color="var(--color-primary)" /></el-col>
    </el-row>

    <FormSection title="经营风险告警" description="「去处理」深链到对应域；确认后保留审计痕迹不删除">
      <el-row v-loading="loading" :gutter="16">
        <el-col v-for="a in items" :key="a.id" :span="8" class="risk-col">
          <RiskCard :alert="a" :target="alertTarget(a.rule_key)" :writable="writable" @ack="ack" />
        </el-col>
      </el-row>
      <EmptyState v-if="!items.length && !loading" reason="NO_DATA" hint="暂无告警" />
    </FormSection>

    <FormSection title="巡检规则配置" description="阈值可调、可单独启停；规则与 AI 动作审批（actions）联动由对应功能页消费">
      <el-table v-loading="loadingRules" :data="rules" size="small">
        <el-table-column prop="name" label="规则" min-width="150" />
        <el-table-column prop="key" label="标识" width="150" />
        <el-table-column label="级别" width="120">
          <template #default="{ row }">
            <el-select v-if="writable" v-model="row.level" size="small" @change="saveRule(row)">
              <el-option label="高" value="high" />
              <el-option label="中" value="mid" />
              <el-option label="低" value="low" />
            </el-select>
            <StatusBadge v-else :status="row.level" />
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" :disabled="!writable" @change="saveRule(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
        <el-table-column label="当前阈值" min-width="180">
          <template #default="{ row }">
            <span class="threshold">{{ formatThreshold(row.threshold) }}</span>
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="暂无规则" /></template>
      </el-table>
    </FormSection>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import MetricCard from '../../components/MetricCard.vue'
import RiskCard from '../../components/RiskCard.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import { can } from '../../permissions/permissions'
import {
  fetchAlerts, ackAlert, fetchAlertRules, updateAlertRule, scanAlerts,
} from '../../api/domains/alerts'
import { alertTarget } from '../../features/optimization/alertTargets'

const writable = can('ai:write')

const items = ref([])
const rules = ref([])
const counts = ref({})
const loading = ref(false)
const loadingRules = ref(false)
const scanning = ref(false)
const filterLevel = ref('')
const filterStatus = ref('open')

async function load() {
  loading.value = true
  try {
    const data = await fetchAlerts({ level: filterLevel.value, status: filterStatus.value })
    items.value = data.items || []
    counts.value = data.counts || {}
  } finally {
    loading.value = false
  }
}

async function loadRules() {
  loadingRules.value = true
  try {
    rules.value = (await fetchAlertRules()).items || []
  } finally {
    loadingRules.value = false
  }
}

async function scan() {
  scanning.value = true
  try {
    const data = await scanAlerts()
    ElMessage.success(`巡检完成：新增 ${data.created} 条，去重跳过 ${data.skipped} 条`)
    await load()
  } finally {
    scanning.value = false
  }
}

async function ack(row) {
  await ackAlert(row.id)
  ElMessage.success('已确认（保留审计痕迹，不删除）')
  await load()
}

async function saveRule(row) {
  try {
    await updateAlertRule(row.id, { enabled: row.enabled, level: row.level })
    ElMessage.success('规则已更新')
  } catch {
    await loadRules()
  }
}

function formatThreshold(threshold) {
  const entries = Object.entries(threshold || {})
  if (!entries.length) return '—'
  return entries.map(([k, v]) => `${k}=${v}`).join('，')
}

onMounted(() => { load(); loadRules() })
</script>

<style scoped>
.mb16 {
  margin-bottom: var(--space-4);
}
.risk-col {
  margin-bottom: var(--space-3);
}
.threshold {
  font-size: var(--font-size-xs);
  color: var(--color-text-regular);
}
</style>
