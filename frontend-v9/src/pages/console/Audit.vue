<template>
  <div class="page">
    <PageHeader title="访问审计" subtitle="代客访问 · AI 调用（全平台）">
      <template #actions>
        <el-button size="small" @click="loadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-card class="mb16" shadow="never">
      <template #header><span class="card-title">代客访问审计</span></template>
      <el-table :data="logs" v-loading="logsLoading" size="small">
        <el-table-column prop="operator_name" label="操作人" min-width="120" />
        <el-table-column prop="tenant_id" label="租户 ID" width="100" />
        <el-table-column prop="action" label="操作" min-width="180" />
        <el-table-column prop="created_at" label="时间" min-width="170" />
        <template #empty><EmptyState reason="NO_DATA" hint="暂无代客访问记录" /></template>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header><span class="card-title">AI 调用日志（全平台）</span></template>
      <el-table :data="aiLogs" v-loading="aiLogsLoading" size="small" max-height="420">
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column prop="tenant_id" label="租户" width="70" />
        <el-table-column prop="agent" label="Agent" width="110" />
        <el-table-column prop="action" label="动作" width="140" />
        <el-table-column label="模式" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.mode === 'llm' ? 'success' : 'info'">{{ row.mode }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="70">
          <template #default="{ row }">
            <el-tag size="small" :type="row.ok ? 'success' : 'danger'">{{ row.ok ? 'OK' : 'FAIL' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="latency_ms" label="耗时ms" width="90" />
        <el-table-column prop="response" label="响应摘要" show-overflow-tooltip />
        <template #empty><EmptyState reason="NO_DATA" hint="暂无 AI 调用记录" /></template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
/**
 * 访问审计（UX-E，旧 /platform-admin?tab=audit 语义独立成页，302 表 #28）：
 * 代客访问审计 + 全平台 AI 调用日志（prompt 不出后端，前端不请求）。
 */
import { onMounted, ref } from 'vue'
import PageHeader from '../../components/PageHeader.vue'
import EmptyState from '../../components/EmptyState.vue'
import { fetchAccessLogs, fetchAiLogs } from '../../api/domains/admin'
import { normalizeList } from '../../composables/tenantAdmin'

const logs = ref([])
const logsLoading = ref(false)
const aiLogs = ref([])
const aiLogsLoading = ref(false)

async function loadLogs() {
  logsLoading.value = true
  try { logs.value = normalizeList(await fetchAccessLogs()).items }
  finally { logsLoading.value = false }
}

async function loadAiLogs() {
  aiLogsLoading.value = true
  try { aiLogs.value = normalizeList(await fetchAiLogs({ limit: 100 })).items }
  finally { aiLogsLoading.value = false }
}

function loadAll() {
  loadLogs()
  loadAiLogs()
}

onMounted(loadAll)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.card-title { font-weight: 600; }
</style>
