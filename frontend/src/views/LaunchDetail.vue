<template>
  <div class="page" v-loading="loading">
    <el-card class="head-card">
      <div class="head">
        <div class="head-left">
          <el-button size="small" @click="goBack">返回列表</el-button>
          <span class="title">{{ title }}</span>
          <el-tag v-if="detail?.is_history" size="small" type="info">历史轮次</el-tag>
        </div>
        <div class="head-right">
          <launch-experience-toggle v-model="mode" :effective="effectiveMode" />
          <el-button size="small" :loading="syncing" @click="doSync">同步刷新</el-button>
        </div>
      </div>
    </el-card>

    <el-alert v-if="error" type="error" show-icon :closable="false" :title="error" class="mb16" />

    <template v-if="detail">
      <launch-status-summary :launch="detail" :guided="!professional" class="mb16" />

      <!-- 待平台核验：显式说明「等待核验」，绝不显示为已上线/已完成 -->
      <waiting-external-state v-if="waitingExternal" class="mb16" owner="平台"
        :since="detail.last_submitted_at || ''" :hint="detail.verification_notice || ''" />

      <el-descriptions v-if="professional" :column="3" border size="small" class="mb16">
        <el-descriptions-item label="Profile">{{ detail.profile?.key }} v{{ detail.profile?.version }}</el-descriptions-item>
        <el-descriptions-item label="Profile hash">{{ detail.profile?.hash || '未接入' }}</el-descriptions-item>
        <el-descriptions-item label="revision">{{ detail.revision }}</el-descriptions-item>
        <el-descriptions-item label="环境">{{ detail.environment }}</el-descriptions-item>
        <el-descriptions-item label="验证状态">{{ detail.verification_status }}</el-descriptions-item>
        <el-descriptions-item label="同步时间">{{ detail.last_synced_at || '未同步' }}</el-descriptions-item>
      </el-descriptions>

      <div v-if="detail.professional_links?.length" class="links mb16">
        <span class="muted">专业页：</span>
        <el-button v-for="link in detail.professional_links" :key="link.step_code + link.path"
          size="small" plain @click="openLink(link)">
          {{ link.step_code }} → {{ link.path }}
        </el-button>
      </div>

      <div class="columns">
        <launch-timeline :steps="detail.steps" :active-code="selectedStep?.step_code || ''" @select="select" />
        <launch-step-panel :step="selectedStep" :revision="detail.revision" :professional="professional"
          :can-manage="canManage" @run="openAction" />
      </div>
    </template>

    <launch-action-dialog v-model="dialogVisible" :run-id="runId" :action="pendingAction"
      :step-code="selectedStep?.step_code || ''" :revision="detail?.revision || 0"
      @executed="onExecuted" @conflict="onConflict" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from '../ui'
import { can } from '../permissions'
import {
  errorEnvelope, experienceMode, loadContext, loadDetail, sanitizeReturnTo, syncLaunch,
} from '../composables/launchCenter'
import LaunchExperienceToggle from '../components/LaunchExperienceToggle.vue'
import LaunchStatusSummary from '../components/LaunchStatusSummary.vue'
import LaunchTimeline from '../components/LaunchTimeline.vue'
import LaunchStepPanel from '../components/LaunchStepPanel.vue'
import LaunchActionDialog from '../components/LaunchActionDialog.vue'
import WaitingExternalState from '../components/WaitingExternalState.vue'

const route = useRoute()
const router = useRouter()

const runId = computed(() => Number(route.params.id))
const detail = ref(null)
const loading = ref(false)
const error = ref('')
const syncing = ref(false)
const selectedCode = ref('')
const effectiveMode = ref('GUIDED')
const mode = ref('GUIDED')
const dialogVisible = ref(false)
const pendingAction = ref({})

const canManage = computed(() => can('launch:manage'))
const professional = computed(() => mode.value === 'PROFESSIONAL')
const steps = computed(() => detail.value?.steps || [])
const selectedStep = computed(() => steps.value.find((s) => s.step_code === selectedCode.value) || steps.value[0] || null)
const title = computed(() => {
  const product = detail.value?.product?.title
  const store = detail.value?.store
  const suffix = store ? `${store.platform} · ${store.name}` : '上线流程'
  return product ? `${product} ｜ ${suffix}` : `上线流程 #${runId.value}`
})
const backTarget = computed(() => sanitizeReturnTo(route.query.return_to, '/launch'))

/** 平台侧「等待核验」状态：SUBMITTED / UNDER_REVIEW。 */
const WAITING_PLATFORM_STATUSES = new Set(['SUBMITTED', 'UNDER_REVIEW'])
const waitingExternal = computed(() => WAITING_PLATFORM_STATUSES.has(detail.value?.platform_status))

/**
 * 当前详情 URL（剔除 return_to 自身）：作为专业页回跳的 fallback，
 * 使专业页「返回上一步」能回到**原上线步骤**（而非丢回列表）。
 */
const currentDetailUrl = computed(() => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(route.query)) {
    if (key === 'return_to' || value === null || value === undefined) continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${route.path}?${qs}` : route.path
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    detail.value = await loadDetail(runId.value)
    if (!steps.value.some((s) => s.step_code === selectedCode.value)) {
      selectedCode.value = detail.value.current_steps?.[0] || steps.value[0]?.step_code || ''
    }
  } catch (err) {
    error.value = errorEnvelope(err).message
    detail.value = null
  } finally {
    loading.value = false
  }
}

async function initMode() {
  try {
    effectiveMode.value = experienceMode(await loadContext())
  } catch {
    effectiveMode.value = 'GUIDED'
  }
  mode.value = effectiveMode.value
}

function select(step) {
  selectedCode.value = step.step_code
}

function openAction(entry) {
  pendingAction.value = entry
  dialogVisible.value = true
}

async function onExecuted(launch) {
  if (launch) detail.value = launch
  else await load()
}

async function onConflict() {
  await load()  // 保留用户未提交输入由对话框持有；此处只刷新状态
  ElMessage.warning('流程已被更新，已刷新最新状态')
}

async function doSync() {
  if (!detail.value) return
  syncing.value = true
  try {
    const out = await syncLaunch(runId.value, detail.value.revision)
    if (out.launch) detail.value = out.launch
    ElMessage.success('已同步刷新')
  } catch (err) {
    const envelope = errorEnvelope(err)
    if (envelope.code === 'REVISION_CONFLICT') {
      await load()
      ElMessage.warning('流程已更新，已刷新')
    } else {
      ElMessage.error(envelope.message)
    }
  } finally {
    syncing.value = false
  }
}

function openLink(link) {
  // fallback 改为**当前详情 URL**：专业页据此「返回上一步」回到原步骤（AC-14.7 闭环）。
  router.push({ path: link.path, query: { return_to: sanitizeReturnTo(link.return_to, currentDetailUrl.value) } })
}

function goBack() {
  router.push(backTarget.value)
}

onMounted(async () => {
  await initMode()
  await load()
})
</script>

<style scoped>
.head-card { margin-bottom: 16px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.head-left { display: flex; align-items: center; gap: 10px; }
.head-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.title { font-weight: 600; font-size: 15px; }
.mb16 { margin-bottom: 16px; }
.columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
.links { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.muted { color: #909399; font-size: 12px; }
@media (max-width: 1100px) { .columns { grid-template-columns: 1fr; } }
</style>
