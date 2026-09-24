<template>
  <div class="page">
    <el-row :gutter="16" class="mb16">
      <el-col :span="8" v-for="t in templates" :key="t.key">
        <el-card shadow="hover">
          <h4 style="margin:0 0 6px">{{ icon(t.key) }} {{ t.name }}</h4>
          <p style="color:#909399;font-size:12px;min-height:36px">{{ t.description }}</p>
          <div class="pipeline">
            <template v-for="(s, i) in t.steps" :key="i">
              <el-tag size="small" type="info" effect="plain">{{ agentLabel[s.agent] || s.agent }}</el-tag>
              <span v-if="i < t.steps.length - 1" class="arrow">→</span>
            </template>
          </div>
          <el-button v-if="write" type="primary" size="small" style="width:100%;margin-top:10px"
            :loading="running === t.key" @click="run(t)">运行</el-button>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="mb16">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>⏰ 自主经营调度（定时自动执行）</span>
          <el-button v-if="write" type="primary" size="small" @click="schedDialog = true">新建调度</el-button>
        </div>
      </template>
      <el-table :data="schedules" size="small">
        <el-table-column prop="name" label="任务" min-width="160" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.kind === 'workflow' ? 'primary' : 'info'">
              {{ kindLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="频率" width="110">
          <template #default="{ row }">{{ freqLabel(row.interval_minutes) }}</template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" :disabled="!write" @change="(v) => toggleSchedule(row, v)" />
          </template>
        </el-table-column>
        <el-table-column prop="run_count" label="已执行" width="80" />
        <el-table-column prop="last_run_at" label="上次执行" width="160" />
        <el-table-column label="上次结果" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.last_status" size="small"
              :type="row.last_status === 'success' ? 'success' : row.last_status === 'failed' ? 'danger' : 'warning'">
              {{ { success: '成功', partial: '部分成功', blocked: '等待人工', failed: '失败', running: '运行中', queued: '排队中' }[row.last_status] || row.last_status }}
            </el-tag>
            <span v-else style="color:#c0c4cc">未执行</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button v-if="can('ai:write')" size="small" type="success" :loading="runningSched === row.id" @click="runSchedule(row)">立即执行</el-button>
            <el-button v-if="can('ai:write')" size="small" type="danger" @click="removeSchedule(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-alert type="info" :closable="false" style="margin-top:10px"
        title="启用的任务由后台调度器自动执行（每 30 秒检查一次到期任务），执行记录可在「运行历史」与 AI 调用日志中查看。" />
    </el-card>

    <el-card>
      <template #header>运行历史</template>
      <el-table :data="runs" v-loading="loading" size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="工作流" width="160" />
        <el-table-column label="状态" width="90"><template #default="{ row }"><run-status :status="row.status" /></template></el-table-column>
        <el-table-column prop="created_at" label="开始时间" width="160" />
        <el-table-column prop="finished_at" label="结束时间" width="160" />
        <el-table-column prop="error" label="错误" show-overflow-tooltip />
        <el-table-column label="操作" width="150">
          <template #default="{ row }"><el-button size="small" @click="showRun(row)">详情</el-button><el-button v-if="write && ['failed','blocked','partial'].includes(row.status)" link type="warning" :loading="resuming===row.id" @click="resume(row)">恢复</el-button></template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="drawer" :title="`工作流运行 #${current.id || ''}`" size="640px">
      <template v-if="current.id">
        <el-alert v-if="current.error" type="error" :title="current.error" :closable="false" style="margin-bottom:12px" />
        <el-steps :active="activeStep" direction="vertical" :process-status="'process'"
          :finish-status="'success'" style="height:560px">
          <el-step v-for="s in current.steps" :key="s.seq"
            :title="`${s.agent}.${s.action}`"
            :status="stepStatus(s.status)"
            :description="stepDesc(s)" />
        </el-steps>
      </template>
    </el-drawer>

    <el-dialog v-model="schedDialog" title="新建调度任务" width="520px">
      <el-form label-width="100px">
        <el-form-item label="任务名称"><el-input v-model="schedForm.name" placeholder="如：每天早8点扫趋势" /></el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="schedForm.kind" @change="schedForm.workflow_key = ''">
            <el-option label="工作流" value="workflow" />
            <el-option label="趋势扫描" value="trend_scan" />
            <el-option label="主动巡检" value="alert_scan" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="schedForm.kind === 'workflow'" label="工作流">
          <el-select v-model="schedForm.workflow_key" style="width:100%">
            <el-option v-for="t in templates" :key="t.key" :label="t.name" :value="t.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="执行频率">
          <el-select v-model="schedForm.interval_minutes" style="width:100%">
            <el-option v-for="opt in freqOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="schedDialog = false">取消</el-button>
        <el-button type="primary" @click="createSchedule">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
import RunStatus from './RunStatus.vue'
import { canWrite, can } from '../permissions'

const templates = ref([])
const runs = ref([])
const loading = ref(false)
const write = can('ai:write')
const resuming = ref(null)
const running = ref('')
const drawer = ref(false)
const current = ref({})
const pollTimer = ref(null)
const agentLabel = { discovery: '市场发现', product: '商品分析', supplier: '供应链',
  compliance: '合规', listing: 'Listing', pricing: '定价', ads: '广告' }
const schedules = ref([])
const schedDialog = ref(false)
const runningSched = ref(null)
const schedForm = ref({ name: '', kind: 'workflow', workflow_key: 'auto_listing', interval_minutes: 1440 })
const freqOptions = [
  { label: '每 30 分钟', value: 30 }, { label: '每 1 小时', value: 60 },
  { label: '每 6 小时', value: 360 }, { label: '每天一次', value: 1440 },
  { label: '每周一次', value: 10080 },
]

const activeStep = computed(() => {
  const idx = (current.value.steps || []).findIndex((s) => s.status !== 'success')
  return idx === -1 ? (current.value.steps || []).length : idx
})

function icon(key) {
  return { auto_listing: '🚀', reprice: '💰', restock: '📦' }[key] || '⚡'
}

function stepStatus(status) {
  return { success: 'success', running: 'process', failed: 'error', blocked: 'error', pending: 'wait', skipped: 'wait' }[status] || 'wait'
}

function stepDesc(s) {
  if (s.error) return `错误：${s.error}`
  if (!s.output || !Object.keys(s.output).length) return s.status
  const keys = Object.keys(s.output).filter((k) => k !== 'context_patch')
  const k = keys[0]
  const v = s.output[k]
  const summary = Array.isArray(v) ? `${k}: ${v.length} 条` : typeof v === 'object' ? `${k}: ${JSON.stringify(v).slice(0, 120)}` : `${k}: ${v}`
  return summary.slice(0, 150)
}

async function load() {
  loading.value = true
  try {
    const [t, r, s] = await Promise.all([api.get('/workflows/templates'), api.get('/workflows/runs'),
      api.get('/schedules')])
    templates.value = t.data.items
    runs.value = r.data.items
    schedules.value = s.data.items
  } finally { loading.value = false }
}

function freqLabel(minutes) {
  if (minutes % 10080 === 0 && minutes >= 10080) return `每 ${minutes / 10080} 周`
  if (minutes % 1440 === 0 && minutes >= 1440) return `每 ${minutes / 1440} 天`
  if (minutes % 60 === 0) return `每 ${minutes / 60} 小时`
  return `每 ${minutes} 分钟`
}

/** 任务类型标签：三种 kind 各自可读（此前只判断 workflow，其余一律显示"趋势扫描"）。 */
function kindLabel(row) {
  if (row.kind === 'workflow') return `工作流·${row.workflow_key}`
  if (row.kind === 'alert_scan') return '主动巡检'
  if (row.kind === 'trend_scan') return '趋势扫描'
  return row.kind
}

async function toggleSchedule(row, v) {
  await api.put(`/schedules/${row.id}`, { enabled: v })
  ElMessage.success(v ? '已启用，到期将自动执行' : '已停用')
}

async function runSchedule(row) {
  runningSched.value = row.id
  try {
    const { data } = await api.post(`/schedules/${row.id}/run`)
    ElMessage.success(data.ok ? `执行成功（${data.detail}）` : `执行失败：${data.detail}`)
    load()
  } finally { runningSched.value = null }
}

async function removeSchedule(row) {
  await api.delete(`/schedules/${row.id}`)
  ElMessage.success('已删除')
  load()
}

async function createSchedule() {
  if (!schedForm.value.name.trim()) return ElMessage.warning('请填写任务名称')
  await api.post('/schedules', schedForm.value)
  ElMessage.success('调度任务已创建')
  schedDialog.value = false
  load()
}

async function run(t) {
  running.value = t.key
  try {
    const { data } = await api.post('/workflows/run', { template_key: t.key, context: {} })
    ElMessage.info(`「${t.name}」已提交，最终结果以运行状态为准`)
    load()
    showRun(data)
  } finally { running.value = '' }
}

async function resume(row) {
  resuming.value = row.id
  try { await api.post(`/workflows/runs/${row.id}/resume`); ElMessage.success('已从安全检查点恢复执行'); await load() }
  finally { resuming.value = null }
}

async function showRun(row) {
  const { data } = await api.get(`/workflows/runs/${row.id}`)
  current.value = data
  drawer.value = true
  clearInterval(pollTimer.value)
  if (data.status === 'running') {
    pollTimer.value = setInterval(async () => {
      const r = await api.get(`/workflows/runs/${row.id}`)
      current.value = r.data
      if (r.data.status !== 'running') {
        clearInterval(pollTimer.value)
        load()
      }
    }, 2000)
  }
}

onUnmounted(() => clearInterval(pollTimer.value))
onMounted(load)
</script>

<style scoped>
.pipeline { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; min-height: 40px; }
.arrow { color: #c0c4cc; }
</style>
