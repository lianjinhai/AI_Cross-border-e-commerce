<template>
  <div class="page">
    <PageHeader
      title="AI 行动中心"
      subtitle="AI 建议全生命周期：对象 / 原因 / 证据 / 风险 / 经济口径 / 状态 / 来源 / 审批人 / 结果 / 下一操作"
    >
      <template #filters>
        <el-radio-group v-model="statusFilter" size="small" @change="load">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="PENDING_APPROVAL">待审批</el-radio-button>
          <el-radio-button value="APPROVED">已批准</el-radio-button>
          <el-radio-button value="SUCCESS">执行成功</el-radio-button>
          <el-radio-button value="FAILED">执行失败</el-radio-button>
        </el-radio-group>
        <el-select v-model="typeFilter" size="small" placeholder="动作类型" clearable @change="load">
          <el-option v-for="o in typeOptions" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
      </template>
      <template #actions>
        <el-button size="small" @click="load">刷新</el-button>
        <el-button size="small" @click="router.push('/app/ai/decisions')">决策依据</el-button>
      </template>
    </PageHeader>

    <SectionState :code="listCode" :error="error" @retry="load">
      <el-card shadow="never" class="mb16">
        <el-table :data="items" size="small" v-loading="loading" @row-click="open">
          <el-table-column label="建议对象" width="120">
            <template #default="{ row }">
              <span v-if="row.target_type">{{ row.target_type }} #{{ row.target_id }}</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="原因" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ row.reason || '—' }}</template>
          </el-table-column>
          <el-table-column label="证据摘要" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="open(row)">
                {{ evidenceSummary(row) }}
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="风险级别" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="riskTag(row.risk_level).type" effect="plain">
                {{ riskTag(row.risk_level).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="经济影响口径" width="150">
            <template #default="{ row }">{{ economicSummary(row) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.status).type" effect="plain">
                {{ statusTag(row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_by" label="创建来源" width="100">
            <template #default="{ row }">{{ row.created_by || 'AI' }}</template>
          </el-table-column>
          <el-table-column prop="approved_by" label="审批人" width="100">
            <template #default="{ row }">{{ row.approved_by || '—' }}</template>
          </el-table-column>
          <el-table-column label="执行结果" width="120" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.status === 'SUCCESS'">成功</span>
              <span v-else-if="row.status === 'FAILED'" class="fail-text">{{ row.outcome?.error || '失败' }}</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="下一操作" width="170" fixed="right">
            <template #default="{ row }">
              <template v-if="row.status === 'PENDING_APPROVAL' && writable">
                <el-button size="small" type="success" @click.stop="decide(row, true)">批准</el-button>
                <el-button size="small" type="danger" @click.stop="decide(row, false)">拒绝</el-button>
              </template>
              <el-button
                v-else-if="row.status === 'APPROVED' && writable"
                size="small" type="primary" @click.stop="execute(row)"
              >执行</el-button>
              <el-button
                v-else-if="row.status === 'FAILED' && writable"
                size="small" type="warning" @click.stop="execute(row)"
              >重试执行</el-button>
              <span v-else class="next-hint">{{ nextHint(row) }}</span>
            </template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="AI 还没有提出建议（或当前筛选无结果）" /></template>
        </el-table>
      </el-card>
    </SectionState>

    <!-- 证据抽屉：证据快照（EvidencePanel）+ 风险 -->
    <el-drawer v-model="drawer" title="AI 建议证据" size="520px">
      <template v-if="current.id">
        <el-descriptions :column="2" border size="small" class="mb12">
          <el-descriptions-item label="动作">{{ current.action_type || current.action || '—' }}</el-descriptions-item>
          <el-descriptions-item label="对象">{{ current.target_type || '—' }} #{{ current.target_id ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="创建来源">{{ current.created_by || 'AI' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusTag(current.status).label }}</el-descriptions-item>
        </el-descriptions>
        <EvidencePanel
          :items="current.evidence_items || []"
          :risks="current.risk_items || []"
          :source="evidenceSource(current)"
          :decision-id="current.decision_id || current.id"
          @view-decision="viewDecision"
        />
      </template>
    </el-drawer>

    <!-- 审批：AsyncActionDialog（对象/Store/金额币种/前置条件/审批人展示） -->
    <AsyncActionDialog
      v-model="approveDialog"
      :action="pendingVerb"
      :context="pendingContext"
      :idempotency-key="pendingKey"
      :done-message="pendingVerb === '批准' ? '已批准，可执行' : '已拒绝'"
      @submit="onApproveSubmit"
      @requery="load"
    />

    <!-- 执行回执（提交中/成功/失败/409/超时不盲重试） -->
    <AsyncActionDialog
      v-model="executeDialog"
      action="执行动作"
      :context="executeContext"
      :idempotency-key="executeKey"
      done-message="执行成功"
      @submit="onExecuteSubmit"
      @requery="load"
    />
  </div>
</template>

<script setup>
/**
 * AI 行动中心（蓝图 R1 AI-02，包 2）：/app/ai/actions。
 *
 * 数据源：actions.js（已接 approve/reject/execute）。
 * 列表字段：建议对象/原因/证据摘要/风险级别/经济影响口径/状态/创建来源/审批人/执行结果/下一操作；
 * 审批走 AsyncActionDialog（409 刷新不丢输入；超时 UNCERTAIN 只重新查询状态）；
 * 证据快照用 EvidencePanel（未核验中性样式，verified=true 才绿）。
 * 11 态：列表分区走 SectionState code；旧审批失效 = BLOCKED 语义（409 → 刷新）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import EvidencePanel from '../../components/EvidencePanel.vue'
import AsyncActionDialog from '../../components/AsyncActionDialog.vue'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import { can } from '../../permissions/permissions'
import { fetchActions, approve, reject, execute as executeAction } from '../../api/domains/actions'

const router = useRouter()
const writable = can('order:write')

const typeOptions = [
  { value: 'ADJUST_AD_BUDGET', label: '预算调整' },
  { value: 'REPRICE', label: '重新定价' },
  { value: 'RESTOCK', label: '补货建议' },
]

const items = ref([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref('')
const typeFilter = ref('')

const listCode = computed(() => {
  if (error.value) return 'ERROR'
  if (loading.value) return 'LOADING'
  if (!items.value.length && statusFilter.value) return 'EMPTY_FILTER'
  if (!items.value.length) return 'EMPTY_NEW'
  return 'ready'
})

const STATUS_TAGS = {
  PENDING_APPROVAL: { type: 'warning', label: '待审批' },
  APPROVED: { type: 'primary', label: '已批准 · 待执行' },
  SUCCESS: { type: 'success', label: '执行成功' },
  FAILED: { type: 'danger', label: '执行失败' },
  REJECTED: { type: 'info', label: '已拒绝' },
}
const RISK_TAGS = {
  low: { type: 'success', label: '低' },
  mid: { type: 'warning', label: '中' },
  high: { type: 'danger', label: '高' },
}

function statusTag(status) {
  return STATUS_TAGS[status] || { type: 'info', label: status || '未知' }
}
function riskTag(level) {
  const key = String(level || '').toLowerCase()
  return RISK_TAGS[key] || { type: 'info', label: level ? String(level) : '未标注' }
}

/** 证据摘要（单行，抽屉看全量）。 */
function evidenceSummary(row) {
  const ev = row.evidence || row.evidence_items
  if (Array.isArray(ev) && ev.length) return `证据 ${ev.length} 项`
  if (row.decision_id) return `决策 #${row.decision_id}`
  return '无证据快照'
}

/** 经济影响口径：old → new（金额币种），缺项显"—"。 */
function economicSummary(row) {
  const old = row.evidence?.old_budget
  const nw = row.expected_impact?.new_budget
  if (old == null && nw == null) return '—'
  const cur = row.expected_impact?.currency || row.currency || ''
  return `${old ?? '—'} → ${nw ?? '—'} ${cur}`.trim()
}

/** 下一操作提示（只读行）。 */
function nextHint(row) {
  if (row.status === 'PENDING_APPROVAL' && !writable) return '仅审批人可操作'
  if (row.status === 'APPROVED' && !writable) return '仅执行角色可操作'
  if (row.status === 'SUCCESS') return '已完成'
  if (row.status === 'FAILED') return '失败可重试或查看决策依据'
  if (row.status === 'REJECTED') return '已拒绝，无需操作'
  return '—'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const wantAll = !statusFilter.value
    const statuses = wantAll
      ? ['PENDING_APPROVAL', 'APPROVED', 'SUCCESS', 'FAILED']
      : [statusFilter.value]
    const lists = await Promise.all(statuses.map((s) => fetchActions({
      status: s, type: typeFilter.value || undefined, page: 1,
    })))
    items.value = lists.flatMap((r) => r.items || [])
  } catch (e) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// ── 证据抽屉 ──
const drawer = ref(false)
const current = ref(null)

function open(row) {
  current.value = row
  drawer.value = true
}

function evidenceSource(row) {
  if (row.evidence?.source) return row.evidence.source
  return row.model === 'llm' ? 'AI 估算（大模型）' : '规则引擎'
}

function viewDecision(decisionId) {
  drawer.value = false
  router.push({ path: '/app/ai/decisions', query: { subject_id: decisionId, return_to: '/app/ai/actions' } })
}

// ── 审批（AsyncActionDialog） ──
const approveDialog = ref(false)
const pendingVerb = ref('批准')
const pendingRow = ref(null)
const pendingKey = computed(() =>
  pendingRow.value ? `action:${pendingRow.value.id}:${pendingVerb.value === '批准' ? 'approve' : 'reject'}:${Date.now()}` : '')
const pendingContext = computed(() => {
  const row = pendingRow.value
  if (!row) return ''
  return `对象 ${row.target_type || '—'} #${row.target_id ?? '—'} · ${row.reason || ''} · 经济口径 ${economicSummary(row)}`
})

function decide(row, isApprove) {
  pendingVerb.value = isApprove ? '批准' : '拒绝'
  pendingRow.value = row
  approveDialog.value = true
}

async function onApproveSubmit() {
  const row = pendingRow.value
  let note = ''
  try {
    const { value } = await ElMessageBox.prompt(
      '请输入审批依据（将记入 Action 审计）', `${pendingVerb.value} #${row.id}`,
      { inputPattern: /\S+/, inputErrorMessage: '依据不能为空' })
    note = value.trim()
  } catch { return } // 用户取消：保持对话框，不丢输入
  try {
    if (pendingVerb.value === '批准') await approve(row.id, { note })
    else await reject(row.id, { reason: note })
    ElMessage.success(`已${pendingVerb.value} #${row.id}`)
    approveDialog.value = false
    await load()
  } catch (e) {
    const status = e?.response?.status
    // 409：旧审批失效（状态已变）→ 刷新不丢输入（BLOCKED 语义）
    if (status === 409) {
      ElMessage.warning('状态已变更：该建议已被他人处理，刷新中')
      approveDialog.value = false
      await load()
    } else {
      ElMessage.error(e?.response?.data?.detail || e?.message || '审批失败')
    }
  }
}

// ── 执行（AsyncActionDialog：失败可重试；超时 UNCERTAIN 只重新查询） ──
const executeDialog = ref(false)
const executingRow = ref(null)
const executeKey = computed(() =>
  executingRow.value ? `action:${executingRow.value.id}:execute:${Date.now()}` : '')
const executeContext = computed(() => {
  const row = executingRow.value
  if (!row) return ''
  return `对象 ${row.target_type || '—'} #${row.target_id ?? '—'} · 经济口径 ${economicSummary(row)}`
})

function execute(row) {
  executingRow.value = row
  executeDialog.value = true
}

async function onExecuteSubmit() {
  const row = executingRow.value
  try {
    const result = await executeAction(row.id)
    if (result?.status === 'SUCCESS') ElMessage.success(`#${row.id} 执行成功`)
    else ElMessage.warning(result?.outcome?.error || '执行失败，可重试')
    executeDialog.value = false
    await load()
  } catch (e) {
    if (e?.response?.status === 409) {
      ElMessage.warning('状态已变更，刷新中')
      executeDialog.value = false
      await load()
    }
    throw e // 交由 AsyncActionDialog FAILED/UNCERTAIN 分支
  }
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.mb12 { margin-bottom: 12px; }
.fail-text { color: var(--color-danger); }
.next-hint { font-size: var(--font-size-xs); color: var(--color-text-secondary); }
</style>
