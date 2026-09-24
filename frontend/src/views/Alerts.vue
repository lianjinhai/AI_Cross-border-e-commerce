<template>
  <div class="page">
    <el-row :gutter="16" class="mb16">
      <el-col :span="6">
        <el-card class="kpi-card" shadow="hover">
          <div class="kpi-label">高风险告警</div>
          <div class="kpi-value" style="color:#F56C6C">{{ counts.high || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="kpi-card" shadow="hover">
          <div class="kpi-label">中风险告警</div>
          <div class="kpi-value" style="color:#E6A23C">{{ counts.mid || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="kpi-card" shadow="hover">
          <div class="kpi-label">低风险告警</div>
          <div class="kpi-value" style="color:#909399">{{ counts.low || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="kpi-card" shadow="hover">
          <div class="kpi-label">待处理</div>
          <div class="kpi-value" style="color:#409EFF">{{ counts.open || 0 }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="mb16">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>经营风险告警（AI 主动巡检 · 只告警不执行）</span>
          <div style="display:flex;gap:8px;align-items:center">
            <el-select v-model="filterLevel" size="small" style="width:110px" @change="load">
              <el-option label="全部级别" value="" />
              <el-option label="高" value="high" />
              <el-option label="中" value="mid" />
              <el-option label="低" value="low" />
            </el-select>
            <el-select v-model="filterStatus" size="small" style="width:110px" @change="load">
              <el-option label="全部状态" value="" />
              <el-option label="待处理" value="open" />
              <el-option label="已确认" value="acked" />
            </el-select>
            <el-button v-if="writable" type="primary" size="small" :loading="scanning" @click="scan">
              立即巡检
            </el-button>
          </div>
        </div>
      </template>
      <el-table :data="items" size="small" v-loading="loading" empty-text="暂无告警">
        <el-table-column label="级别" width="80">
          <template #default="{ row }"><run-status :status="row.level" /></template>
        </el-table-column>
        <el-table-column prop="title" label="告警" min-width="220" show-overflow-tooltip />
        <el-table-column prop="detail" label="详情" min-width="320" show-overflow-tooltip />
        <el-table-column prop="rule_key" label="规则" width="150" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'open' ? 'warning' : 'info'" size="small">
              {{ row.status === 'open' ? '待处理' : '已确认' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button v-if="writable && row.status === 'open'" size="small" @click="ack(row)">
              确认
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card>
      <template #header>巡检规则配置（阈值可调、可单独启停）</template>
      <el-table :data="rules" size="small" v-loading="loadingRules" empty-text="暂无规则">
        <el-table-column prop="name" label="规则" min-width="150" />
        <el-table-column prop="key" label="标识" width="150" />
        <el-table-column label="级别" width="130">
          <template #default="{ row }">
            <el-select v-if="writable" v-model="row.level" size="small" @change="saveRule(row)">
              <el-option label="高" value="high" />
              <el-option label="中" value="mid" />
              <el-option label="低" value="low" />
            </el-select>
            <run-status v-else :status="row.level" />
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" :disabled="!writable" @change="saveRule(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="240" show-overflow-tooltip />
        <el-table-column label="当前阈值" min-width="200">
          <template #default="{ row }">
            <span style="font-size:12px;color:#606266">{{ formatThreshold(row.threshold) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
import { canWrite, can } from '../permissions'
import RunStatus from './RunStatus.vue'

const items = ref([])
const rules = ref([])
const counts = ref({})
const loading = ref(false)
const loadingRules = ref(false)
const scanning = ref(false)
const filterLevel = ref('')
const filterStatus = ref('open')
const writable = can('ai:write')

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/alerts', {
      params: { level: filterLevel.value, status: filterStatus.value },
    })
    items.value = data.items || []
    counts.value = data.counts || {}
  } finally {
    loading.value = false
  }
}

async function loadRules() {
  loadingRules.value = true
  try {
    const { data } = await api.get('/alerts/rules')
    rules.value = data.items || []
  } finally {
    loadingRules.value = false
  }
}

async function scan() {
  scanning.value = true
  try {
    const { data } = await api.post('/alerts/scan')
    ElMessage.success(`巡检完成：新增 ${data.created} 条，去重跳过 ${data.skipped} 条`)
    await load()
  } finally {
    scanning.value = false
  }
}

async function ack(row) {
  await api.put(`/alerts/${row.id}/ack`)
  ElMessage.success('已确认（保留审计痕迹，不删除）')
  await load()
}

async function saveRule(row) {
  try {
    await api.put(`/alerts/rules/${row.id}`, { enabled: row.enabled, level: row.level })
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
