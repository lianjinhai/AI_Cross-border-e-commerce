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

        <!-- 阻断与补齐（P0-4）：阻断不能只给原因，必须同时给出下一步去哪 -->
        <BlockerList v-if="detail.blockers && detail.blockers.length" :blockers="detail.blockers" class="mb16" />

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
            <!-- 失败态同样要有补齐入口（P0-4）：裸 409 只能告诉用户「不行」，说不出「然后呢」 -->
            <BlockerList v-if="lastError && lastError.blockers && lastError.blockers.length"
              :blockers="lastError.blockers" class="mt12" />
            <!-- 每步 AI 建议（建议→证据→动作 三段式） -->
            <AiActionCard v-if="aiSuggestion.title" class="mt12" :suggestion="aiSuggestion"
              :evidence="aiSuggestion.evidence || []" :risks="aiSuggestion.risks || []"
              :actions="aiSuggestion.actions || []" @apply="applyAiAction" />
          </el-col>
        </el-row>

        <!-- 轮次历史（P0-3）：同一销售对象仅一个活跃槽，历史轮次只读回看 -->
        <el-card shadow="never" class="mt16">
          <template #header>
            <span class="card-title">轮次历史</span>
            <span class="muted round-hint">{{ roundsHint }}</span>
          </template>
          <el-alert v-if="roundsView.anomalies.length" type="error" :closable="false" show-icon class="mb8"
            :title="roundsView.anomalies[0]" />
          <el-table :data="roundsView.rounds" size="small" v-loading="loadingRounds">
            <el-table-column label="轮次" width="90">
              <template #default="{ row }">第 {{ row.round }} 轮</template>
            </el-table-column>
            <el-table-column label="槽位" width="110">
              <template #default="{ row }">
                <el-tag :type="row.is_history ? 'info' : 'success'" size="small" effect="light">
                  {{ row.slot_label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="执行状态" width="130">
              <template #default="{ row }">
                <el-tag :type="executionStatusMeta(row.execution_status).tag" size="small" effect="light">
                  {{ executionStatusMeta(row.execution_status).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="平台状态" width="120">
              <template #default="{ row }">
                <el-tag :type="platformStatusMeta(row.platform_status).tag" size="small" effect="light">
                  {{ platformStatusMeta(row.platform_status).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="170" />
            <el-table-column label="" width="90">
              <template #default="{ row }">
                <span v-if="row.is_current" class="muted">当前查看</span>
                <el-button v-else link type="primary" size="small" @click="goRound(row)">查看</el-button>
              </template>
            </el-table-column>
            <template #empty><EmptyState reason="NO_DATA" hint="暂无轮次记录" /></template>
          </el-table>
        </el-card>

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
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import AiActionCard from '../../components/AiActionCard.vue'
import LaunchStatusSummary from '../../features/launch/LaunchStatusSummary.vue'
import LaunchTimeline from '../../features/launch/LaunchTimeline.vue'
import LaunchStepPanel from '../../features/launch/LaunchStepPanel.vue'
import LaunchActionDialog from '../../features/launch/LaunchActionDialog.vue'
import BlockerList from '../../features/launch/BlockerList.vue'
import LaunchExperienceToggle from '../../features/launch/LaunchExperienceToggle.vue'
import { errorEnvelope, actionReceiptView, isSafeReturnTo, loadDetail, loadEvents, loadSteps, syncLaunch, executionStatusMeta, platformStatusMeta } from '../../composables/launchCenter'
import { fetchLaunches } from '../../api/domains/launch'
import { buildRoundChain, roundChainHint } from '../../shared/launchRounds'
import WaitingExternalState from '../../features/launch/WaitingExternalState.vue'
import { safeReturnToTasks } from '../../shared/taskCenterView'

const route = useRoute()
const router = useRouter()
// 轮次跳转属于「同路由不同参数」，组件会被复用；用响应式 id + watch 重新拉数据，
// 否则点历史轮次的「查看」会看到上一轮的内容。
const runId = ref(Number(route.params.id))
watch(() => route.params.id, (next) => {
  const id = Number(next)
  if (!id || id === runId.value) return
  runId.value = id
  detail.value = {}
  activeCode.value = ''
  lastError.value = null
  lastActionEntry.value = null
  lastReceipt.value = null
  loadAll()
})

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
const loadingRounds = ref(false)
/** 轮次链（P0-3）：同一销售对象的全部轮次 + 活跃槽标记。 */
const roundsView = ref({ rounds: [], activeCount: 0, anomalies: [] })

const effectiveMode = computed(() => detail.value.effective_experience_mode || 'GUIDED')
// E10：动作可执行性由后端 available_actions（已按当前用户权限计算）决定，
// 不再用通用 canWrite() 一刀切；模式切换只改信息密度，不改业务权限。
const revision = computed(() => Number(detail.value.expected_revision ?? detail.value.revision ?? 0))
const activeStep = computed(() => steps.value.find((s) => s.step_code === activeCode.value) || null)

/** 每步 AI 建议：来自步骤 DTO 的 ai_advice 字段；后端未给则不渲染（禁伪造）。 */
const aiSuggestion = computed(() => activeStep.value?.ai_advice || {})

/** 轮次提示：活跃槽为什么还在、历史轮次为什么只读。 */
const roundsHint = computed(() => roundChainHint({
  currentIsHistory: Boolean(detail.value.is_history),
  activeCount: roundsView.value.activeCount,
}))

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
    detail.value = await loadDetail(runId.value)
  } catch (e) {
    if (e?.response?.status === 403) forbidden.value = true
    else error.value = errorEnvelope(e).message
    return
  }
  // 步骤 / 事件 / 轮次三路互不连带：任一失败只降级自己，不拖垮整页。
  await Promise.all([loadStepList(), loadEventList(), loadRounds()])
}

/**
 * 步骤列表：后端 `/launch/{id}/steps` 返回 `{items, revision, profile}`。
 * 这里兼容裸数组与旧 `steps` 字段，并强制归一为数组——否则后续 `.find`
 * 会在对象上抛错，连带把同页的轮次/事件加载全部跳过。
 */
async function loadStepList() {
  try {
    const data = await loadSteps(runId.value)
    const list = Array.isArray(data) ? data : (data?.items || data?.steps || [])
    steps.value = Array.isArray(list) ? list : []
  } catch {
    steps.value = []
  }
  if (!activeCode.value) {
    // 默认聚焦第一个非完成步骤（全部完成则聚焦首个）。
    const focus = steps.value.find((s) => s.step_status !== 'COMPLETED') || steps.value[0]
    activeCode.value = focus?.step_code || ''
  }
}

/**
 * 轮次链：按当前流程的销售对象（商品 + 店铺）取全部轮次（含历史）。
 * 查询走既有列表接口的 include_history，不复用第二套读模型。
 */
async function loadRounds() {
  const productId = detail.value?.product?.id
  const shopId = detail.value?.store?.id
  if (!productId || !shopId) {
    roundsView.value = { rounds: [], activeCount: 0, anomalies: [] }
    return
  }
  loadingRounds.value = true
  try {
    // page_size 取后端上限：轮次按销售对象收窄后数量有限，用默认 20 页会静默截断，
    // 导致「第 N 轮」编号失真；真超上限时由 buildRoundChain 报截断异常。
    const data = await fetchLaunches({
      filters: { product_id: productId, shop_id: shopId, include_history: true, page_size: 200 },
    })
    roundsView.value = buildRoundChain(data?.items || [], runId.value, data?.total ?? null)
  } catch {
    // 轮次读失败不影响主详情：降级为空链，不伪造轮次。
    roundsView.value = { rounds: [], activeCount: 0, anomalies: [] }
  } finally {
    loadingRounds.value = false
  }
}

function goRound(row) {
  if (!row?.id || row.id === runId.value) return
  router.push(`/app/launch/${row.id}`)
}

async function loadEventList() {
  loadingEvents.value = true
  try { events.value = (await loadEvents(runId.value)).items || [] }
  catch { events.value = [] }
  finally { loadingEvents.value = false }
}

async function doSync() {
  syncing.value = true
  try {
    await syncLaunch(runId.value, revision.value)
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
.mb8 { margin-bottom: 8px; }
.mb16 { margin-bottom: 16px; }
.mt12 { margin-top: 12px; }
.mt16 { margin-top: 16px; }
.round-hint { margin-left: 8px; font-weight: 400; }
.card-title { font-weight: 600; }
.retry-line { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
.receipt-line { font-size: 13px; margin-top: 4px; }
.receipt-line .muted { display: inline-block; min-width: 56px; color: var(--color-text-secondary); }
.muted { color: var(--color-text-secondary); font-size: 12px; }
</style>
