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
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import JourneyJ0Bar from '../../components/JourneyJ0Bar.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import { can } from '../../permissions/permissions'
import { fetchPricingRecords, calcProfit, suggestPrice } from '../../api/domains/pricing'
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

onMounted(load)
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
