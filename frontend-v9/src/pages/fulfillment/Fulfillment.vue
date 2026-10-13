<template>
  <div class="page">
    <PageHeader
      title="发货 / 代发 / 备货"
      subtitle="履约员按模式执行 · 备货与代发独立展示 · 采购走既有端点"
    >
      <template #filters>
        <el-radio-group v-model="mode" size="small">
          <el-radio-button value="stocking">备货</el-radio-button>
          <el-radio-button value="dropship">代发</el-radio-button>
          <el-radio-button value="purchase">采购</el-radio-button>
        </el-radio-group>
      </template>
      <template #actions>
        <el-button @click="router.push('/app/orders')">订单工作台</el-button>
        <el-button @click="router.push('/app/supply/purchases')">采购单管理</el-button>
      </template>
    </PageHeader>

    <SectionState :code="queueCode" :error="error" @retry="load">
      <!-- 备货列：平台备货端点未核（§7#6）→ 待接入占位 + 人工处理引导 -->
      <template v-if="mode === 'stocking'">
        <SectionState code="NOT_CONFIGURED" action-text="人工在平台处理">
          <el-card shadow="never">
            <el-alert
              type="info" :closable="false"
              title="平台备货待接入，请人工在平台处理"
              description="平台备货申请端点未核（§7#6）：批准量/备妥量/外部参考号/仓库证据未接入前，本区只读，不出现假进度。可先创建本地采购单（走下方采购列）作为过渡。"
            />
            <div class="stocking-hint">
              过渡方案：在「采购」列创建采购单并登记收货；平台侧备货请在平台后台人工处理，完成后回到订单页登记发运。
            </div>
          </el-card>
        </SectionState>
      </template>

      <!-- 代发列：purchases 中 dropship 子集（真实数据） -->
      <template v-else-if="mode === 'dropship'">
        <el-card shadow="never">
          <div class="queue-card__head">
            <span>代发单（{{ dropshipRows.length }}）</span>
            <el-button size="small" :loading="loading" @click="load">刷新</el-button>
          </div>
          <el-table :data="dropshipRows" size="small" v-loading="loading">
            <el-table-column label="采购单" width="90">
              <template #default="{ row }">
                <EntityLink
                  object-type="purchase" :object-id="row.id"
                  :return-to="returnTo"
                >#{{ row.id }}</EntityLink>
              </template>
            </el-table-column>
            <el-table-column label="供货商" min-width="140">
              <template #default="{ row }">{{ row.supplier || '—' }}</template>
            </el-table-column>
            <el-table-column label="价格" width="130">
              <template #default="{ row }">
                <MoneyValue
                  :value="row.price" :currency="row.currency"
                  estimated
                />
              </template>
            </el-table-column>
            <el-table-column label="数量" width="70">
              <template #default="{ row }">{{ row.qty ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <BusinessStatus :raw="row.status" />
              </template>
            </el-table-column>
            <el-table-column label="下一操作" min-width="160">
              <template #default="{ row }">
                <el-tooltip :content="rowAction(row).reason" :disabled="!rowAction(row).disabled" placement="top">
                  <el-button
                    size="small"
                    :type="rowAction(row).code === 'DROP_SHIP_DELEGATE' ? 'primary' : 'default'"
                    :disabled="rowAction(row).disabled"
                    @click="doPrimary(row, rowAction(row))"
                  >
                    {{ rowAction(row).label }}
                  </el-button>
                </el-tooltip>
              </template>
            </el-table-column>
            <template #empty>
              <EmptyState reason="NO_DATA" hint="暂无代发采购单" />
            </template>
          </el-table>
        </el-card>
      </template>

      <!-- 采购列：purchases 真实数据 -->
      <template v-else>
        <el-card shadow="never">
          <div class="queue-card__head">
            <span>采购单（{{ purchaseRows.length }}）</span>
            <el-button size="small" :loading="loading" @click="load">刷新</el-button>
          </div>
          <el-table :data="purchaseRows" size="small" v-loading="loading">
            <el-table-column label="采购单" width="90">
              <template #default="{ row }">
                <EntityLink
                  object-type="purchase" :object-id="row.id"
                  :return-to="returnTo"
                >#{{ row.id }}</EntityLink>
              </template>
            </el-table-column>
            <el-table-column label="供货商" min-width="140">
              <template #default="{ row }">{{ row.supplier || '—' }}</template>
            </el-table-column>
            <el-table-column label="价格" width="130">
              <template #default="{ row }">
                <MoneyValue
                  :value="row.price" :currency="row.currency"
                  :estimated="!row.currency"
                />
              </template>
            </el-table-column>
            <el-table-column label="下单时间" width="150">
              <template #default="{ row }">{{ row.orderedAt || '—' }}</template>
            </el-table-column>
            <el-table-column label="收货时间" width="150">
              <template #default="{ row }">{{ row.receivedAt || '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <BusinessStatus :raw="row.status" />
              </template>
            </el-table-column>
            <el-table-column label="下一操作" min-width="150">
              <template #default="{ row }">
                <el-tooltip :content="rowAction(row, 'purchase').reason" :disabled="!rowAction(row, 'purchase').disabled" placement="top">
                  <el-button
                    size="small"
                    :type="rowAction(row, 'purchase').code === 'PURCHASE_RECEIVE' ? 'primary' : 'default'"
                    :disabled="rowAction(row, 'purchase').disabled"
                    @click="doPrimary(row, rowAction(row, 'purchase'))"
                  >
                    {{ rowAction(row, 'purchase').label }}
                  </el-button>
                </el-tooltip>
              </template>
            </el-table-column>
            <template #empty>
              <EmptyState reason="NO_DATA" hint="暂无采购单（可从订单工作台或采购单管理创建）" />
            </template>
          </el-table>
        </el-card>
      </template>
    </SectionState>

    <!-- 发运/收货登记（AsyncActionDialog：提交中→成功/失败/409/超时） -->
    <AsyncActionDialog
      v-model="actionDialog"
      :action="pendingAction ? pendingAction.label : ''"
      :context="pendingAction ? pendingAction.context : ''"
      :idempotency-key="pendingAction ? pendingAction.key : ''"
      :done-message="pendingAction ? pendingAction.doneMessage : ''"
      @submit="onSubmit"
      @requery="load"
    />
  </div>
</template>

<script setup>
/**
 * 发货/代发/备货（蓝图 R1 OR-03，包 2）：/app/fulfillment。
 *
 * 数据源：purchases.js（采购已有）；平台备货端点未核（§7#6）→ 备货区"待接入/人工处理"；
 * 代发/采购分列独立展示（备货与代发不得混用同一"创建采购单"动作）；可关联不等同。
 * 物流轨迹待接入（§7#1）→ 发运登记后仅显示登记状态，不渲染轨迹。
 * 纯函数源：shared/fulfillmentQueue.js（三列分列 + 主操作推导 + 备货证据提取）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import BusinessStatus from '../../components/BusinessStatus.vue'
import MoneyValue from '../../components/MoneyValue.vue'
import EntityLink from '../../components/EntityLink.vue'
import AsyncActionDialog from '../../components/AsyncActionDialog.vue'
import { ElMessage } from '../../shared/ui'
import { fetchPurchases, receivePurchase } from '../../api/domains/purchases'
import {
  splitFulfillmentQueues, primaryFulfillAction, purchaseRow,
} from '../../shared/fulfillmentQueue'

const route = useRoute()
const router = useRouter()
const returnTo = computed(() => route.query.return_to || '/app/fulfillment')

const mode = ref('purchase')
const purchases = ref([])
const loading = ref(false)
const error = ref('')

const queues = computed(() => splitFulfillmentQueues(purchases.value))
const dropshipRows = computed(() => queues.value.dropship.map(purchaseRow))
const purchaseRows = computed(() => queues.value.purchase.map(purchaseRow))

/** 11 态：队列主体；备货列独立走 NOT_CONFIGURED。 */
const queueCode = computed(() => {
  if (error.value) return 'ERROR'
  if (loading.value) return 'LOADING'
  if (!purchases.value.length && mode.value !== 'stocking') return 'EMPTY_NEW'
  return 'ready'
})

const pendingAction = ref(null)
const actionDialog = ref(false)

function rowAction(row, m = 'dropship') {
  return primaryFulfillAction({ mode: m, item: row })
}

/** 主操作执行（收货登记等走 AsyncActionDialog；代登记发运同理，不盲重试）。 */
function doPrimary(row, action) {
  if (action.disabled) return
  if (action.code === 'PURCHASE_RECEIVE') {
    pendingAction.value = {
      ...action,
      key: `purchase:${row.id}:receive:${Date.now()}`,
      context: `采购单 #${row.id} · 登记收货 · 数量 ${row.qty ?? '—'} · 供货商 ${row.supplier || '未指定'}`,
      doneMessage: '收货已登记',
      row,
    }
    actionDialog.value = true
    return
  }
  if (action.code === 'DROP_SHIP_DELEGATE') {
    ElMessage.info('委托代发：请在平台侧完成代发货，完成后回到订单页登记发运（轨迹待接入）')
    return
  }
  if (action.code === 'DROP_SHIP_VIEW') {
    ElMessage.info('发运登记：物流轨迹待接入，当前仅显示登记状态')
  }
}

async function onSubmit(payload) {
  const row = payload.context?.row || pendingAction.value?.row
  if (!row) return
  try {
    const result = await receivePurchase(row.id, { qty: row.qty ?? undefined })
    ElMessage.success(`收货已登记，在手库存 +${result?.in_stock_added ?? ''}`)
    actionDialog.value = false
    pendingAction.value = null
    await load()
  } catch (e) {
    const status = e?.response?.status
    if (status === 409) {
      // 状态已变 → 刷新不丢输入（AsyncActionDialog CONFLICT 分支）
      await load()
    }
    throw e
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchPurchases({ page: 1 })
    purchases.value = data.items || []
  } catch (e) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// 切列时清空选中；从订单页深链带 mode 参数
watch(() => route.query.mode, (m) => {
  if (['stocking', 'dropship', 'purchase'].includes(m)) mode.value = m
}, { immediate: false })

onMounted(load)
</script>

<style scoped>
.queue-card__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.stocking-hint {
  margin-top: 8px;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}
</style>
