<template>
  <div class="page">
    <PageHeader :title="`上线流程 #${runId}`" subtitle="步骤导航 · AI 建议 · 动作失败原因与重试">
      <template #actions>
        <el-button size="small" @click="goBack">{{ returnLabel }}</el-button>
        <el-button size="small" :loading="syncing" @click="doSync">同步状态</el-button>
        <LaunchExperienceToggle v-model="mode" :effective="effectiveMode" />
      </template>
    </PageHeader>

    <SectionState :state="detailState" :error="error" @retry="loadAll">
      <template #default>
        <LaunchStatusSummary :launch="detail" :guided="mode === 'GUIDED'" class="mb16" />

        <!-- J1 诚实红线：WAITING_EXTERNAL 显式标注「等待外部平台回执」，绝不写成已上线。 -->
        <WaitingExternalState v-if="detail.execution_status === 'WAITING_EXTERNAL'" owner="平台"
          :since="detail.updated_at || detail.created_at || ''"
          hint="等待外部平台回执，流程尚未上线，请勿视为已发布" class="mb16" />

        <el-row :gutter="16">
          <!-- GUIDED 侧边步骤导航（PROFESSIONAL 用完整时间线） -->
          <el-col :span="10">
            <LaunchTimeline :steps="steps" :active-code="activeCode" @select="selectStep" />
          </el-col>
          <el-col :span="14">
            <LaunchStepPanel :step="activeStep" :professional="mode === 'PROFESSIONAL'"
              @run="openAction" />
            <!-- 动作完成回执（E10）：什么改变了 / 仍缺什么 / 下一步 -->
            <el-alert v-if="lastReceipt" type="success" :closable="false" show-icon class="mt12"
              :title="`动作 ${lastReceipt.action} 已执行（版本 ${lastReceipt.revision}）`">
              <div class="receipt-line"><span class="muted">改变了</span> {{ lastReceipt.changed }}</div>
              <div class="receipt-line"><span class="muted">仍缺</span> {{ lastReceipt.stillMissing }}</div>
              <div class="receipt-line"><span class="muted">下一步</span> {{ lastReceipt.nextAction }}</div>
            </el-alert>
            <!-- 动作失败原因直出 + 重试（验收条目） -->
            <el-alert v-if="lastError" type="error" :closable="false" show-icon class="mt12"
              :title="`动作执行失败：${lastError.message}`">
              <div class="retry-line">
                <span class="muted">代码 {{ lastError.code }}</span>
                <el-button size="small" type="primary" plain @click="openAction(lastActionEntry)">重试</el-button>
              </div>
            </el-alert>
            <!-- 每步 AI 建议（建议→证据→动作 三段式） -->
            <AiActionCard v-if="aiSuggestion.title" class="mt12" :suggestion="aiSuggestion"
              :evidence="aiSuggestion.evidence || []" :risks="aiSuggestion.risks || []"
              :actions="aiSuggestion.actions || []" @apply="applyAiAction" />
          </el-col>
        </el-row>

        <!-- 事件流 -->
        <el-card shadow="never" class="mt16">
          <template #header><span class="card-title">事件流</span></template>
          <el-table :data="events" size="small" v-loading="loadingEvents">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="event_type" label="事件" width="160" />
            <el-table-column prop="message" label="说明" min-width="240" show-overflow-tooltip />
            <el-table-column prop="created_at" label="时间" width="170" />
            <template #empty><EmptyState reason="NO_DATA" hint="暂无事件" /></template>
          </el-table>
        </el-card>
      </template>
    </SectionState>

    <LaunchActionDialog v-model="dialogVisible" :run-id="runId" :action="activeActionEntry"
      :step-code="activeCode" :revision="revision" @executed="reloadAfterAction" @conflict="onConflict" />
  </div>
</template>

<script setup>
/**
 * 上线流程详情（UX-C）：GUIDED 侧边步骤导航 + 每步 AI 建议；动作失败给原因与重试；
 * 无权限呈 NoPermissionState（SectionState nopermission 态）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import AiActionCard from '../../components/AiActionCard.vue'
import LaunchStatusSummary from '../../features/launch/LaunchStatusSummary.vue'
import LaunchTimeline from '../../features/launch/LaunchTimeline.vue'
import LaunchStepPanel from '../../features/launch/LaunchStepPanel.vue'
import LaunchActionDialog from '../../features/launch/LaunchActionDialog.vue'
import LaunchExperienceToggle from '../../features/launch/LaunchExperienceToggle.vue'
import { errorEnvelope, actionReceiptView, isSafeReturnTo, loadDetail, loadEvents, loadSteps, syncLaunch } from '../../composables/launchCenter'
import WaitingExternalState from '../../features/launch/WaitingExternalState.vue'
import { safeReturnToTasks } from '../../shared/taskCenterView'

const route = useRoute()
const router = useRouter()
const runId = Number(route.params.id)

/**
 * 回跳目标规范化（J1/J2 共用着陆页）：
 * - 待办中心来源（/app/tasks…）走 J2 的 safeReturnToTasks；
 * - 商品 / 上线中心 / Listing / 店铺等来源走通用白名单（navigationReturn.isSafeReturnTo）；
 * - 均非法则维持浏览器返回（R3-2 行为），保证「返回不丢上下文」。
 */
const returnTo = computed(() => {
  const v = route.query.return_to
  if (typeof v !== 'string' || !v) return ''
  if (v.startsWith('/app/tasks')) return safeReturnToTasks(v)
  return isSafeReturnTo(v) ? v : ''
})
const returnLabel = computed(() => (returnTo.value && returnTo.value.startsWith('/app/tasks')) ? '返回待办' : '返回')
function goBack() {
  if (returnTo.value) router.push(returnTo.value)
  else router.back()
}

const detail = ref({})
const steps = ref([])
const events = ref([])
const error = ref('')
const forbidden = ref(false)
const mode = ref('GUIDED')
const activeCode = ref('')
const syncing = ref(false)
const loadingEvents = ref(false)
const dialogVisible = ref(false)
const activeActionEntry = ref({})
const lastError = ref(null)
const lastActionEntry = ref(null)
const lastReceipt = ref(null)

const effectiveMode = computed(() => detail.value.effective_experience_mode || 'GUIDED')
// E10：动作可执行性由后端 available_actions（已按当前用户权限计算）决定，
// 不再用通用 canWrite() 一刀切；模式切换只改信息密度，不改业务权限。
const revision = computed(() => Number(detail.value.expected_revision ?? detail.value.revision ?? 0))
const activeStep = computed(() => steps.value.find((s) => s.step_code === activeCode.value) || null)

/** 每步 AI 建议：来自步骤 DTO 的 ai_advice 字段；后端未给则不渲染（禁伪造）。 */
const aiSuggestion = computed(() => activeStep.value?.ai_advice || {})

const detailState = computed(() => {
  if (forbidden.value) return 'nopermission'
  if (error.value && !detail.value.id) return 'error'
  if (!detail.value.id) return 'loading'
  return 'ready'
})

function selectStep(step) {
  activeCode.value = step.step_code
  lastError.value = null
  lastActionEntry.value = null
}

function openAction(entry) {
  lastActionEntry.value = entry
  activeActionEntry.value = entry
  dialogVisible.value = true
}

async function loadAll() {
  error.value = ''
  forbidden.value = false
  try {
    detail.value = await loadDetail(runId)
    const stepData = await loadSteps(runId)
    steps.value = stepData.steps || stepData || []
    if (!activeCode.value) {
      // 默认聚焦第一个非完成步骤（全部完成则聚焦首个）。
      const focus = steps.value.find((s) => s.step_status !== 'COMPLETED') || steps.value[0]
      activeCode.value = focus?.step_code || ''
    }
    await loadEventList()
  } catch (e) {
    if (e?.response?.status === 403) forbidden.value = true
    else error.value = errorEnvelope(e).message
  }
}

async function loadEventList() {
  loadingEvents.value = true
  try { events.value = (await loadEvents(runId)).items || [] }
  catch { events.value = [] }
  finally { loadingEvents.value = false }
}

async function doSync() {
  syncing.value = true
  try {
    await syncLaunch(runId, revision.value)
    await loadAll()
  } catch (e) {
    lastError.value = errorEnvelope(e)
  } finally { syncing.value = false }
}

async function reloadAfterAction(result) {
  lastError.value = null
  // E10：动作完成回执（什么改变了/仍缺什么/下一步）+ 刷新合法动作对齐 run.revision
  lastReceipt.value = actionReceiptView(result || {})
  await loadAll()
}

function onConflict(envelope) {
  // 409 后以服务端 current_revision 回填，用户输入保留在对话框内。
  if (envelope.current_revision != null) detail.value.expected_revision = envelope.current_revision
}

onMounted(loadAll)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.mt12 { margin-top: 12px; }
.mt16 { margin-top: 16px; }
.card-title { font-weight: 600; }
.retry-line { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
.receipt-line { font-size: 13px; margin-top: 4px; }
.receipt-line .muted { display: inline-block; min-width: 56px; color: var(--color-text-secondary); }
.muted { color: var(--color-text-secondary); font-size: 12px; }
</style>
