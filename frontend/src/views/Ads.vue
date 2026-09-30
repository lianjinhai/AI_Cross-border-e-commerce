<template>
  <div class="page">
    <el-row :gutter="16" class="mb16">
      <el-col :span="6"><el-card class="kpi-card"><div class="kpi-label">总花费</div><div class="kpi-value">${{ summary.total_spend?.toFixed(2) || 0 }}</div></el-card></el-col>
      <el-col :span="6"><el-card class="kpi-card"><div class="kpi-label">总收入</div><div class="kpi-value">${{ summary.total_revenue?.toFixed(2) || 0 }}</div></el-card></el-col>
      <el-col :span="6"><el-card class="kpi-card"><div class="kpi-label">广告 ROI</div><div class="kpi-value" :style="{color: summary.roi > 2 ? '#67C23A' : summary.roi > 0.8 ? '#E6A23C' : '#F56C6C'}">{{ summary.roi ?? '-' }}</div></el-card></el-col>
      <el-col :span="6"><el-card class="kpi-card"><div class="kpi-label">平均 CTR</div><div class="kpi-value">{{ summary.avg_ctr ?? 0 }}%</div></el-card></el-col>
    </el-row>

    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>广告活动</span>
          <el-button v-if="can('ai:write')" type="primary" size="small" @click="sugDialog = true">AI 选词建组</el-button>
        </div>
      </template>
      <el-table :data="campaigns" v-loading="loading" size="small">
        <el-table-column prop="id" label="ID" width="55" />
        <el-table-column prop="name" label="活动" min-width="180" show-overflow-tooltip />
        <el-table-column prop="platform" label="平台" width="90" />
        <el-table-column prop="budget" label="日预算$" width="90" />
        <el-table-column prop="spend" label="花费$" width="90" />
        <el-table-column prop="revenue" label="收入$" width="90" />
        <el-table-column label="ROI" width="100">
          <template #default="{ row }">
            <el-tag :type="row.roi > 2 ? 'success' : row.roi > 0.8 ? 'warning' : 'danger'" size="small">{{ row.roi }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ctr" label="CTR%" width="80" />
        <el-table-column prop="cvr" label="CVR%" width="80" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button v-if="can('finance:write')" size="small" type="primary" @click="optimize(row)">预算优化</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="mt16">
      <template #header>预算调整审批</template>
      <el-table :data="budgetActions" size="small" empty-text="暂无待处理的预算调整">
        <el-table-column prop="id" label="Action ID" width="100" />
        <el-table-column prop="target_id" label="活动 ID" width="90" />
        <el-table-column prop="reason" label="调整依据" min-width="220" show-overflow-tooltip />
        <el-table-column label="预算变化" width="145">
          <template #default="{ row }">{{ row.evidence.old_budget }} → {{ row.expected_impact.new_budget }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="165" />
        <el-table-column label="操作" width="210">
          <template #default="{ row }">
            <el-button v-if="row.status === 'PENDING_APPROVAL' && can('finance:write')"
                       size="small" type="success" @click="decideAction(row, true)">批准</el-button>
            <el-button v-if="row.status === 'PENDING_APPROVAL' && can('finance:write')"
                       size="small" type="danger" @click="decideAction(row, false)">拒绝</el-button>
            <el-button v-if="row.status === 'APPROVED' && can('finance:write')"
                       size="small" type="primary" @click="executeAction(row)">执行</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="sugDialog" title="AI 选词建议" width="560px">
      <el-form label-width="90px">
        <el-form-item label="商品ID"><el-input-number v-model="sug.product_id" :min="1" /></el-form-item>
        <el-form-item label="平台">
          <el-select v-model="sug.platform">
            <el-option v-for="p in ['facebook','google','tiktok']" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
      </el-form>
      <template v-if="sugResult.keywords">
        <el-divider>建议关键词</el-divider>
        <el-tag v-for="k in sugResult.keywords" :key="k" type="info" style="margin:0 6px 6px 0">{{ k }}</el-tag>
        <p style="color:#909399;font-size:13px">{{ sugResult.reason }}</p>
      </template>
      <template #footer>
        <el-button @click="sugDialog = false">关闭</el-button>
        <el-button type="primary" :loading="sugLoading" @click="doSuggest">获取建议</el-button>
        <el-button type="success" :disabled="!sugResult.keywords" @click="createFromSug">按建议创建广告组</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'
import { can } from '../permissions'

const campaigns = ref([])
const summary = ref({})
const budgetActions = ref([])
const loading = ref(false)
const sugDialog = ref(false)
const sugLoading = ref(false)
const sugResult = ref({})
const sug = reactive({ product_id: 1, platform: 'facebook' })

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/ads/campaigns')
    campaigns.value = data.campaigns
    summary.value = data.summary
    if (can('finance:write')) {
      const [pending, approved] = await Promise.all([
        api.get('/actions', { params: { status: 'PENDING_APPROVAL' } }),
        api.get('/actions', { params: { status: 'APPROVED' } }),
      ])
      budgetActions.value = [...pending.data.items, ...approved.data.items]
    }
  } finally { loading.value = false }
}

async function doSuggest() {
  sugLoading.value = true
  try {
    const { data } = await api.post('/ads/suggest', sug)
    sugResult.value = data
  } finally { sugLoading.value = false }
}

async function createFromSug() {
  await api.post('/ads/campaigns', {
    name: sugResult.value.name, platform: sugResult.value.platform,
    product_id: sugResult.value.product_id, keywords: sugResult.value.keywords,
    budget: sugResult.value.budget,
  })
  ElMessage.success('广告组已创建（草稿）')
  sugDialog.value = false
  sugResult.value = {}
  load()
}

async function optimize(row) {
  const { data } = await api.post(`/ads/campaigns/${row.id}/optimize`)
  if (data.status === 'PENDING_APPROVAL') {
    ElMessage.success(`已提交预算审批 #${data.action_id}：${data.old_budget} → ${data.new_budget}`)
  } else {
    ElMessage.info(data.reason)
  }
  load()
}

async function decideAction(row, approve) {
  const verb = approve ? '批准' : '拒绝'
  const { value } = await ElMessageBox.prompt(`请输入${verb}依据（将记入 Action 审计）`,
    `${verb}预算调整 #${row.id}`, { inputPattern: /\S+/, inputErrorMessage: '依据不能为空' })
  await api.post(`/actions/${row.id}/${approve ? 'approve' : 'reject'}`, { note: value })
  ElMessage.success(`已${verb}预算调整 #${row.id}`)
  load()
}

async function executeAction(row) {
  await ElMessageBox.confirm(`确定执行活动 #${row.target_id} 的预算调整？`, '执行已批准的 Action',
    { type: 'warning' })
  const { data } = await api.post(`/actions/${row.id}/execute`)
  if (data.status === 'SUCCESS') ElMessage.success('预算已调整')
  else ElMessage.warning(data.outcome?.error || '执行失败，请重新提交建议')
  load()
}

onMounted(load)
</script>
