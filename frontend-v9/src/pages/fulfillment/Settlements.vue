<template>
  <div class="page">
    <PageHeader
      title="账期结算"
      subtitle="生成 → 确认 → 付款 状态机 · 应付账龄与供应商页同口径"
    >
      <template #actions>
        <el-button v-if="writable" type="primary" @click="openGen">按供应商生成对账单</el-button>
      </template>
    </PageHeader>

    <!-- 应付账龄总览（与供应商页账龄入口同口径：同一结算汇总端点） -->
    <FormSection title="应付账龄总览（按供应商）" description="与「供应商库 → 应付账龄」同口径（同一端点），仅在本页维护">
      <el-table v-loading="sumLoading" :data="summary" size="small" :row-class-name="agingRowClass">
        <el-table-column prop="supplier_name" label="供应商" min-width="140" show-overflow-tooltip />
        <el-table-column prop="settlement_days" label="账期(天)" width="90" />
        <el-table-column prop="unsettled_count" label="未结算笔数" width="100" />
        <el-table-column label="未结算金额" width="120">
          <template #default="{ row }">¥{{ Number(row.unsettled_amount || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="overdue_count" label="逾期笔数" width="90" />
        <el-table-column label="逾期金额" width="120">
          <template #default="{ row }">¥{{ Number(row.overdue_amount || 0).toFixed(2) }}</template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="暂无应付数据" /></template>
      </el-table>
    </FormSection>

    <FormSection title="结算单状态机" description="已付款对账单为终态，不可再编辑">
      <div class="flow">
        <template v-for="(s, i) in SETTLE_FLOW" :key="s">
          <el-tag v-if="i > 0" type="info" effect="plain">→</el-tag>
          <el-tag :type="settleStatusTag(s).type">{{ settleStatusTag(s).label }}</el-tag>
        </template>
      </div>
    </FormSection>

    <FormSection title="结算单列表">
      <el-table v-loading="loading" :data="items" size="small">
        <el-table-column prop="settle_no" label="结算单号" width="170" show-overflow-tooltip />
        <el-table-column prop="supplier_name" label="供应商" min-width="130" show-overflow-tooltip />
        <el-table-column label="账期区间" width="200">
          <template #default="{ row }">
            {{ (row.period_start || '').slice(0, 10) }} ~ {{ (row.period_end || '').slice(0, 10) }}
          </template>
        </el-table-column>
        <el-table-column prop="po_count" label="采购单数" width="90" />
        <el-table-column label="应付总额" width="120">
          <template #default="{ row }">¥{{ Number(row.total_amount || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="settleStatusTag(row.status).type">
              {{ settleStatusTag(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="付款时间" width="160">
          <template #default="{ row }">{{ row.paid_at || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              v-for="act in settleActions(row.status)" :key="act.status"
              v-show="writable" :type="act.type" link size="small"
              @click="onTransition(row, act)"
            >
              {{ act.label }}
            </el-button>
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="暂无结算单" /></template>
      </el-table>
      <el-pagination
        class="pager" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" :current-page="page" @current-change="onPageChange"
      />
    </FormSection>

    <!-- 按供应商生成对账单（前置选择器加强：展示未结算笔数/金额） -->
    <el-dialog v-model="genDialog" title="按供应商生成对账单" width="480px">
      <el-form label-width="90px">
        <el-form-item label="供应商" required>
          <el-select v-model="genSupplierId" filterable placeholder="请选择供应商" style="width: 100%">
            <el-option
              v-for="s in genableSuppliers" :key="s.supplier_id"
              :label="`${s.supplier_name}（未结算 ${s.unsettled_count} 笔 / ¥${Number(s.unsettled_amount || 0).toFixed(2)}）`"
              :value="s.supplier_id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" title="将汇总该供应商所有「已收货且未结算」的采购单，生成一张对账单。" />
      <template #footer>
        <el-button @click="genDialog = false">取消</el-button>
        <el-button type="primary" :loading="genLoading" @click="generate">生成对账单</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import { can } from '../../permissions/permissions'
import {
  fetchSettlements, fetchPayableSummary, generateSettlement, updateSettlement,
} from '../../api/domains/settlements'
import {
  SETTLE_FLOW, settleActions, settleStatusTag,
} from '../../features/fulfillment/settlementStateMachine'

const writable = can('settlement:write')

const summary = ref([])
const sumLoading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const genDialog = ref(false)
const genLoading = ref(false)
const genSupplierId = ref(null)

const genableSuppliers = computed(() => summary.value.filter((s) => s.unsettled_count > 0))

function agingRowClass({ row }) {
  return row.overdue_amount > 0 ? 'aging-overdue' : ''
}

async function loadSummary() {
  sumLoading.value = true
  try {
    summary.value = (await fetchPayableSummary()).items || []
  } finally {
    sumLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const data = await fetchSettlements({ page: page.value })
    items.value = data.items || []
    total.value = Number(data.total ?? items.value.length)
  } finally {
    loading.value = false
  }
}

function onPageChange(next) {
  page.value = next
  load()
}

function openGen() {
  if (!genableSuppliers.value.length) {
    ElMessage.info('当前没有待结算的已收货采购单')
    return
  }
  genSupplierId.value = null
  genDialog.value = true
}

async function generate() {
  if (!genSupplierId.value) return ElMessage.warning('请选择供应商')
  genLoading.value = true
  try {
    const data = await generateSettlement(genSupplierId.value)
    ElMessage.success(`对账单 ${data.settle_no} 已生成`)
    genDialog.value = false
    await Promise.all([loadSummary(), load()])
  } finally {
    genLoading.value = false
  }
}

async function onTransition(row, act) {
  if (act.status === 'confirmed') {
    try {
      await ElMessageBox.confirm(`确认完成结算单 ${row.settle_no} 的对账？`, '确认对账', { type: 'warning' })
    } catch { return }
  } else {
    try {
      await ElMessageBox.confirm(
        `确认将结算单 ${row.settle_no}（¥${Number(row.total_amount || 0).toFixed(2)}）标记为已付款？` +
        '真实打款请在银行/支付宝完成后记录。', '标记已付款', { type: 'warning' })
    } catch { return }
  }
  await updateSettlement(row.id, { status: act.status })
  ElMessage.success(`结算单 ${row.settle_no} 已${settleStatusTag(act.status).label}`)
  load()
}

onMounted(() => { loadSummary(); load() })
</script>

<style scoped>
:deep(.el-table .aging-overdue td.el-table__cell) {
  color: var(--color-danger);
}
.flow {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.pager {
  margin-top: var(--space-3);
  justify-content: flex-end;
}
</style>
