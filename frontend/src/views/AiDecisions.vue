<template>
  <div class="page">
    <el-card class="mb16">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>AI 决策依据链（只增不删 · 可追溯「为什么这么判」）</span>
          <div style="display:flex;gap:8px">
            <el-select v-model="filterAgent" size="small" style="width:130px" @change="load">
              <el-option label="全部 Agent" value="" />
              <el-option label="选品 discovery" value="discovery" />
              <el-option label="定价 pricing" value="pricing" />
              <el-option label="Listing listing" value="listing" />
            </el-select>
            <el-input v-model="filterSubjectType" size="small" style="width:150px"
              placeholder="对象类型，如 product" @keyup.enter="load" />
            <el-button size="small" @click="load">查询</el-button>
          </div>
        </div>
      </template>
      <el-alert type="info" :closable="false" class="mb16"
        title="每条决策都记录：用了哪些数据（引用而非快照）、走的是 LLM 还是规则引擎、判定结果是什么。用于复盘与合规审计。" />
      <el-table :data="items" size="small" v-loading="loading" empty-text="暂无决策记录"
        @row-click="open" style="cursor:pointer">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="agent" label="Agent" width="110" />
        <el-table-column prop="action" label="动作" width="150" />
        <el-table-column label="对象" width="140">
          <template #default="{ row }">{{ row.subject_type }} #{{ row.subject_id }}</template>
        </el-table-column>
        <el-table-column label="判定结果" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ brief(row.decision) }}</template>
        </el-table-column>
        <el-table-column label="模型" width="90">
          <template #default="{ row }">
            <el-tag :type="row.model === 'llm' ? 'success' : 'info'" size="small">
              {{ row.model === 'llm' ? '大模型' : '规则' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="160" />
      </el-table>
    </el-card>

    <el-drawer v-model="drawer" title="决策依据详情" size="560px">
      <template v-if="current.id">
        <el-descriptions :column="2" border size="small" class="mb16">
          <el-descriptions-item label="Agent">{{ current.agent }}</el-descriptions-item>
          <el-descriptions-item label="动作">{{ current.action }}</el-descriptions-item>
          <el-descriptions-item label="对象">{{ current.subject_type }} #{{ current.subject_id }}</el-descriptions-item>
          <el-descriptions-item label="模型">{{ current.model }}</el-descriptions-item>
        </el-descriptions>
        <h4>判定结果</h4>
        <pre class="json-box">{{ pretty(current.decision) }}</pre>
        <h4>依据链（数据引用）</h4>
        <pre class="json-box">{{ pretty(current.evidence) }}</pre>
        <el-alert v-if="reasons.length" type="success" :closable="false" title="判定理由">
          <ul style="margin:6px 0 0;padding-left:18px">
            <li v-for="(r, i) in reasons" :key="i">{{ r }}</li>
          </ul>
        </el-alert>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import api from '../api'

const items = ref([])
const loading = ref(false)
const drawer = ref(false)
const current = ref({})
const filterAgent = ref('')
const filterSubjectType = ref('')

const reasons = computed(() => {
  const r = current.value?.evidence?.reasons
  return Array.isArray(r) ? r : []
})

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/ai/decisions', {
      params: {
        agent: filterAgent.value,
        subject_type: filterSubjectType.value.trim(),
        limit: 100,
      },
    })
    items.value = data.items || []
  } finally {
    loading.value = false
  }
}

function open(row) {
  current.value = row
  drawer.value = true
}

function brief(decision) {
  const entries = Object.entries(decision || {})
  if (!entries.length) return '—'
  return entries.map(([k, v]) => `${k}=${v}`).join('，')
}

function pretty(obj) {
  try { return JSON.stringify(obj ?? {}, null, 2) } catch { return String(obj) }
}

onMounted(load)
</script>

<style scoped>
.json-box {
  background: #f5f7fa; border-radius: 4px; padding: 10px;
  font-size: 12px; line-height: 1.6; max-height: 260px; overflow: auto;
  white-space: pre-wrap; word-break: break-all;
}
</style>
