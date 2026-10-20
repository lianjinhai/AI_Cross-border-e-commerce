<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div class="approval-panel__header">
        <span>{{ title }}（审批 → 执行 → 结果三态可见）</span>
        <el-button size="small" @click="load">刷新</el-button>
      </div>
    </template>
    <el-table :data="items" size="small" empty-text="暂无动作记录">
      <el-table-column prop="id" label="Action" width="80" />
      <el-table-column prop="target_id" label="目标活动" width="90" />
      <el-table-column prop="reason" label="调整依据" min-width="200" show-overflow-tooltip />
      <el-table-column label="预算变化" width="140">
        <template #default="{ row }">
          {{ row.evidence?.old_budget ?? '—' }} → {{ row.expected_impact?.new_budget ?? '—' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status).type" size="small">{{ statusTag(row.status).label }}</el-tag>
          <div v-if="row.status === 'FAILED' && row.outcome?.error" class="approval-panel__error">
            {{ row.outcome.error }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <template v-if="row.status === 'PENDING_APPROVAL' && writable">
            <el-button size="small" type="success" @click="decide(row, true)">批准</el-button>
            <el-button size="small" type="danger" @click="decide(row, false)">拒绝</el-button>
          </template>
          <el-button
            v-if="row.status === 'APPROVED' && writable"
            size="small" type="primary" @click="execute(row)"
          >
            执行
          </el-button>
          <el-button
            v-if="row.status === 'FAILED' && writable"
            size="small" type="warning" @click="execute(row)"
          >
            重试执行
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
/**
 * 审批面板（V9 第 3 批组件）：统一消费 /actions 域（契约 §4.2）。
 * 审批-执行-结果三态在列表可见：PENDING_APPROVAL（待审批）→ APPROVED（已批准
 * 待执行）→ SUCCESS/FAILED（执行结果，失败给原因并支持重试）。
 * 加载策略：并行拉取 4 个状态合并展示（后端 list_actions 单状态过滤）。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../shared/ui'
import { fetchActions, approve, reject, execute as executeAction } from '../api/domains/actions'

const props = defineProps({
  title: { type: String, default: '预算调整审批' },
  // Action 类型（后端 list_actions 必填 action_type，默认预算调整）。
  type: { type: String, default: 'ADJUST_AD_BUDGET' },
  writable: { type: Boolean, default: false },
})

const emit = defineEmits(['changed'])

const ACTION_STATUSES = ['PENDING_APPROVAL', 'APPROVED', 'SUCCESS', 'FAILED']
const STATUS_TAGS = {
  PENDING_APPROVAL: { type: 'warning', label: '待审批' },
  APPROVED: { type: 'primary', label: '已批准 · 待执行' },
  SUCCESS: { type: 'success', label: '执行成功' },
  FAILED: { type: 'danger', label: '执行失败' },
}

const items = ref([])
const loading = ref(false)

function statusTag(status) {
  return STATUS_TAGS[status] || { type: 'info', label: status }
}

async function load() {
  loading.value = true
  try {
    // type prop 必须真正下发：否则「广告预算审批」面板会把其它类型的待办也拉进来（S3 修正）。
    const lists = await Promise.all(ACTION_STATUSES.map(
      (status) => fetchActions({ status, type: props.type || undefined })))
    items.value = lists.flatMap((r) => r.items || [])
    emit('changed')
  } finally {
    loading.value = false
  }
}

async function decide(row, isApprove) {
  const verb = isApprove ? '批准' : '拒绝'
  let note = ''
  try {
    const { value } = await ElMessageBox.prompt(
      `请输入${verb}依据（将记入 Action 审计）`, `${verb}预算调整 #${row.id}`,
      { inputPattern: /\S+/, inputErrorMessage: '依据不能为空' })
    note = value.trim()
  } catch { return }
  if (isApprove) await approve(row.id, { note })
  else await reject(row.id, { reason: note })
  ElMessage.success(`已${verb}预算调整 #${row.id}`)
  load()
}

async function execute(row) {
  try {
    await ElMessageBox.confirm(
      `确定执行活动 #${row.target_id} 的预算调整？`, '执行已批准的 Action', { type: 'warning' })
  } catch { return }
  const result = await executeAction(row.id)
  if (result.status === 'SUCCESS') ElMessage.success('预算已调整')
  else ElMessage.warning(result.outcome?.error || '执行失败，可重试')
  load()
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.approval-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.approval-panel__error {
  color: var(--color-danger);
  font-size: var(--font-size-xs);
  margin-top: 2px;
}
</style>
