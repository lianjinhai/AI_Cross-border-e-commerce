<template>
  <div class="page">
    <JourneyJ0Bar />
    <PageHeader
      title="供应商库"
      subtitle="私域供应链伙伴 · AI 评分 · 补货预警 · 货源匹配"
    >
      <template #actions>
        <el-button @click="router.push('/app/supply/purchases')">采购单管理</el-button>
        <el-button @click="router.push('/app/settlements')">应付账龄 / 结算</el-button>
        <el-button v-if="writable" type="primary" @click="openCreate">新增源头工厂</el-button>
      </template>
    </PageHeader>

    <el-alert
      type="info" :closable="false" class="mb16"
      title="工厂网络已独立分组"
      description="机会匹配历史与工厂门户账号管理归入「货源中心 · 工厂门户」分组；本页账龄入口与结算页同口径（同一结算汇总端点）。"
    />

    <el-row :gutter="16">
      <el-col :span="15">
        <FormSection title="私域供应链伙伴" description="评分由 AI 综合评估（价格/时效/稳定性）">
          <DataTable :columns="supplierColumns" :loader="loadSuppliers">
            <template #cell-verification_status="{ row }">
              <el-tag size="small" :type="row.verification_status === 'verified' ? 'success' : 'warning'">
                {{ row.verification_status || 'candidate' }}
              </el-tag>
            </template>
            <template #cell-score_total="{ row }">
              <el-progress
                v-if="row.score_total != null"
                :percentage="row.score_total"
                :color="row.score_total > 75 ? 'var(--color-success)' : 'var(--color-warning)'"
              />
              <el-button v-else-if="writable" link type="primary" size="small" @click="score(row)">
                AI 评分
              </el-button>
              <span v-else>—</span>
            </template>
            <template #cell-actions="{ row }">
              <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
            </template>
          </DataTable>
        </FormSection>
      </el-col>
      <el-col :span="9">
        <FormSection title="补货预警（AI 销量预测）">
          <template #extra>
            <el-button size="small" type="primary" :loading="fcLoading" @click="loadForecast">
              刷新预测
            </el-button>
          </template>
          <el-table :data="shortages" size="small" v-loading="fcLoading">
            <el-table-column prop="title" label="商品" show-overflow-tooltip />
            <el-table-column prop="weekly_demand" label="周需求" width="70" />
            <el-table-column prop="onhand" label="在手" width="60" />
            <el-table-column label="风险" width="80">
              <template #default="{ row }"><StatusBadge :status="row.shortage_risk" /></template>
            </el-table-column>
            <el-table-column prop="suggest_restock_qty" label="建议补货" width="80" />
            <template #empty><EmptyState reason="NO_DATA" hint="暂无缺货风险" /></template>
          </el-table>
        </FormSection>
      </el-col>
    </el-row>

    <!-- 供应商详情抽屉 -->
    <el-drawer v-model="drawer" :title="current.name || '供应商详情'" size="var(--drawer-w-md)">
      <template v-if="current.id">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="地区">{{ current.region || '—' }}</el-descriptions-item>
          <el-descriptions-item label="平台评分">{{ current.rating ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="发货天数">{{ current.ship_days ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="稳定性">{{ current.stability || '—' }}</el-descriptions-item>
          <el-descriptions-item label="工厂类型">{{ current.supplier_type || '—' }}</el-descriptions-item>
          <el-descriptions-item label="核验状态">{{ current.verification_status || 'candidate' }}</el-descriptions-item>
        </el-descriptions>
        <template v-if="current.score">
          <h4>AI 综合评分（{{ current.score.total }}）</h4>
          <el-alert
            v-for="(reason, i) in current.score.reasons || []" :key="i"
            :title="reason" type="info" :closable="false" class="mb8"
          />
        </template>
        <h4>货源报价（{{ (current.offers || []).length }}）</h4>
        <el-table :data="current.offers || []" size="small">
          <el-table-column prop="product_id" label="商品ID" width="80" />
          <el-table-column prop="price" label="采购价¥" width="100" />
          <el-table-column prop="ship_days" label="发货天" width="80" />
          <el-table-column prop="moq" label="起订" width="70" />
          <template #empty><EmptyState reason="NO_DATA" /></template>
        </el-table>
      </template>
    </el-drawer>

    <!-- 新增供应商 -->
    <el-dialog v-model="dialog" title="新增供应商" width="480px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="地区"><el-input v-model="form.region" /></el-form-item>
        <el-form-item label="平台评分">
          <el-input-number v-model="form.rating" :min="0" :max="5" :step="0.1" />
        </el-form-item>
        <el-form-item label="发货天数">
          <el-input-number v-model="form.ship_days" :min="1" :max="30" />
        </el-form-item>
        <el-form-item label="能力标签">
          <el-input v-model="form.capabilityText" placeholder="针织,小单快反,印花" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="create">保存</el-button>
      </template>
    </el-dialog>

    <!-- 货源匹配（真实端点 POST /suppliers/match） -->
    <el-dialog v-model="matchDialog" title="货源匹配" width="520px">
      <div class="match-bar">
        <el-select v-model="matchProductId" filterable placeholder="选择商品池商品" class="match-bar__select">
          <el-option
            v-for="p in productOptions" :key="p.id"
            :label="`#${p.id} ${p.title}`" :value="p.id"
          />
        </el-select>
        <el-button type="primary" :loading="matchLoading" :disabled="!matchProductId" @click="match">
          分析最优货源
        </el-button>
      </div>
      <el-descriptions v-if="matchResult" :column="1" border size="small">
        <el-descriptions-item label="最优货源">
          {{ matchResult.supplier_name || matchResult.supplier?.name || '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="采购价¥">
          {{ matchResult.price ?? matchResult.expected_price ?? '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="匹配分">{{ matchResult.total_score ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="说明">
          {{ matchResult.reason || (matchResult.gaps || []).join('；') || '—' }}
        </el-descriptions-item>
      </el-descriptions>
      <EmptyState v-else reason="NO_MATCH" hint="选择商品后分析最优货源" />
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import JourneyJ0Bar from '../../components/JourneyJ0Bar.vue'
import FormSection from '../../components/FormSection.vue'
import DataTable from '../../components/DataTable.vue'
import EmptyState from '../../components/EmptyState.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import { can } from '../../permissions/permissions'
import {
  fetchSuppliers, fetchSupplier, createSupplier, scoreSupplier, fetchForecast, matchBest,
} from '../../api/domains/suppliers'
import { fetchProducts } from '../../api/domains/products'

const router = useRouter()
const writable = can('supply:write')

const supplierColumns = [
  { prop: 'name', label: '供应商', minWidth: 160 },
  { prop: 'region', label: '地区', width: 80 },
  { prop: 'verification_status', label: '核验', width: 90 },
  { prop: 'rating', label: '评分', width: 70 },
  { prop: 'ship_days', label: '发货天', width: 75 },
  { prop: 'score_total', label: '综合分', width: 140 },
  { prop: 'actions', label: '操作', width: 70, fixed: 'right' },
]

const shortages = ref([])
const fcLoading = ref(false)
const drawer = ref(false)
const current = ref({})
const dialog = ref(false)
const saving = ref(false)
const form = reactive({ name: '', region: '', rating: 4.5, ship_days: 7, capabilityText: '' })
const matchDialog = ref(false)
const matchProductId = ref(null)
const matchResult = ref(null)
const matchLoading = ref(false)
const productOptions = ref([])

async function loadSuppliers() {
  const data = await fetchSuppliers()
  const items = data.items || []
  return { items, total: items.length }
}

/** 解包预测结果：部分通道包 context_patch，缺省 shortages 为空数组（不伪造）。 */
async function loadForecast() {
  fcLoading.value = true
  try {
    const data = await fetchForecast()
    const source = data?.context_patch || data || {}
    shortages.value = source.shortages || data?.shortages || []
  } finally {
    fcLoading.value = false
  }
}

async function score(row) {
  const result = await scoreSupplier(row.id)
  ElMessage.success(`${row.name} 综合评分 ${result.total ?? '已生成'}`)
  suppliersVersion.value += 1
}

async function openDetail(row) {
  current.value = await fetchSupplier(row.id)
  drawer.value = true
}

function openCreate() {
  Object.assign(form, { name: '', region: '', rating: 4.5, ship_days: 7, capabilityText: '' })
  dialog.value = true
}

async function create() {
  if (!form.name) return ElMessage.warning('请填写供应商名称')
  saving.value = true
  try {
    await createSupplier({
      name: form.name,
      region: form.region,
      rating: form.rating,
      ship_days: form.ship_days,
      capabilities: form.capabilityText.split(/[,，]/).map((x) => x.trim()).filter(Boolean),
    })
    ElMessage.success('已创建')
    dialog.value = false
    suppliersVersion.value += 1
  } finally {
    saving.value = false
  }
}

async function match() {
  matchLoading.value = true
  try {
    matchResult.value = await matchBest(matchProductId.value)
  } finally {
    matchLoading.value = false
  }
}

onMounted(async () => {
  await loadForecast()
  if (matchDialog.value) return
  try {
    const data = await fetchProducts({ page: 1 })
    productOptions.value = data.items || []
  } catch { productOptions.value = [] }
})
</script>

<style scoped>
.match-bar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.match-bar__select {
  flex: 1;
}
.forecast-bar {
  margin-bottom: var(--space-2);
  display: flex;
  justify-content: flex-end;
}
.mb8 {
  margin-bottom: var(--space-2);
}
</style>
