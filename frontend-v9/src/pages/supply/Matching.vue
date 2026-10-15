<template>
  <div class="page">
    <JourneyJ0Bar />
    <PageHeader
      title="货源匹配"
      subtitle="左商品要求 · 中央供应候选对比 · 右总成本/毛利假设/风险/缺项"
    >
      <template #filters>
        <el-select
          v-model="productId" filterable placeholder="选择商品（按成本试算要求）"
          style="width: 260px" @change="loadForProduct"
        >
          <el-option
            v-for="p in productOptions" :key="p.id"
            :label="`#${p.id} ${p.title}`" :value="p.id"
          />
        </el-select>
      </template>
      <template #actions>
        <el-button @click="goPricing">定价与利润试算</el-button>
      </template>
    </PageHeader>

    <!-- 左：商品要求 -->
    <el-row :gutter="16">
      <el-col :span="6">
        <el-card shadow="never" class="match-col">
          <div class="match-col__title">商品要求</div>
          <SectionState code="EMPTY_NEW" action-text="选择商品">
            <el-descriptions :column="1" border size="small" v-if="selectedProduct">
              <el-descriptions-item label="商品">{{ selectedProduct.title }}</el-descriptions-item>
              <el-descriptions-item label="目标售价">
                <MoneyValue :value="targetSellPrice" :currency="marketCurrency" />
              </el-descriptions-item>
              <el-descriptions-item label="目标市场币种">{{ marketCurrency || '—' }}</el-descriptions-item>
              <el-descriptions-item label="成本假设来源">定价域（costing 读端点）</el-descriptions-item>
            </el-descriptions>
          </SectionState>
        </el-card>
      </el-col>

      <!-- 中央：供应候选对比 -->
      <el-col :span="10">
        <el-card shadow="never" class="match-col">
          <div class="match-col__title">供应候选对比（{{ offers.length }}）</div>
          <SectionState :code="offersCode" :error="offersError" @retry="loadForProduct">
            <el-table v-if="offers.length" :data="offers" size="small" border>
              <el-table-column prop="supplier_name" label="供货商" min-width="130" />
              <el-table-column label="采购价">
                <template #default="{ row }">
                  <MoneyValue :value="row.price" :currency="row.currency" :fx-date="row.fx_date" />
                </template>
              </el-table-column>
              <el-table-column prop="moq" label="MOQ" width="70">
                <template #default="{ row }">{{ row.moq ?? '—' }}</template>
              </el-table-column>
              <el-table-column prop="ship_days" label="交期(天)" width="80">
                <template #default="{ row }">{{ row.ship_days ?? '—' }}</template>
              </el-table-column>
              <template #empty>
                <EmptyState reason="NO_DATA" hint="该商品暂无货源报价" />
              </template>
            </el-table>
            <div v-if="offers.length >= 2" class="match-col__compare">
              <div class="match-col__sub">逐字段优劣（{{ offers[0].supplier_name }} vs {{ offers[1].supplier_name }}）</div>
              <el-table :data="compareRows" size="small">
                <el-table-column prop="field" label="字段" width="110" />
                <el-table-column label="判定" width="110">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.winner === 'a' ? 'success' : row.winner === 'b' ? 'warning' : 'info'" effect="plain">
                      {{ row.winner === 'a' ? 'A 优' : row.winner === 'b' ? 'B 优' : row.winner === 'tie' ? '持平' : '未知' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="detail" label="明细" min-width="140" show-overflow-tooltip />
              </el-table>
            </div>
          </SectionState>
        </el-card>
      </el-col>

      <!-- 右：总成本 / 毛利假设 / 风险 / 缺项 -->
      <el-col :span="8">
        <el-card shadow="never" class="match-col">
          <div class="match-col__title">总成本 · 毛利假设 · 风险</div>
          <template v-if="selectedOffer">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="选中候选">{{ selectedOffer.supplier_name }}</el-descriptions-item>
              <el-descriptions-item label="总成本">
                <MoneyValue
                  :value="view.totalCost"
                  :currency="view.currency"
                  :analysis-currency="marketCurrency"
                  :fx-date="view.fxDate"
                  :estimated="true"
                />
              </el-descriptions-item>
              <el-descriptions-item label="毛利">
                <el-tooltip
                  :content="view.isAssumption ? '缺项未补齐，仅为假设，不得当真利润（§5.13）' : ''"
                  placement="top"
                >
                  <el-tag :type="view.isAssumption ? 'warning' : 'success'" size="small" effect="plain">
                    {{ profitLabel(view) }}
                  </el-tag>
                </el-tooltip>
              </el-descriptions-item>
              <el-descriptions-item label="缺项">
                <template v-if="view.gaps.length">
                  <el-tag
                    v-for="g in view.gaps" :key="g"
                    type="warning" size="small" effect="plain" class="gap-tag"
                  >{{ g }}</el-tag>
                </template>
                <span v-else>无缺项</span>
              </el-descriptions-item>
              <el-descriptions-item v-if="view.fxUnknown" label="汇率">汇率未知（不同币种缺汇率日）</el-descriptions-item>
            </el-descriptions>
            <DataQualityBanner
              v-if="view.isAssumption"
              tag="AI_ESTIMATED"
              detail="毛利为假设值：缺物流费/税费或汇率日，不能当作真利润，禁止据此自动下单"
              :links="[{ label: '到定价域补齐假设', path: '/app/pricing' }]"
            />
          </template>
          <EmptyState v-else reason="NO_DATA" hint="选择左侧商品与候选后试算总成本" />
        </el-card>
      </el-col>
    </el-row>

    <div class="match-note">
      <el-alert
        type="info" :closable="false"
        title="口径说明：成本假设来自定价域 costing 读端点；缺物流费/税费的毛利仅为假设（MoneyValue 估算标签），不同币种缺汇率日显「汇率未知」"
      />
    </div>
  </div>
</template>

<script setup>
/**
 * 货源匹配（蓝图 R1 SU-04，包 2）：/app/supply/matching。
 *
 * 数据源：pricing.js(costing 读端点 = 利润试算 calc) + suppliers.js offers（真实候选）；
 * 缺币种汇率日/物流费 → 毛利禁当真利润（MoneyValue 估算标签 + DataQualityBanner）。
 * 纯函数源：shared/matchingView.js（候选对比 + 缺项统计 + 总成本/毛利假设）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import JourneyJ0Bar from '../../components/JourneyJ0Bar.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import MoneyValue from '../../components/MoneyValue.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchProducts } from '../../api/domains/products'
import { fetchOffers } from '../../api/domains/suppliers'
import {
  compareCandidates, costAndGrossAssumption, profitLabel,
} from '../../shared/matchingView'
import { isJourneyActive, buildJourneyQuery } from '../../shared/journeyJ0View'

const route = useRoute()
const router = useRouter()

/** J0 链路内跳转：保留 journey + productId 上下文。 */
const journeyQuery = computed(() =>
  isJourneyActive(route.query) ? buildJourneyQuery({ productId: route.query.productId }) : {})
function goPricing() {
  router.push({ path: '/app/pricing', query: journeyQuery.value })
}

const productOptions = ref([])
const productId = ref(null)
const offers = ref([])
const offersLoading = ref(false)
const offersError = ref('')
const selectedOffer = ref(null)

/** 市场币种（商品目标市场；缺项显"—"）。 */
const marketCurrency = computed(() => selectedProduct.value?.market_currency || selectedProduct.value?.currency || '')

const selectedProduct = computed(() =>
  productOptions.value.find((p) => String(p.id) === String(productId.value)) || null)

/** 逐字段对比（前两个候选；≥2 条才渲染）。 */
const compareRows = computed(() =>
  offers.value.length >= 2 ? compareCandidates(offers.value[0], offers.value[1]) : [])

/** 总成本/毛利假设视图（缺物流费/税费 → isAssumption；缺汇率日 → fxUnknown）。 */
const view = computed(() => {
  const row = selectedOffer.value || {}
  const basePrice = row.price ?? null
  const logistics = row.logistics_cost ?? null
  const tax = row.tax_cost ?? null
  const currency = row.currency || ''
  return costAndGrossAssumption({
    unitPrice: basePrice,
    qty: Number(row.moq) || 1,
    logisticsCost: logistics,
    taxCost: tax,
    sellPrice: targetSellPrice.value,
    currency,
    analysisCurrency: marketCurrency.value,
    fxDate: row.fx_date || '',
  })
})

/** 目标售价（商品主档缺项 → null，不渲染 0）。 */
const targetSellPrice = computed(() => {
  const p = selectedProduct.value
  return p?.attrs?.sale_price ?? p?.sale_price ?? null
})

const offersCode = computed(() => {
  if (offersError.value) return 'ERROR'
  if (offersLoading.value) return 'LOADING'
  if (!productId.value) return 'EMPTY_NEW'
  if (!offers.value.length) return 'EMPTY_FILTER'
  return 'ready'
})

async function loadForProduct() {
  selectedOffer.value = null
  offers.value = []
  offersError.value = ''
  if (!productId.value) return
  offersLoading.value = true
  try {
    const data = await fetchOffers(productId.value)
    offers.value = data.items || []
  } catch (e) {
    offersError.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    offersLoading.value = false
  }
}

onMounted(async () => {
  try {
    const data = await fetchProducts({ page: 1 })
    productOptions.value = data.items || []
    // 深链：/app/supply/matching?productId=
    const qId = route.query.productId
    productId.value = qId ? Number(qId) : (productOptions.value[0]?.id ?? null)
    if (productId.value) await loadForProduct()
  } catch {
    productOptions.value = []
  }
})
</script>

<style scoped>
.match-col { height: 100%; }
.match-col__title {
  font-weight: 600;
  margin-bottom: 8px;
}
.match-col__sub {
  margin: 12px 0 6px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}
.gap-tag { margin-right: 4px; }
.match-note { margin-top: 16px; }
</style>
