<template>
  <div class="page">
    <PageHeader title="AI 工作流" subtitle="模板运行（带参数说明） · 自主调度 · 运行历史与失败恢复">
      <template #actions>
        <el-button v-if="writable" type="primary" @click="schedDialog = true">新建调度</el-button>
      </template>
    </PageHeader>

    <SectionState :state="listState" :error="error" :trace-id="traceId" @retry="load">
      <!-- 失败/阻塞运行恢复卡片（矩阵 #20：失败运行卡片置顶并给恢复动作） -->
      <FormSection v-if="recoverableRuns.length" title="待恢复运行" description="失败/阻塞/部分成功的运行已置顶，可从安全检查点一键恢复">
        <div class="recover-cards">
          <el-card v-for="r in recoverableRuns" :key="r.id" shadow="never" class="recover-card">
            <div class="recover-head">
              <StatusBadge :status="r.status" />
              <span class="recover-title">运行 #{{ r.id }} · {{ r.name || r.template_key }}</span>
            </div>
            <div class="recover-err">{{ r.error || '（后端未返回错误详情）' }}</div>
            <el-button
              v-if="writable" size="small" type="warning"
              :loading="resuming === r.id" @click="resumeRun(r)"
            >从检查点恢复</el-button>
          </el-card>
        </div>
      </FormSection>

      <!-- 模板运行 -->
      <FormSection title="工作流模板" description="运行向导逐步展示每个 Agent 步骤的参数说明，确认后提交执行">
        <div class="tpl-grid">
          <el-card v-for="t in templates" :key="t.key" shadow="hover" class="tpl-card">
            <h4 class="tpl-name">{{ t.name }}</h4>
            <p class="tpl-desc">{{ t.description }}</p>
            <div class="pipeline">
              <template v-for="(s, i) in t.steps" :key="i">
                <el-tag v-if="i > 0" size="small" type="info" effect="plain">→</el-tag>
                <el-tag size="small" effect="plain">{{ agentLabel(s.agent) }}</el-tag>
              </template>
            </div>
            <el-button
              v-if="writable" type="primary" size="small" class="tpl-run"
              :loading="runningKey === t.key" @click="openWizard(t)"
            >运行</el-button>
          </el-card>
        </div>
      </FormSection>

      <!-- 自主调度 -->
      <FormSection title="自主经营调度" description="到点自动执行工作流/趋势扫描；下次执行时间由「上次执行 + 频率」估算">
        <el-table :data="schedules" size="small">
          <el-table-column prop="name" label="任务" min-width="150" show-overflow-tooltip />
          <el-table-column label="类型" width="150">
            <template #default="{ row }">{{ kindLabel(row) }}</template>
          </el-table-column>
          <el-table-column label="频率" width="100">
            <template #default="{ row }">{{ freqLabel(row.interval_minutes) }}</template>
          </el-table-column>
          <el-table-column label="下次执行（估算）" width="190">
            <template #default="{ row }">
              <span v-if="!row.enabled" class="muted">已停用</span>
              <span v-else>{{ nextRunAt(row).text }}</span>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" :disabled="!writable" @change="(v) => toggleSchedule(row, v)" />
            </template>
          </el-table-column>
          <el-table-column prop="run_count" label="已执行" width="70" />
          <el-table-column label="上次结果" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.last_status" size="small" :type="lastStatusTag(row.last_status)">
                {{ lastStatusLabel(row.last_status) }}
              </el-tag>
              <span v-else class="muted">未执行</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button v-if="writable" size="small" type="success" :loading="triggering === row.id" @click="runSchedule(row)">立即执行</el-button>
              <el-button v-if="writable" size="small" type="danger" plain @click="removeSchedule(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="暂无调度任务" /></template>
        </el-table>
      </FormSection>

      <!-- 运行历史 -->
      <FormSection title="运行历史" description="失败/阻塞运行排在最前；详情抽屉可逐步查看每个 Agent 的执行结果">
        <el-table :data="sortedRuns" v-loading="loading" size="small">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column label="工作流" width="170">
            <template #default="{ row }">{{ row.name || row.template_key }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }"><StatusBadge :status="row.status" /></template>
          </el-table-column>
          <el-table-column prop="created_at" label="开始时间" width="160" />
          <el-table-column prop="finished_at" label="结束时间" width="160" />
          <el-table-column prop="error" label="错误" show-overflow-tooltip />
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="showRun(row)">详情</el-button>
              <el-button
                v-if="writable && isRecoverableRun(row)" link type="warning"
                :loading="resuming === row.id" @click="resumeRun(row)"
              >恢复</el-button>
            </template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="暂无运行记录" /></template>
        </el-table>
      </FormSection>
    </SectionState>

    <!-- 运行向导（WorkflowStepper：说明 → 各步骤参数 → 确认） -->
    <el-dialog v-model="wizardVisible" :title="`运行「${wizardTemplate?.name || ''}」`" width="640px" :close-on-click-modal="false">
      <WorkflowStepper v-model:current="wizardStep" :steps="wizardSteps" :can-advance="true">
        <template #step-content="{ step }">
          <el-alert
            v-if="step.key === 'confirm'" type="warning" :closable="false"
            :title="`将按模板编排提交执行「${wizardTemplate?.name}」；执行结果以运行状态为准，失败可在运行历史恢复。`"
          />
          <el-alert v-else type="info" :closable="false" :title="step.hint" />
        </template>
      </WorkflowStepper>
      <template #footer>
        <el-button @click="wizardVisible = false">取消</el-button>
        <el-button
          v-if="wizardStep === wizardSteps.length - 1" type="primary"
          :loading="runningKey === wizardTemplate?.key" @click="submitWizard"
        >确认运行</el-button>
      </template>
    </el-dialog>

    <!-- 新建调度 -->
    <el-dialog v-model="schedDialog" title="新建调度任务" width="520px">
      <el-form label-width="100px">
        <el-form-item label="任务名称"><el-input v-model="schedForm.name" placeholder="如：每天早8点扫趋势" /></el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="schedForm.kind" @change="schedForm.workflow_key = ''">
            <el-option v-for="o in SCHEDULE_KIND_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="schedForm.kind === 'workflow'" label="工作流">
          <el-select v-model="schedForm.workflow_key" style="width: 100%">
            <el-option v-for="t in templates" :key="t.key" :label="t.name" :value="t.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="执行频率">
          <el-select v-model="schedForm.interval_minutes" style="width: 100%">
            <el-option v-for="o in FREQ_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="schedDialog = false">取消</el-button>
        <el-button type="primary" @click="createSchedule">创建</el-button>
      </template>
    </el-dialog>

    <!-- 运行详情 -->
    <el-drawer v-model="drawer" :title="`工作流运行 #${current.id || ''}`" size="640px">
      <template v-if="current.id">
        <el-alert v-if="current.error" type="error" :title="current.error" :closable="false" class="mb8" />
        <el-steps :active="activeStep" direction="vertical" style="height: 560px">
          <el-step
            v-for="s in current.steps" :key="s.seq"
            :title="`${agentLabel(s.agent)}.${s.action}`"
            :status="stepFlowStatus(s.status)" :description="stepDesc(s)"
          />
        </el-steps>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import SectionState from '../../components/SectionState.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import WorkflowStepper from '../../components/WorkflowStepper.vue'
import { can } from '../../permissions/permissions'
import { normalizeError } from '../../shared/api/errors'
import {
  fetchTemplates, fetchRuns, runWorkflow, fetchRun, resumeRun as resumeRunApi,
} from '../../api/domains/workflows'
import {
  fetchSchedules, createSchedule as createScheduleApi,
  updateSchedule, deleteSchedule, triggerSchedule,
} from '../../api/domains/schedules'
import {
  agentLabel, isRecoverableRun, runActiveStep, runWizardSteps,
  sortRunsForRecovery, stepDesc, stepFlowStatus,
} from '../../features/aiops/workflowView'
import {
  FREQ_OPTIONS, SCHEDULE_KIND_OPTIONS, freqLabel, kindLabel,
  lastStatusLabel, nextRunAt,
} from '../../features/aiops/scheduleView'

const writable = can('ai:write')

const templates = ref([])
const runs = ref([])
const schedules = ref([])
const loading = ref(false)
const error = ref('')
const traceId = ref('')
const runningKey = ref('')
const resuming = ref(null)
const triggering = ref(null)
const drawer = ref(false)
const current = ref({})
let pollTimer = null

/** SectionState 五态：loading/empty/error/nopermission/ready（P2-3 风格收敛）。 */
const listState = computed(() => {
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  if (!templates.value.length) return 'empty'
  return 'ready'
})

const sortedRuns = computed(() => sortRunsForRecovery(runs.value))
const recoverableRuns = computed(() => sortedRuns.value.filter(isRecoverableRun).slice(0, 3))
const activeStep = computed(() => runActiveStep(current.value.steps || []))

async function load() {
  loading.value = true
  error.value = ''
  traceId.value = ''
  try {
    const [t, r, s] = await Promise.all([fetchTemplates(), fetchRuns(50), fetchSchedules()])
    templates.value = t.items || []
    runs.value = r.items || []
    schedules.value = s.items || []
  } catch (e) {
    const norm = normalizeError(e)
    error.value = norm.message
    traceId.value = norm.traceId || ''
  } finally {
    loading.value = false
  }
}

// ---- 运行向导 ----
const wizardVisible = ref(false)
const wizardTemplate = ref(null)
const wizardStep = ref(0)
const wizardSteps = computed(() => runWizardSteps(wizardTemplate.value))

function openWizard(tpl) {
  wizardTemplate.value = tpl
  wizardStep.value = 0
  wizardVisible.value = true
}

async function submitWizard() {
  if (!wizardTemplate.value) return
  runningKey.value = wizardTemplate.value.key
  try {
    const data = await runWorkflow(wizardTemplate.value.key, {})
    ElMessage.info(`「${wizardTemplate.value.name}」已提交，最终结果以运行状态为准`)
    wizardVisible.value = false
    load()
    showRun(data)
  } finally {
    runningKey.value = ''
  }
}

// ---- 运行历史 / 恢复 ----
async function resumeRun(row) {
  resuming.value = row.id
  try {
    await resumeRunApi(row.id)
    ElMessage.success('已从安全检查点恢复执行')
    load()
  } finally {
    resuming.value = null
  }
}

async function showRun(row) {
  const data = await fetchRun(row.id)
  current.value = data
  drawer.value = true
  clearInterval(pollTimer)
  if (data.status === 'running') {
    pollTimer = setInterval(async () => {
      const r = await fetchRun(row.id)
      current.value = r
      if (r.status !== 'running') {
        clearInterval(pollTimer)
        load()
      }
    }, 2000)
  }
}

onUnmounted(() => clearInterval(pollTimer))

// ---- 调度 ----
const schedDialog = ref(false)
const schedForm = reactive({ name: '', kind: 'workflow', workflow_key: '', interval_minutes: 1440 })

function lastStatusTag(status) {
  return { success: 'success', failed: 'danger' }[status] || 'warning'
}

async function toggleSchedule(row, enabled) {
  try {
    await updateSchedule(row.id, { enabled })
    ElMessage.success(enabled ? '已启用，到期将自动执行' : '已停用')
  } catch (e) {
    ElMessage.error(normalizeError(e).message) // 409：调度正在执行
  }
  load()
}

async function runSchedule(row) {
  triggering.value = row.id
  try {
    const data = await triggerSchedule(row.id)
    if (data.ok) ElMessage.success(`执行成功（${data.detail}）`)
    else ElMessage.warning(`执行失败：${data.detail}`)
    load()
  } finally {
    triggering.value = null
  }
}

async function removeSchedule(row) {
  try {
    await ElMessageBox.confirm(`确定删除调度任务「${row.name}」？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  await deleteSchedule(row.id)
  ElMessage.success('已删除')
  load()
}

async function createSchedule() {
  if (!schedForm.name.trim()) return ElMessage.warning('请填写任务名称')
  if (schedForm.kind === 'workflow' && !schedForm.workflow_key) {
    return ElMessage.warning('请选择要调度的工作流模板')
  }
  await createScheduleApi({ ...schedForm })
  ElMessage.success('调度任务已创建')
  schedDialog.value = false
  load()
}

onMounted(load)
</script>

<style scoped>
.recover-cards { display: flex; gap: var(--space-3); flex-wrap: wrap; }
.recover-card { width: 320px; }
.recover-head { display: flex; align-items: center; gap: var(--space-2); margin-bottom: 6px; }
.recover-title { font-weight: 600; font-size: 13px; }
.recover-err {
  color: var(--color-text-secondary, #909399);
  font-size: 12px;
  margin-bottom: 8px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tpl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--space-3); }
.tpl-name { margin: 0 0 6px; }
.tpl-desc { color: var(--color-text-secondary, #909399); font-size: 12px; min-height: 36px; margin: 0; }
.pipeline { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; min-height: 32px; }
.tpl-run { width: 100%; margin-top: 10px; }
.muted { color: var(--color-text-placeholder, #c0c4cc); }
.mb8 { margin-bottom: var(--space-2); }
</style>
