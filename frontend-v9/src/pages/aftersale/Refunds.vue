<template>
  <div class="page">
    <PageHeader title="售后管理" subtitle="退款全状态机 · 时间线可视化 · 支持从订单页预填发起">
      <template #actions>
        <el-button v-if="writable" type="primary" @click="openCreate">发起退款</el-button>
      </template>
      <template #filters>
        <el-select v-model="status" placeholder="状态" clearable style="width: 140px" @change="touch">
          <el-option v-for="(v, s) in REFUND_STATUS" :key="s" :label="v.text" :value="s" />
        </el-select>
      </template>
    </PageHeader>

    <!-- 状态统计卡 -->
    <el-row :gutter="16" class="mb16">
      <el-col v-for="k in statCards" :key="k.key" :span="4">
        <MetricCard :label="k.label" :value="String(stats[k.key] ?? 0)" :loading="statLoading" />
      </el-col>
    </el-row>

    <FormSection title="退款单列表" description="展开行查看状态时间线；仅当前状态可达的操作可见（非法跳转后端 400 拒绝）">
      <el-table v-loading="loading" :data="items" size="small">
        <el-table-column type="expand">
          <template #default="{ row }">
            <AuditTimeline :steps="refundTimeline(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="refund_no" label="退款单号" width="170" show-overflow-tooltip />
        <el-table-column prop="external_no" label="平台单号" width="130" show-overflow-tooltip />
        <el-table-column prop="platform" label="平台" width="90" />
        <el-table-column prop="buyer_name" label="买家" width="100" show-overflow-tooltip />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">{{ REFUND_TYPE[row.type] || row.type }}</template>
        </el-table-column>
        <el-table-column prop="qty" label="数量" width="70" />
        <el-table-column label="金额" width="100">
          <template #default="{ row }">${{ Number(row.amount || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="140" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="refundStatusTag(row.status).type">
              {{ refundStatusTag(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="申请时间" width="160" />
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button
              v-for="act in refundActions(row)" :key="act.action"
              v-show="writable" :type="act.type" link size="small"
              @click="onAction(row, act.action)"
            >
              {{ act.label }}
            </el-button>
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="暂无退款单" /></template>
      </el-table>
      <el-pagination
        class="pager" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" :current-page="page" @current-change="onPageChange"
      />
    </FormSection>

    <!-- 发起退款（支持从订单页带 order_id 预填跳入） -->
    <el-dialog v-model="dialog" title="发起退款" width="480px">
      <el-alert
        v-if="prefillOrderId" type="info" :closable="false" class="mb8"
        :title="`已从订单页带入订单 #${prefillOrderId}`"
      />
      <el-form label-width="90px">
        <el-form-item label="订单ID" required>
          <el-input-number v-model="form.order_id" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="退款不退货" value="refund_only" />
            <el-option label="退货退款" value="return_refund" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量"><el-input-number v-model="form.qty" :min="1" /></el-form-item>
        <el-form-item label="金额($)">
          <el-input-number
            v-model="form.amount" :min="0" :precision="2" :step="1"
            controls-position="right" style="width: 100%"
          />
          <div class="form-tip">留空 = 按订单单价 × 数量自动计算</div>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="form.reason" type="textarea" :rows="2" placeholder="买家申请原因 / 备注" />
        </el-form-item>
        <el-form-item label="回补库存">
          <el-switch v-model="form.restock" />
          <span class="form-tip" style="margin-left: 8px">退货退款且退货入库时回补虚拟库存</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="create">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import MetricCard from '../../components/MetricCard.vue'
import AuditTimeline from '../../components/AuditTimeline.vue'
import { can } from '../../permissions/permissions'
import {
  fetchRefunds, createRefund, updateRefundStatus, receiveReturn, executeRefund,
} from '../../api/domains/refunds'
import {
  REFUND_STATUS, REFUND_TYPE, refundStatusTag, refundActions, refundTimeline,
} from '../../features/aftersale/refundStateMachine'

const writable = can('refund:write')
const route = useRoute()

const statCards = [
  { key: 'pending', label: '待审核' },
  { key: 'approved', label: '已同意' },
  { key: 'returned', label: '已退货' },
  { key: 'refunded', label: '已退款' },
  { key: 'rejected', label: '已拒绝' },
]

const stats = ref({})
const statLoading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const status = ref('')
const dialog = ref(false)
const submitting = ref(false)
const prefillOrderId = Number(route.query.order_id) || null
const form = reactive({ order_id: null, type: 'refund_only', qty: 1, amount: null, reason: '', restock: true })

async function loadStats() {
  statLoading.value = true
  try {
    const data = await fetchRefunds({ page: 1 })
    // 统计口径：取最新一页做概览（后端无统计端点，不伪造全量口径）。
    const counter = {}
    for (const r of data.items || []) counter[r.status] = (counter[r.status] || 0) + 1
    stats.value = counter
  } finally {
    statLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const data = await fetchRefunds({ status: status.value, page: page.value })
    items.value = data.items || []
    total.value = Number(data.total ?? items.value.length)
  } finally {
    loading.value = false
  }
}

function touch() {
  page.value = 1
  load()
}

function onPageChange(next) {
  page.value = next
  load()
}

function refresh() {
  load()
  loadStats()
}

async function onAction(row, action) {
  if (action === 'approve') {
    try {
      await ElMessageBox.confirm(
        `确定同意退款单 ${row.refund_no}（$${Number(row.amount || 0).toFixed(2)}）？`,
        '同意退款', { type: 'warning' })
    } catch { return }
    await updateRefundStatus(row.id, { status: 'approved' })
    ElMessage.success(`退款单 ${row.refund_no} 已同意`)
  } else if (action === 'reject') {
    let reason = ''
    try {
      const { value } = await ElMessageBox.prompt('请输入拒绝原因', `拒绝退款 ${row.refund_no}`, {
        type: 'warning',
        inputPlaceholder: '拒绝原因（将记录到退款单备注）',
        inputValidator: (v) => (v && v.trim() ? true : '请输入拒绝原因'),
      })
      reason = value.trim()
    } catch { return }
    await updateRefundStatus(row.id, { status: 'rejected', note: reason })
    ElMessage.success(`退款单 ${row.refund_no} 已拒绝`)
  } else if (action === 'receive') {
    try {
      await ElMessageBox.confirm(`确认已收到 ${row.refund_no} 的退货商品并入库？`, '退货入库', { type: 'warning' })
    } catch { return }
    const data = await receiveReturn(row.id)
    ElMessage.success(`已回补库存 ${data.restocked} 件`)
  } else if (action === 'refund') {
    try {
      await ElMessageBox.confirm(
        `确认执行退款 $${Number(row.amount || 0).toFixed(2)}？订单将联动为已退款。`,
        '执行退款', { type: 'warning' })
    } catch { return }
    await executeRefund(row.id)
    ElMessage.success('退款执行成功，订单将联动为已退款')
  }
  refresh()
}

function openCreate() {
  Object.assign(form, {
    order_id: prefillOrderId, type: 'refund_only', qty: 1, amount: null, reason: '', restock: true,
  })
  dialog.value = true
}

async function create() {
  if (!form.order_id) return ElMessage.warning('请填写订单ID')
  submitting.value = true
  try {
    const data = await createRefund({
      order_id: form.order_id,
      type: form.type,
      qty: form.qty,
      amount: form.amount ?? null,
      reason: form.reason,
      restock: form.restock,
    })
    ElMessage.success(`退款单 ${data.refund_no} 已创建，等待审核`)
    dialog.value = false
    refresh()
  } finally {
    submitting.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.form-tip {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  line-height: 1.6;
}
.pager {
  margin-top: var(--space-3);
  justify-content: flex-end;
}
.mb8 {
  margin-bottom: var(--space-2);
}
.mb16 {
  margin-bottom: var(--space-4);
}
</style>
