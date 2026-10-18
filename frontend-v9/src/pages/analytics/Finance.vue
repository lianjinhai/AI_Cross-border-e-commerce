<template>
  <div class="page">
    <PageHeader title="财务台账" subtitle="维护交易日汇率、订单行与费用，并核对平台结算 · 全部行内编辑" />

    <el-alert
      type="info" show-icon :closable="false" class="mb16"
      title="财务事实工作台"
      description="所有数据将进入统一 GMV、净收入和贡献利润口径；缺汇率的金额会被排除而非静默混入。"
    />

    <el-tabs v-model="tab">
      <!-- 汇率（行内新增） -->
      <el-tab-pane label="汇率" name="fx">
        <FormSection title="汇率维护" description="录入交易发生日之前有效的兑 USD 汇率">
          <el-form :inline="true">
            <el-form-item label="币种">
              <el-input v-model="fxForm.base_currency" style="width: 90px" />
            </el-form-item>
            <el-form-item label="兑 USD">
              <el-input-number v-model="fxForm.rate" :min="0.000001" :precision="6" />
            </el-form-item>
            <el-form-item label="生效时间">
              <el-date-picker v-model="fxForm.effective_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" />
            </el-form-item>
            <el-form-item>
              <el-button v-if="writable" type="primary" :loading="saving" @click="saveFx">新增汇率</el-button>
            </el-form-item>
          </el-form>
          <el-table v-loading="loading" :data="fxItems" size="small">
            <el-table-column prop="base_currency" label="基础币种" />
            <el-table-column prop="quote_currency" label="报价币种" />
            <el-table-column prop="rate" label="汇率" />
            <el-table-column prop="effective_at" label="生效时间" />
            <el-table-column prop="source" label="来源" />
            <template #empty><EmptyState reason="NO_DATA" hint="暂无汇率" /></template>
          </el-table>
        </FormSection>
      </el-tab-pane>

      <!-- 订单明细与费用（行内编辑表格，取代原 2 个弹窗） -->
      <el-tab-pane label="订单明细与费用" name="orders">
        <FormSection title="加载订单财务明细">
          <div class="load-bar">
            <el-input-number v-model="orderId" :min="1" placeholder="订单 ID" />
            <el-button type="primary" @click="loadOrder">加载财务明细</el-button>
          </div>
        </FormSection>
        <template v-if="detail.order">
          <el-descriptions :column="4" border size="small" class="mb16">
            <el-descriptions-item label="订单号">{{ detail.order.external_no }}</el-descriptions-item>
            <el-descriptions-item label="平台">{{ detail.order.platform }}</el-descriptions-item>
            <el-descriptions-item label="金额">{{ detail.order.currency }} {{ detail.order.amount }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ detail.order.status }}</el-descriptions-item>
          </el-descriptions>
          <el-row :gutter="16">
            <el-col :span="12">
              <FormSection title="订单行">
                <el-table :data="detail.lines" size="small">
                  <el-table-column prop="external_line_no" label="行号" />
                  <el-table-column prop="sku" label="SKU" />
                  <el-table-column prop="title" label="标题" show-overflow-tooltip />
                  <el-table-column prop="qty" label="数量" width="60" />
                  <el-table-column prop="unit_price" label="单价" width="80" />
                  <el-table-column prop="product_cost" label="成本" width="80" />
                  <template #empty><EmptyState reason="NO_DATA" /></template>
                </el-table>
                <!-- 行内新增编辑行 -->
                <el-table v-if="writable" :data="[lineDraft]" size="small" class="inline-edit">
                  <el-table-column label="行号*">
                    <template #default="{ row }"><el-input v-model="row.external_line_no" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="SKU">
                    <template #default="{ row }"><el-input v-model="row.sku" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="数量">
                    <template #default="{ row }"><el-input-number v-model="row.qty" :min="1" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="单价">
                    <template #default="{ row }"><el-input-number v-model="row.unit_price" :min="0" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="成本">
                    <template #default="{ row }"><el-input-number v-model="row.product_cost" :min="0" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="币种" width="90">
                    <template #default="{ row }"><el-input v-model="row.currency" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="操作" width="80">
                    <template #default>
                      <el-button type="primary" size="small" @click="saveLine">保存</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </FormSection>
            </el-col>
            <el-col :span="12">
              <FormSection title="费用">
                <el-table :data="detail.fees" size="small">
                  <el-table-column prop="fee_type" label="类型" />
                  <el-table-column prop="amount" label="金额" />
                  <el-table-column prop="currency" label="币种" />
                  <el-table-column prop="occurred_at" label="发生时间" />
                  <template #empty><EmptyState reason="NO_DATA" /></template>
                </el-table>
                <el-table v-if="writable" :data="[feeDraft]" size="small" class="inline-edit">
                  <el-table-column label="类型">
                    <template #default="{ row }">
                      <el-select v-model="row.fee_type" size="small">
                        <el-option v-for="x in FEE_TYPES" :key="x" :label="x" :value="x" />
                      </el-select>
                    </template>
                  </el-table-column>
                  <el-table-column label="金额">
                    <template #default="{ row }"><el-input-number v-model="row.amount" :precision="2" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="币种" width="90">
                    <template #default="{ row }"><el-input v-model="row.currency" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="操作" width="80">
                    <template #default>
                      <el-button type="primary" size="small" @click="saveFee">保存</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </FormSection>
            </el-col>
          </el-row>
        </template>
        <EmptyState v-else reason="NO_MATCH" hint="输入订单 ID 加载财务明细" />
      </el-tab-pane>

      <!-- 平台结算对账（行内录入，取代原弹窗；幂等保存） -->
      <el-tab-pane label="平台结算对账" name="settlements">
        <FormSection title="平台结算单" description="按外部结算单号幂等保存；差异 > 0 的结算单需人工核对">
          <el-alert
            v-if="unreconciled" type="warning" :closable="false" class="mb8"
            :title="`${unreconciled} 笔结算存在差异`"
          />
          <el-table v-loading="loading" :data="settlements" size="small">
            <el-table-column prop="platform" label="平台" />
            <el-table-column prop="external_settlement_no" label="结算单号" />
            <el-table-column prop="gross_amount" label="交易总额" />
            <el-table-column prop="fee_amount" label="费用" />
            <el-table-column prop="refund_amount" label="退款" />
            <el-table-column prop="expected_net" label="应结" />
            <el-table-column prop="net_amount" label="实结" />
            <el-table-column prop="variance" label="差异" />
            <el-table-column label="结果">
              <template #default="{ row }">
                <el-tag :type="row.reconciled ? 'success' : 'danger'" size="small">
                  {{ row.reconciled ? '已平' : '待核对' }}
                </el-tag>
              </template>
            </el-table-column>
            <template #empty><EmptyState reason="NO_DATA" hint="暂无结算单" /></template>
          </el-table>
          <el-table v-if="writable" :data="[settleDraft]" size="small" class="inline-edit">
            <el-table-column label="平台*">
              <template #default="{ row }"><el-input v-model="row.platform" size="small" /></template>
            </el-table-column>
            <el-table-column label="结算单号*">
              <template #default="{ row }"><el-input v-model="row.external_settlement_no" size="small" /></template>
            </el-table-column>
            <el-table-column label="总额">
              <template #default="{ row }"><el-input-number v-model="row.gross_amount" :min="0" size="small" /></template>
            </el-table-column>
            <el-table-column label="费用">
              <template #default="{ row }"><el-input-number v-model="row.fee_amount" :min="0" size="small" /></template>
            </el-table-column>
            <el-table-column label="退款">
              <template #default="{ row }"><el-input-number v-model="row.refund_amount" :min="0" size="small" /></template>
            </el-table-column>
            <el-table-column label="实结">
              <template #default="{ row }"><el-input-number v-model="row.net_amount" size="small" /></template>
            </el-table-column>
            <el-table-column label="币种" width="90">
              <template #default="{ row }"><el-input v-model="row.currency" size="small" /></template>
            </el-table-column>
            <el-table-column label="操作" width="110">
              <template #default>
                <el-button type="primary" size="small" @click="saveSettlement">幂等保存</el-button>
              </template>
            </el-table-column>
          </el-table>
        </FormSection>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import { can } from '../../permissions/permissions'
import {
  fetchFxRates, createFxRate, fetchOrderFinance, createOrderLine, createOrderFee,
  fetchReconciliation, savePlatformSettlement,
} from '../../api/domains/finance'

const writable = can('finance:write')
const FEE_TYPES = ['platform_fee', 'payment_fee', 'shipping', 'tax', 'advertising', 'other']

// 默认落到中央台账「订单明细与费用」，而非汇率维护（fx）标签；不误导为「真实利润」。
const tab = ref('orders')
const loading = ref(false)
const saving = ref(false)
const fxItems = ref([])
const settlements = ref([])
const unreconciled = ref(0)
const orderId = ref(null)
const detail = ref({})

const fxForm = reactive({
  base_currency: 'CNY', rate: 0.14,
  effective_at: new Date().toISOString().slice(0, 19), quote_currency: 'USD', source: 'manual',
})
const lineDraft = reactive({
  external_line_no: '', sku: '', title: '', qty: 1, unit_price: 0, product_cost: 0, currency: 'USD',
})
const feeDraft = reactive({
  fee_type: 'platform_fee', amount: 0, currency: 'USD', source: 'manual',
})
const settleDraft = reactive({
  platform: '', external_settlement_no: '', gross_amount: 0, fee_amount: 0,
  refund_amount: 0, net_amount: 0, currency: 'USD', status: 'pending',
})

async function load() {
  loading.value = true
  try {
    const [fx, recon] = await Promise.all([fetchFxRates(), fetchReconciliation()])
    fxItems.value = fx.items || []
    settlements.value = recon.items || []
    unreconciled.value = recon.unreconciled || 0
  } finally {
    loading.value = false
  }
}

async function saveFx() {
  if (!fxForm.base_currency || !fxForm.rate) return ElMessage.warning('请填写币种和汇率')
  saving.value = true
  try {
    await createFxRate(fxForm)
    ElMessage.success('汇率已保存')
    load()
  } finally {
    saving.value = false
  }
}

async function loadOrder() {
  if (!orderId.value) return ElMessage.warning('请输入订单 ID')
  detail.value = await fetchOrderFinance(orderId.value)
}

async function saveLine() {
  if (!lineDraft.external_line_no) return ElMessage.warning('请填写外部行号')
  await createOrderLine(orderId.value, { ...lineDraft })
  ElMessage.success('订单行已保存')
  Object.assign(lineDraft, {
    external_line_no: '', sku: '', title: '', qty: 1, unit_price: 0, product_cost: 0, currency: 'USD',
  })
  await loadOrder()
}

async function saveFee() {
  await createOrderFee(orderId.value, { ...feeDraft })
  ElMessage.success('费用已保存')
  Object.assign(feeDraft, { fee_type: 'platform_fee', amount: 0, currency: 'USD', source: 'manual' })
  await loadOrder()
}

async function saveSettlement() {
  if (!settleDraft.platform || !settleDraft.external_settlement_no) {
    return ElMessage.warning('请填写平台和结算单号')
  }
  await savePlatformSettlement({ ...settleDraft })
  ElMessage.success('结算单已幂等保存')
  Object.assign(settleDraft, {
    platform: '', external_settlement_no: '', gross_amount: 0, fee_amount: 0,
    refund_amount: 0, net_amount: 0, currency: 'USD', status: 'pending',
  })
  load()
}

onMounted(load)
</script>

<style scoped>
.mb16 {
  margin-bottom: var(--space-4);
}
.mb8 {
  margin-bottom: var(--space-2);
}
.load-bar {
  display: flex;
  gap: var(--space-2);
}
.inline-edit {
  margin-top: var(--space-2);
}
</style>
