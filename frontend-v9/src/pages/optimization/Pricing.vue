<template>
  <div class="page">
    <JourneyJ0Bar />
    <PageHeader title="动态定价" subtitle="利润计算与 BI / 到岸成本同口径 · AI 建议价批量采纳">
      <template #actions>
        <el-button v-if="writable" :loading="sugLoading" @click="suggest">AI 动态定价（按商品）</el-button>
      </template>
      <template #filters>
        <el-input-number v-model="pid" :min="1" placeholder="商品ID" />
      </template>
    </PageHeader>

    <!-- 利润计算卡：与 BI 贡献利润 / 到岸成本同源 costing 实现（口径互链） -->
    <FormSection title="利润计算" description="与「BI 经营分析 · 贡献利润」「到岸成本配置」同一套 costing 实现（T-53 口径唯一）">
      <div class="calc-bar">
        <el-input v-model="destination" placeholder="目的国（可选，如 US）" style="width: 180px" clearable />
        <el-input-number v-model="qty" :min="1" placeholder="数量" />
        <el-button v-if="writable" type="primary" :loading="calcLoading" @click="calc">计算真实利润</el-button>
      </div>
      <el-descriptions v-if="calcResult" :column="4" border size="small" class="mt8">
        <el-descriptions-item label="采购成本¥">{{ calcResult.purchase_cost ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="物流¥">{{ calcResult.logistics_cost ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="关税¥">{{ calcResult.duty_cny ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="佣金率">{{ percent(calcResult.platform_fee_rate) }}</el-descriptions-item>
        <el-descriptions-item label="广告¥/件">{{ calcResult.ads_cost ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="售价">{{ calcResult.currency || '—' }} {{ calcResult.price ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="单件利润">
          <b :style="{ color: Number(calcResult.profit) > 0 ? 'var(--color-success)' : 'var(--color-danger)' }">
            {{ calcResult.currency || '—' }} {{ calcResult.profit ?? '—' }}
          </b>
        </el-descriptions-item>
        <el-descriptions-item label="利润率">{{ percent(calcResult.margin) }}</el-descriptions-item>
      </el-descriptions>
      <div class="links">
        <router-link to="/app/analytics/bi">查看 BI 统一口径 →</router-link>
        <router-link :to="costJourneyTo('/app/analytics/landed-cost')">维护到岸成本配置 →</router-link>
      </div>
    </FormSection>

    <!-- 核价报价轮次（M2-A）：只读历史 + 低价门禁解释；写入口在 Launch 动作 -->
    <FormSection
      title="核价报价轮次"
      description="只增不改的报价历史；申报 / 还价 / 接受在 Launch 流程内执行，本页只读，不绕过流程写轮次"
    >
      <el-alert
        v-if="gateMessage" type="error" :closable="false" show-icon class="mt8"
        :title="gateMessage"
        description="本页只能帮你测算到达标价；提交报价轮次请回到 Launch 的「平台核价」步骤——那里才有流程上下文与决策留痕。"
      />
      <el-descriptions v-if="calcResult" :column="4" border size="small" class="mt8">
        <el-descriptions-item label="最低毛利要求">{{ percent(calcResult.min_margin) }}</el-descriptions-item>
        <el-descriptions-item label="目标毛利">{{ percent(calcResult.target_margin) }}</el-descriptions-item>
        <el-descriptions-item label="当前售价毛利">{{ percent(calcResult.margin) }}</el-descriptions-item>
        <el-descriptions-item label="门槛判定">
          <el-tag :type="gateMessage ? 'danger' : 'success'" size="small">
            {{ gateMessage ? '低于门槛' : '达标' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
      <el-table v-loading="roundsLoading" :data="roundRowsData" size="small" class="mt8">
        <el-table-column prop="roundNo" label="轮次" width="70" />
        <el-table-column prop="actionLabel" label="动作" width="100" />
        <el-table-column prop="priceText" label="申报价" width="140" />
        <el-table-column prop="marginText" label="毛利率" width="90" />
        <el-table-column prop="floorText" label="门槛" width="90" />
        <el-table-column label="门禁" width="100">
          <template #default="{ row }">
            <el-tag :type="row.gateOk ? 'success' : 'danger'" size="small">{{ row.gateLabel }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="decisionLabel" label="决策" width="90" />
        <el-table-column prop="at" label="时间" width="170" />
        <el-table-column prop="source" label="来源" width="90" />
        <template #empty>
          <EmptyState reason="NO_DATA" hint="还没有报价轮次：在 Launch 的「平台核价」步骤申报第一轮" />
        </template>
      </el-table>
    </FormSection>

    <FormSection title="定价记录（最新在前）" description="勾选后批量采纳建议价（写入商品取价口径 attrs.sale_price）；忽略为本地标记（后端暂无忽略端点）">
      <div class="batch-bar" v-if="writable">
        <el-button
          type="success" :disabled="!selected.length" :loading="adopting"
          @click="adoptSelected"
        >
          批量采纳（{{ selected.length }}）
        </el-button>
        <el-button :disabled="!selected.length" @click="ignoreSelected">
          批量忽略（{{ selected.length }}）
        </el-button>
        <span class="batch-bar__tip">采纳 = 更新商品售价取价口径，立即影响利润计算</span>
      </div>
      <el-table v-loading="loading" :data="visibleItems" size="small" @selection-change="onSelect">
        <el-table-column v-if="writable" type="selection" width="40" />
        <el-table-column prop="product_id" label="商品ID" width="80" />
        <el-table-column prop="product_title" label="商品" min-width="180" show-overflow-tooltip />
        <el-table-column prop="price" :label="`当前价${priceUnit}`" width="100" />
        <el-table-column :label="`建议价${priceUnit}`" width="110">
          <template #default="{ row }">
            <b style="color: var(--color-primary)">{{ row.suggested_price }}</b>
          </template>
        </el-table-column>
        <el-table-column :label="`单件利润${priceUnit}`" width="110">
          <template #default="{ row }">
            <span :style="{ color: Number(row.profit) > 0 ? 'var(--color-success)' : 'var(--color-danger)' }">
              {{ row.profit }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="利润率" width="150">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.max(0, Math.round(Number(row.margin || 0) * 100))"
              :color="row.margin > 0.3 ? 'var(--color-success)' : row.margin > 0.15 ? 'var(--color-warning)' : 'var(--color-danger)'"
            />
          </template>
        </el-table-column>
        <el-table-column prop="model" label="模型" width="90" />
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column label="调价依据" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.reason?.strategy }}{{ row.reason?.adjustments?.length ? '；' + row.reason.adjustments.join('；') : '' }}
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="暂无定价记录" /></template>
      </el-table>
      <el-pagination
        class="pager" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" :current-page="page" @current-change="onPageChange"
      />
    </FormSection>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import JourneyJ0Bar from '../../components/JourneyJ0Bar.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import { can } from '../../permissions/permissions'
import { fetchPricingRecords, calcProfit, suggestPrice, fetchPriceRounds } from '../../api/domains/pricing'
import { roundRows, priceGateMessage } from '../../shared/pricingRounds'
import { fetchProduct, updateProduct } from '../../api/domains/products'
import { isJourneyActive, buildJourneyQuery } from '../../shared/journeyJ0View'

const route = useRoute()
/** J0 链路内跳到同属「成本/风险」步的到岸成本页，保留 journey + productId。 */
function costJourneyTo(path) {
  return isJourneyActive(route.query)
    ? { path, query: buildJourneyQuery({ productId: route.query.productId }) }
    : { path }
}

const writable = can('finance:write')

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const pid = ref(1)
const destination = ref('')
const qty = ref(1)
const calcLoading = ref(false)
const sugLoading = ref(false)
const calcResult = ref(null)
/** 定价口径币种：取 calc 响应返回的 currency；未跑过试算时为未知（不臆测 USD）。 */
const calcCurrency = ref('')
/**
 * 表头/卡片的金额单位后缀：已知币种包成「（USD）」，未知时显式标「—（口径未知）」
 * 而非默认 $. 仅做展示绑定，不做前端换汇、不在浏览器算利润（costing.calc_profit 权威）。
 */
const priceUnit = computed(() => (calcCurrency.value ? `（${calcCurrency.value}）` : '—（口径未知）'))
const rounds = ref([])
const roundsLoading = ref(false)
/** 低价门禁文案：门槛取自后端 calc 响应的 min_margin，前端不写死 15%。 */
const gateMessage = computed(() => priceGateMessage(
  calcResult.value?.margin, calcResult.value?.min_margin))
const roundRowsData = computed(() => roundRows(rounds.value))
const selected = ref([])
const adopting = ref(false)
/** 本地忽略集（后端无忽略端点，仅本次会话生效，不做假持久化）。 */
const dismissed = ref(new Set())

const visibleItems = computed(() => items.value.filter((r) => !dismissed.value.has(r.id)))

function percent(value) {
  return value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`
}

async function load() {
  loading.value = true
  try {
    const data = await fetchPricingRecords({ page: page.value })
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

function onSelect(rows) {
  selected.value = rows
}

async function calc() {
  calcLoading.value = true
  try {
    const res = await calcProfit({
      product_id: pid.value,
      destination_country: destination.value || '',
      qty: qty.value || 1,
    })
    calcResult.value = res
    // 币种随 calc 响应绑定；响应缺 currency 时回落未知态（不臆测 USD）。
    calcCurrency.value = res?.currency || ''
  } finally {
    calcLoading.value = false
  }
}

async function suggest() {
  sugLoading.value = true
  try {
    const data = await suggestPrice(pid.value)
    // 建议响应自带 currency（与 calc 同源 USD），同步到页面币种上下文以复用 priceUnit；
    // 缺 currency 时回落上一轮 calc 的币种，再回落「—（口径未知）」（不臆测 USD）。
    calcCurrency.value = data?.currency || calcCurrency.value || ''
    ElMessage.success(`建议价${priceUnit.value} ${data.suggested_price}（利润率 ${percent(data.margin)}）`)
    load()
  } finally {
    sugLoading.value = false
  }
}

/** 采纳单条建议价：PUT /products/{id} 全量回写商品字段 + attrs.sale_price（真实取价口径）。 */
async function adoptOne(record) {
  const product = await fetchProduct(record.product_id)
  const attrs = { ...(product.attrs || {}), sale_price: record.suggested_price }
  await updateProduct(product.id, {
    title: product.title,
    sku: product.sku || '',
    category: product.category || '',
    brand: product.brand || '',
    hs_code: product.hs_code ?? null,
    attrs,
    images: product.images || [],
    source_platform: product.source_platform || '1688',
    source_url: product.source_url || '',
  })
}

async function adoptSelected() {
  const targets = selected.value.filter((r) => r.suggested_price != null)
  if (!targets.length) return ElMessage.warning('所选记录没有建议价')
  adopting.value = true
  try {
    let ok = 0
    const failed = []
    for (const record of targets) {
      try {
        await adoptOne(record)
        ok += 1
      } catch { failed.push(record.product_id) }
    }
    ElMessage({
      type: failed.length ? 'warning' : 'success',
      message: `已采纳 ${ok} 条${failed.length ? `，失败 ${failed.length} 条（商品 ${failed.join(',')}）` : ''}`,
    })
    load()
  } finally {
    adopting.value = false
  }
}

function ignoreSelected() {
  const next = new Set(dismissed.value)
  selected.value.forEach((r) => next.add(r.id))
  dismissed.value = next
  ElMessage.info('已本地忽略所选记录（后端暂无忽略端点，刷新后恢复）')
}

async function loadRounds() {
  roundsLoading.value = true
  try {
    const data = await fetchPriceRounds({ productId: pid.value, limit: 50 })
    rounds.value = data?.items || []
  } catch {
    // 轮次读失败不能挡住整页：清空列表并保持空态，不伪造历史。
    rounds.value = []
  } finally {
    roundsLoading.value = false
  }
}

watch(pid, loadRounds)

onMounted(() => {
  load()
  loadRounds()
})
</script>

<style scoped>
.calc-bar {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}
.links {
  margin-top: var(--space-3);
  display: flex;
  gap: var(--space-4);
  font-size: var(--font-size-sm);
}
.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.batch-bar__tip {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}
.pager {
  margin-top: var(--space-3);
  justify-content: flex-end;
}
.mt8 {
  margin-top: var(--space-2);
}
</style>
