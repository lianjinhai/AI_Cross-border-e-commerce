<template>
  <div class="page">
    <PageHeader title="广告增长" subtitle="活动 ROI · 预算审批-执行-结果三态 · AI 选词一键应用">
      <template #actions>
        <el-button v-if="writable" type="primary" @click="sugDialog = true">AI 选词建组</el-button>
      </template>
    </PageHeader>

    <el-row :gutter="16" class="mb16">
      <el-col :span="6"><MetricCard label="总花费" :value="money(summary.total_spend)" /></el-col>
      <el-col :span="6"><MetricCard label="总收入" :value="money(summary.total_revenue)" /></el-col>
      <el-col :span="6">
        <MetricCard
          label="广告 ROI" :value="summary.roi ?? '—'"
          :color="Number(summary.roi) > 2 ? 'var(--color-success)' : Number(summary.roi) > 0.8 ? 'var(--color-warning)' : 'var(--color-danger)'"
        />
      </el-col>
      <el-col :span="6"><MetricCard label="平均 CTR" :value="summary.avg_ctr != null ? `${summary.avg_ctr}%` : '—'" /></el-col>
    </el-row>

    <FormSection title="广告活动" description="ROI 汇总与活动明细同源（同一 ROI 报告端点）">
      <el-table v-if="campaigns.length" v-loading="loading" :data="campaigns" size="small">
        <el-table-column prop="id" label="ID" width="55" />
        <el-table-column prop="name" label="活动" min-width="180" show-overflow-tooltip />
        <el-table-column prop="platform" label="平台" width="90" />
        <el-table-column prop="budget" label="日预算$" width="90" />
        <el-table-column prop="spend" label="花费$" width="90" />
        <el-table-column prop="revenue" label="收入$" width="90" />
        <el-table-column label="ROI" width="90">
          <template #default="{ row }">
            <el-tag :type="row.roi > 2 ? 'success' : row.roi > 0.8 ? 'warning' : 'danger'" size="small">
              {{ row.roi }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ctr" label="CTR%" width="80" />
        <el-table-column prop="cvr" label="CVR%" width="80" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button v-if="writable" size="small" type="primary" @click="optimize(row)">预算优化</el-button>
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="暂无广告活动" /></template>
      </el-table>
      <EmptyState
        v-else-if="!loading" reason="NOT_CONFIGURED"
        hint="尚未配置广告投放（无店铺授权或未创建活动）；可先用「AI 选词建组」创建活动"
      />
    </FormSection>

    <!-- 审批-执行-结果三态（/actions 统一消费） -->
    <ApprovalPanel v-if="writable" class="mt16" title="预算调整审批" :writable="writable" @changed="load" />

    <!-- AI 选词建议（结果一键应用） -->
    <el-dialog v-model="sugDialog" title="AI 选词建议" width="560px" @closed="sugResult = {}">
      <el-form label-width="90px">
        <el-form-item label="商品ID"><el-input-number v-model="sug.product_id" :min="1" /></el-form-item>
        <el-form-item label="平台">
          <el-select v-model="sug.platform">
            <el-option v-for="p in ['facebook', 'google', 'tiktok']" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
      </el-form>
      <template v-if="sugResult.keywords">
        <el-divider>建议关键词</el-divider>
        <el-tag v-for="k in sugResult.keywords" :key="k" type="info" class="kw">{{ k }}</el-tag>
        <p class="sug-reason">{{ sugResult.reason }}</p>
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
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import MetricCard from '../../components/MetricCard.vue'
import ApprovalPanel from '../../components/ApprovalPanel.vue'
import { can, canAny } from '../../permissions/permissions'
import { fetchCampaigns, createCampaign, optimizeCampaign, suggestKeywords } from '../../api/domains/ads'

const writable = canAny('finance:write', 'ai:write')

const campaigns = ref([])
const summary = ref({})
const loading = ref(false)
const sugDialog = ref(false)
const sugLoading = ref(false)
const sugResult = ref({})
const sug = reactive({ product_id: 1, platform: 'facebook' })

function money(value) {
  return value == null ? '—' : `$${Number(value).toFixed(2)}`
}

async function load() {
  loading.value = true
  try {
    const data = await fetchCampaigns()
    campaigns.value = data.campaigns || []
    summary.value = data.summary || {}
  } finally {
    loading.value = false
  }
}

async function doSuggest() {
  sugLoading.value = true
  try {
    sugResult.value = await suggestKeywords(sug)
  } finally {
    sugLoading.value = false
  }
}

async function createFromSug() {
  await createCampaign({
    name: sugResult.value.name,
    platform: sugResult.value.platform,
    product_id: sugResult.value.product_id,
    keywords: sugResult.value.keywords,
    budget: sugResult.value.budget,
  })
  ElMessage.success('广告组已创建（草稿）')
  sugDialog.value = false
  sugResult.value = {}
  load()
}

async function optimize(row) {
  const data = await optimizeCampaign(row.id)
  if (data.approval_required) {
    ElMessage.success(`已提交预算审批 #${data.action_id}：${data.old_budget} → ${data.new_budget}（下方审批面板可见三态）`)
  } else {
    ElMessage.info(data.reason || '本次无需调整预算')
  }
  load()
}

onMounted(load)
</script>

<style scoped>
.mb16 {
  margin-bottom: var(--space-4);
}
.mt16 {
  margin-top: var(--space-4);
}
.kw {
  margin: 0 6px 6px 0;
}
.sug-reason {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>
