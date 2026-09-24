<template>
  <div class="page" v-loading="loading">
    <!-- 合规员视角说明（角色界面差异化的核心：让职责一眼可见） -->
    <el-alert type="info" :closable="false" class="mb16"
      title="合规工作台：待审批队列 · 高风险商品 · 平台规则状态 · 发起检测" />

    <el-row :gutter="16" class="mb16">
      <el-col :span="6" v-for="k in kpis" :key="k.label">
        <el-card class="kpi-card" shadow="hover">
          <div class="kpi-label">{{ k.label }}</div>
          <div class="kpi-value" :style="{ color: k.color }">{{ k.value }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mb16">
      <el-col :span="14">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>待我审批（{{ queue.length }} 条）</span>
              <el-button size="small" @click="loadQueue">刷新</el-button>
            </div>
          </template>
          <el-table :data="queue" size="small" max-height="360"
            empty-text="暂无待审批的 Listing——复核 Agent 判定需人工确认的会出现在这里">
            <el-table-column prop="listing_id" label="Listing" width="80" />
            <el-table-column prop="listing_title" label="标题" min-width="180" show-overflow-tooltip />
            <el-table-column prop="platform" label="平台" width="90" />
            <el-table-column label="需人工原因" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">{{ (row.reasons || []).join('；') }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button v-if="canApprove" size="small" type="success" @click="approve(row)">放行</el-button>
                <el-button v-if="canApprove" size="small" type="danger" @click="reject(row)">驳回</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card class="mb16">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>高风险商品（{{ highRisk.length }} 条）</span>
              <el-button size="small" @click="loadRisk">刷新</el-button>
            </div>
          </template>
          <el-table :data="highRisk" size="small" max-height="200"
            empty-text="暂无高风险报告">
            <el-table-column prop="id" label="报告" width="70" />
            <el-table-column label="对象" width="110">
              <template #default="{ row }">
                {{ row.target_type === 'product' ? `商品#${row.product_id}` : `Listing#${row.listing_id}` }}
              </template>
            </el-table-column>
            <el-table-column label="合规分" width="90">
              <template #default="{ row }">
                <el-tag size="small" type="danger">{{ row.score }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="问题" show-overflow-tooltip>
              <template #default="{ row }">
                {{ (row.issues || []).map(i => i.detail).join('；') || '—' }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>平台规则状态</span>
              <el-button size="small" @click="loadRules">刷新</el-button>
            </div>
          </template>
          <el-table :data="rules" size="small" max-height="200">
            <el-table-column prop="platform" label="平台" width="90" />
            <el-table-column prop="version" label="规则版本" width="110" />
            <el-table-column label="标题上限" width="90">
              <template #default="{ row }">{{ row.summary?.title_max ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="违禁词" width="80">
              <template #default="{ row }">{{ row.summary?.banned_words_count ?? '—' }}</template>
            </el-table-column>
          </el-table>
          <div class="muted" style="margin-top:8px;font-size:12px">
            规则超 30 天未更新时，复核 Agent 会要求人工确认（避免按过期规则放行）
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card>
      <template #header>发起合规检测</template>
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
        <el-radio-group v-model="checkForm.target_type">
          <el-radio-button value="product">商品</el-radio-button>
          <el-radio-button value="listing">Listing</el-radio-button>
        </el-radio-group>
        <el-input-number v-model="checkForm.ref_id" :min="1" />
        <el-button type="primary" :loading="checking" @click="doCheck">开始检测</el-button>
      </div>
      <el-alert v-if="lastReport.id" style="margin-top:12px" :closable="false"
        :type="lastReport.risk_level === 'high' ? 'error' : lastReport.risk_level === 'mid' ? 'warning' : 'success'"
        :title="`检测完成：风险 ${lastReport.risk_level}，合规分 ${lastReport.score}`"
        :description="(lastReport.issues || []).map(i => i.detail).join('；') || '未发现问题'" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'
import { can, canApprove } from '../permissions'

const loading = ref(false)
const queue = ref([])
const highRisk = ref([])
const rules = ref([])
const checking = ref(false)
const lastReport = ref({})
const checkForm = reactive({ target_type: 'product', ref_id: 1 })

const kpis = computed(() => [
  { label: '待我审批', value: queue.value.length, color: queue.value.length ? '#E6A23C' : '#67C23A' },
  { label: '高风险商品', value: highRisk.value.length, color: highRisk.value.length ? '#F56C6C' : '#67C23A' },
  { label: '平台规则包', value: rules.value.length, color: '#409EFF' },
  { label: '可发起检测', value: can('compliance:check') ? '是' : '否', color: '#909399' },
])

async function loadQueue() {
  try {
    const { data } = await api.get('/listings/review-queue', { params: { status: 'manual_required' } })
    queue.value = data.items || []
  } catch { /* 全局拦截器已提示 */ }
}

async function loadRisk() {
  try {
    const { data } = await api.get('/compliance/reports', {
      params: { risk_level: 'high', page_size: 20 },
    })
    highRisk.value = data.items || []
  } catch { /* ignore */ }
}

async function loadRules() {
  try {
    const { data } = await api.get('/shops/platform_rules')
    rules.value = data.items || []
  } catch { /* ignore */ }
}

async function approve(row) {
  await ElMessageBox.confirm(`确定放行 Listing #${row.listing_id}？`, '合规放行', { type: 'info' })
  await api.post(`/listings/${row.listing_id}/review/approve`, { note: '合规工作台人工放行' })
  ElMessage.success('已放行')
  loadQueue()
}

async function reject(row) {
  const { value } = await ElMessageBox.prompt('请输入驳回理由（将记入复核审计）', '合规驳回',
    { inputPlaceholder: '如：标题命中品牌词，需修改后重新提交' })
  await api.post(`/listings/${row.listing_id}/review`, { decision: 'rejected', note: value || '' })
  ElMessage.success('已驳回')
  loadQueue()
}

async function doCheck() {
  checking.value = true
  try {
    const { data } = await api.post('/compliance/check', checkForm)
    lastReport.value = data
    ElMessage.success(`检测完成：风险 ${data.risk_level}，合规分 ${data.score}`)
    loadRisk()
  } finally { checking.value = false }
}

onMounted(() => {
  loading.value = true
  Promise.all([loadQueue(), loadRisk(), loadRules()]).finally(() => { loading.value = false })
})
</script>
