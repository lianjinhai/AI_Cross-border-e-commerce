<template>
  <div class="page">
    <JourneyJ0Bar />
    <PageHeader
      title="货源匹配"
      subtitle="比选即决策：每行报价的来源/有效期/核验可溯，选定后成本试算将采用此报价"
    >
      <template #filters>
        <el-select
          v-model="productId" filterable placeholder="选择商品（按成本试算要求）"
          style="width: 260px" @change="onProductChange"
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

    <!-- 上下文条：选定商品 + 会话内经营条件（仅参考）+ 复制询价内容 -->
    <el-card shadow="never" class="ctx-strip">
      <div class="ctx-strip__row">
        <div class="ctx-item">
          <span class="ctx-label">选定商品</span>
          <span class="ctx-value">{{ selectedProduct?.title || '—' }}</span>
        </div>
        <div class="ctx-item">
          <span class="ctx-label">目标市场</span>
          <span v-if="profile?.targetMarket" class="ctx-value">{{ profile.targetMarket }}</span>
          <el-link v-else type="primary" :underline="false" @click="goOnboarding">待补</el-link>
        </div>
        <div class="ctx-item">
          <span class="ctx-label">预算</span>
          <span v-if="profile?.budget" class="ctx-value">{{ profile.budget }}</span>
          <el-link v-else type="primary" :underline="false" @click="goOnboarding">待补</el-link>
        </div>
        <div class="ctx-item">
          <span class="ctx-label">风险偏好</span>
          <span v-if="profile?.risk" class="ctx-value">{{ profile.risk }}</span>
          <el-link v-else type="primary" :underline="false" @click="goOnboarding">待补</el-link>
        </div>

        <div class="ctx-spacer" />

        <div v-if="selectedOfferId != null" class="ctx-selected">
          <el-tag type="primary" size="small" effect="plain">已选定 #{{ selectedOfferId }}</el-tag>
          <el-button size="small" link type="primary" :loading="selecting" :disabled="selecting || readOnly"
            :title="readOnly ? '只读账号无写权限（fail-closed）' : undefined" @click="clearOffer">
            清除选定
          </el-button>
        </div>
        <el-button size="small" :disabled="!selectedProduct" @click="copyInquiry">复制询价内容</el-button>
      </div>
      <div class="ctx-caption">会话内选择，仅作本页参考</div>
    </el-card>

    <!-- 全宽比选表（原型 05：比选即决策） -->
    <el-card shadow="never" class="match-table-card">
      <div class="match-col__title">
        供应候选对比（{{ offers.length }}）
        <span class="match-col__hint">选定报价后，成本试算将优先采用该报价</span>
      </div>
      <SectionState :code="offersCode" :error="offersError" @retry="onProductChange">
        <el-table
          v-if="offers.length"
          :data="offers"
          size="small" border
          :row-class-name="offerRowClass"
          :empty-text="'该商品暂无货源报价'"
        >
          <el-table-column label="供应商" min-width="190">
            <template #default="{ row }">
              <div class="supplier-cell">
                <div class="supplier-name">{{ row.supplier.name || '未具名供应商' }}</div>
                <div class="supplier-meta">
                  {{ row.supplier.supplier_type || '—' }} · {{ row.supplier.region || '—' }} ·
                  评分 {{ row.supplier.rating != null ? row.supplier.rating : '—' }}
                </div>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="报价" min-width="150">
            <template #default="{ row }">
              <div>
                <MoneyValue :value="row.price" :currency="row.currency" />
                <div
                  v-if="row.currency && marketCurrency && row.currency !== marketCurrency"
                  class="cell-note"
                >非{{ marketCurrency }}结算 · 汇率未知</div>
              </div>
            </template>
          </el-table-column>

          <el-table-column prop="moq" label="MOQ" width="80">
            <template #default="{ row }">{{ row.moq ?? '—' }}</template>
          </el-table-column>

          <el-table-column label="交期" width="90">
            <template #default="{ row }">{{ row.ship_days != null ? `${row.ship_days} 天` : '—' }}</template>
          </el-table-column>

          <el-table-column label="有效期" width="120">
            <template #default="{ row }">
              <span v-if="row.valid_until">{{ row.valid_until }}</span>
              <span v-else class="amber-chip">未填写</span>
            </template>
          </el-table-column>

          <el-table-column label="来源/核验" min-width="150">
            <template #default="{ row }">
              <div class="verify-tags">
                <el-tag size="small" :type="srcTags(row).source.tone" effect="plain">{{ srcTags(row).source.label }}</el-tag>
                <el-tag size="small" :type="srcTags(row).verification.tone" effect="plain">{{ srcTags(row).verification.label }}</el-tag>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="库存" width="90">
            <template #default="{ row }">
              <span :class="row.in_stock === false ? 'muted-text' : ''">{{ stockLabel(row.in_stock) }}</span>
            </template>
          </el-table-column>

          <!-- 窄屏不固定：固定列会盖住整张表，只剩按钮看不清是哪一行（390px 实测）。 -->
          <el-table-column label="下一步" width="180" :fixed="isNarrow ? false : 'right'">
            <template #default="{ row }">
              <el-tag
                v-if="row.is_selected || row.id === selectedOfferId"
                type="primary" effect="plain" size="small"
              >已选定 · 成本试算将使用此报价</el-tag>
              <el-button
                v-else size="small" type="primary"
                :loading="selecting && selectingId === row.id"
                :disabled="selecting || readOnly"
                :title="readOnly ? '只读账号无写权限（fail-closed）' : undefined"
                @click="selectOffer(row)"
              >选定此报价</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="offers.length >= 2" class="match-col__compare">
          <div class="match-col__sub">逐字段优劣（{{ offers[0].supplier.name || '候选A' }} vs {{ offers[1].supplier.name || '候选B' }}）</div>
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

    <!-- 左：商品要求 / 右：成本·毛利假设·风险·缺项 -->
    <el-row :gutter="16" class="match-below">
      <el-col :span="12">
        <el-card shadow="never" class="match-col">
          <div class="match-col__title">商品要求</div>
          <SectionState code="EMPTY_NEW" action-text="选择商品">
            <el-descriptions :column="1" border size="small" v-if="selectedProduct">
              <el-descriptions-item label="商品">{{ selectedProduct.title }}</el-descriptions-item>
              <el-descriptions-item label="目标售价">
                <MoneyValue :value="targetSellPrice" :currency="marketCurrency" />
              </el-descriptions-item>
              <el-descriptions-item label="目标市场币种">{{ marketCurrency || '—' }}</el-descriptions-item>
              <el-descriptions-item label="成本假设来源">后端 costing（POST /pricing/calc）</el-descriptions-item>
            </el-descriptions>
          </SectionState>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never" class="match-col">
          <div class="match-col__title">总成本 · 毛利（后端 costing 试算）</div>
          <template v-if="costingView">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="成本依据报价">
                <span>offer_id={{ costingView.offerId }}</span>
                <el-tag :type="costingView.isUserSelected ? 'success' : 'info'" size="small" effect="plain" class="gap-tag">
                  {{ costingView.basisNote }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="成本口径">
                <el-tag v-if="costingView.shopId != null" type="success" size="small" effect="plain">
                  店铺{{ costingShopName }} · 市场 {{ costingView.market || '待补' }}（销售店铺口径）
                </el-tag>
                <el-tag v-else type="warning" size="small" effect="plain">
                  通用试算：未绑定店铺，不含店铺专属费用
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="采购成本（CNY）">
                <MoneyValue :value="costingView.purchaseCny" currency="CNY" :estimated="costingView.isAssumption" />
              </el-descriptions-item>
              <el-descriptions-item label="总成本（CNY）">
                <MoneyValue :value="costingView.totalCostCny" currency="CNY" :estimated="costingView.isAssumption" />
              </el-descriptions-item>
              <el-descriptions-item :label="`毛利（${costingView.currency}，后端试算）`">
                <el-tooltip
                  :content="costingView.isAssumption ? '存在未计入成本项（见缺项），试算值偏高，不得当真利润' : ''"
                  placement="top"
                >
                  <span v-if="costingView.profit != null">
                    <MoneyValue :value="costingView.profit" :currency="costingView.currency" :estimated="costingView.isAssumption" />
                    <span class="muted-text">（毛利率 {{ (Number(costingView.margin) * 100).toFixed(1) }}% · 汇率 {{ costingView.fx }}）</span>
                  </span>
                  <el-tag v-else type="info" size="small" effect="plain">待核算</el-tag>
                </el-tooltip>
              </el-descriptions-item>
              <el-descriptions-item label="缺项">
                <template v-if="costingView.gaps.length">
                  <el-tag
                    v-for="g in costingView.gaps" :key="g"
                    type="warning" size="small" effect="plain" class="gap-tag"
                  >{{ g }}</el-tag>
                </template>
                <span v-else>无缺项</span>
              </el-descriptions-item>
            </el-descriptions>
            <el-alert v-if="costingView.offerLimits.length" type="warning" :closable="false" show-icon class="gap-alert"
              :title="`选定报价限制（${costingView.offerState}）`"
              :description="costingView.offerLimits.join('；')" />
            <el-alert v-if="costingView.selectedIgnored" type="warning" :closable="false" show-icon class="gap-alert"
              title="已选定报价未被成本引擎采用"
              description=" costing 依据其实际采用的报价（上方 offer_id）计算；请检查选定报价是否仍有效，或重新选定。" />
            <DataQualityBanner
              v-if="costingView.isAssumption"
              tag="AI_ESTIMATED"
              detail="试算含未计入成本项（见缺项），结果偏高；补齐目的国/HS 编码/海外仓后再作为定价依据"
              :links="[{ label: '到定价域补齐假设', path: '/app/pricing' }]"
            />
          </template>
          <EmptyState v-else-if="costingError"
            :reason="costingError.includes('权限') ? 'NO_PERMISSION' : 'REQUEST_FAILED'" :hint="`待核算：${costingError}`" />
          <div v-else-if="costingLoading" class="costing-loading">正在调用后端成本试算…</div>
          <EmptyState v-else reason="NO_DATA" hint="选择左侧商品后由后端 costing 试算总成本" />
        </el-card>
      </el-col>
    </el-row>

    <div class="match-note">
      <el-alert
        type="info" :closable="false"
        title="口径说明：成本与毛利由后端 costing（POST /pricing/calc）按当前配置试算，前端不做本地财务公式；毛利为试算值——存在缺项时偏高，不是承诺利润；选定报价后成本试算优先采用该报价（选定失效时显式标注回退）"
      />
    </div>
  </div>
</template>

<script setup>
/**
 * 货源匹配（蓝图 R1 SU-04，包 2 → B3 原型 05 重建）：/app/supply/matching。
 *
 * 比选即决策：每行报价带 来源/核验/有效期/库存 可溯证据；用户「选定此报价」
 * 经 PUT /products/{id}/selected-offer 写入，成本试算（costing）将优先使用该报价。
 * 诚实边界（§5.13 / §B.2）：
 *  - 无发送 API → 询价动作仅「复制询价内容」（toast「已复制」），绝无「已发送」。
 *  - 货币：真实币种渲染；不同币种标「汇率未知」，不默认 $。
 *  - 缺物流费/税费 → 毛利仅假设，禁当真利润。
 * 纯函数源：shared/matchingView.js（归一化/对比/成本假设/询价文案/最低在库）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import JourneyJ0Bar from '../../components/JourneyJ0Bar.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import MoneyValue from '../../components/MoneyValue.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchProducts, saveSelectedOffer } from '../../api/domains/products'
import { fetchOffers } from '../../api/domains/suppliers'
import { calcProfit } from '../../api/domains/pricing'
import { useWorkspaceShell } from '../../composables/workspaceShell'
import { canWrite } from '../../permissions/permissions'
import {
  compareCandidates, costingResultView,
  normalizeOffer, offerId, sourceVerificationTags, stockLabel,
  buildInquiryCopy,
} from '../../shared/matchingView'
import { loadSessionProfile } from '../../shared/onboardingProfile'
import { isJourneyActive, buildJourneyQuery } from '../../shared/journeyJ0View'

const route = useRoute()
const router = useRouter()

/** J0 链路内跳转：保留 journey + productId 上下文。 */
const journeyQuery = computed(() =>
  isJourneyActive(route.query) ? buildJourneyQuery({ productId: route.query.productId }) : {})
function goPricing() {
  router.push({ path: '/app/pricing', query: journeyQuery.value })
}
function goOnboarding() {
  router.push('/onboarding?step=1')
}

const productOptions = ref([])
const productId = ref(null)
const offers = ref([])
const offersLoading = ref(false)
const offersError = ref('')
const selectedOfferId = ref(null)
const selecting = ref(false)
const selectingId = ref(null)
/** 只读 fail-closed：与 ShellBanner 同源判断，写按钮禁用（D24）。 */
const { readOnly, selectedShopId, shops } = useWorkspaceShell()

/** 成本上下文店铺：仅具体店铺（非「全部店铺」）时传给后端，服务端会校验归属。 */
const costingShopId = computed(() => {
  const raw = selectedShopId.value
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : null
})

/** 成本口径展示用店名：取不到店名时退回 #id（不臆造名称）。 */
const costingShopName = computed(() => {
  const hit = (shops.value || []).find((s) => String(s?.id) === String(costingView.value?.shopId))
  return hit?.name ? `「${hit.name}」` : ` #${costingView.value?.shopId}`
})

/** 窄屏（≤560）：比选表不启用固定操作列，避免固定列盖住整行证据。 */
const isNarrow = ref(false)
let narrowMq = null
function onNarrowChange(e) { isNarrow.value = e.matches }
onMounted(() => {
  if (typeof window === 'undefined' || !window.matchMedia) return
  narrowMq = window.matchMedia('(max-width: 560px)')
  isNarrow.value = narrowMq.matches
  narrowMq.addEventListener('change', onNarrowChange)
})
onUnmounted(() => {
  if (narrowMq) narrowMq.removeEventListener('change', onNarrowChange)
})

/** 会话内经营条件（仅本页参考；缺项「待补」）。 */
const profile = computed(() => loadSessionProfile())

const selectedProduct = computed(() =>
  productOptions.value.find((p) => String(p.id) === String(productId.value)) || null)

/** 市场币种（商品目标市场；缺项显"—"）。 */
const marketCurrency = computed(() => selectedProduct.value?.market_currency || selectedProduct.value?.currency || '')

/** 目标售价（商品主档缺项 → null，不渲染 0）。 */
const targetSellPrice = computed(() => {
  const p = selectedProduct.value
  return p?.attrs?.sale_price ?? p?.sale_price ?? null
})

/**
 * 后端 costing 试算（任务三口径修复）：
 * 成本/毛利只消费 POST /pricing/calc 返回值——前端绝不用本地公式替代财务核算。
 * require_write：只读账号不发起请求，显式「待核算（需要定价写权限）」。
 */
const costing = ref(null)
const costingLoading = ref(false)
const costingError = ref('')

const costingView = computed(() => costingResultView(costing.value, selectedOfferId.value))

async function loadCosting() {
  costing.value = null
  costingError.value = ''
  if (!productId.value) return
  if (!canWrite()) {
    costingError.value = '成本试算需要定价写权限（require_write），当前账号只读——请向管理员申请或查看定价域只读记录'
    return
  }
  costingLoading.value = true
  try {
    const payload = { product_id: productId.value }
    if (costingShopId.value != null) payload.shop_id = costingShopId.value
    costing.value = await calcProfit(payload)
  } catch (e) {
    costingError.value = e?.response?.data?.detail?.message || e?.response?.data?.detail || e?.message || '成本试算失败'
  } finally {
    costingLoading.value = false
  }
}

/** 逐字段对比（前两个候选；≥2 条才渲染）。 */
const compareRows = computed(() =>
  offers.value.length >= 2 ? compareCandidates(offers.value[0], offers.value[1]) : [])

const offersCode = computed(() => {
  if (offersError.value) return 'ERROR'
  if (offersLoading.value) return 'LOADING'
  if (!productId.value) return 'EMPTY_NEW'
  if (!offers.value.length) return 'EMPTY_FILTER'
  return 'ready'
})

/** 来源/核验标签（行内调用）。 */
function srcTags(row) {
  return sourceVerificationTags(row.source_kind, row.verification_status)
}

/** 选中行高亮（tint-blue 强调）。 */
function offerRowClass({ row }) {
  return (row.is_selected || row.id === selectedOfferId.value) ? 'offer-row--selected' : ''
}

/** 加载报价（防御式：兼容 {items, selected_offer_id} 与裸数组）。 */
async function loadForProduct() {
  offers.value = []
  offersError.value = ''
  selectedOfferId.value = null
  if (!productId.value) return
  offersLoading.value = true
  try {
    const data = await fetchOffers(productId.value)
    const rawItems = Array.isArray(data) ? data : (data?.items ?? [])
    offers.value = rawItems.map(normalizeOffer)
    const selId = Array.isArray(data) ? null : (data?.selected_offer_id ?? null)
    selectedOfferId.value = selId ?? (offers.value.find((o) => o.is_selected)?.id ?? null)
    // 选定状态影响 costing 采用哪条报价：报价加载完即刷新后端试算
    loadCosting()
  } catch (e) {
    offersError.value = e?.response?.data?.detail || e?.message || '加载失败'
    // 向上抛：写操作后的回读失败必须能被调用方识别为「已提交但确认失败」，
    // 不能被静默吞掉后仍显示成功态。
    throw e
  } finally {
    offersLoading.value = false
  }
}

async function onProductChange() {
  try {
    await loadForProduct()
  } catch {
    // offersError 已呈现；切换商品失败不阻塞页面其余部分
  }
}

/** 选定报价（PUT；成功回填，失败保留旧状态 + 后端 detail）。 */
async function selectOffer(row) {
  if (selecting.value) return // 双击保护
  const pid = productId.value
  const oid = offerId(row)
  if (oid == null) {
    ElMessage.warning('该报价缺少 offer_id，无法选定')
    return
  }
  selecting.value = true
  selectingId.value = oid
  // 两段式（B3 契约）：写入失败 ≠ 读回失败。写成功但读回失败时**绝不重发写请求**，
  // 必须提示「已提交，确认结果失败」并让用户手动重试读取（PUT 是幂等的，
  // 但重发仍可能覆盖他人并发的改选，所以只在用户明确重试时才再写）。
  try {
    await saveSelectedOffer(pid, oid)
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '选定失败'
    ElMessage.error(`选定失败：${detail}`)
    selecting.value = false
    selectingId.value = null
    return // 保留先前状态：不修改 offers / selectedOfferId
  }
  try {
    await loadForProduct() // 回读 is_selected / selected_offer_id
    selectedOfferId.value = oid
    ElMessage.success('已选定此报价，成本试算将优先使用')
  } catch (e) {
    // 服务端已接受写入，但本地未能确认：不允许显示成功态。
    selectedOfferId.value = oid
    ElMessage.warning('已提交选定，但确认结果失败：请刷新或重新查询后再确认状态')
    if (!offersError.value) offersError.value = '选定已提交，读回失败（状态待确认）'
  } finally {
    selecting.value = false
    selectingId.value = null
  }
}

/** 清除选定（PUT offer_id=null；失败保留旧状态）。 */
async function clearOffer() {
  if (selecting.value) return
  const pid = productId.value
  selecting.value = true
  try {
    await saveSelectedOffer(pid, null)
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '清除失败'
    ElMessage.error(`清除失败：${detail}`)
    selecting.value = false
    return
  }
  try {
    await loadForProduct()
    selectedOfferId.value = null
    ElMessage.success('已清除选定')
  } catch {
    selectedOfferId.value = null
    ElMessage.warning('已提交清除，但确认结果失败：请刷新后确认状态')
    if (!offersError.value) offersError.value = '清除已提交，读回失败（状态待确认）'
  } finally {
    selecting.value = false
  }
}

/** 复制询价内容（复制，非发送）。 */
async function copyInquiry() {
  const text = buildInquiryCopy({
    product: selectedProduct.value || {},
    profile: profile.value || {},
    requirements: { targetSellPrice: targetSellPrice.value, marketCurrency: marketCurrency.value },
    offer: costBasisOffer.value,
  })
  const ok = await copyText(text)
  if (ok) ElMessage.success('已复制')
  else ElMessage.warning('复制失败，请手动选择文本')
}

/** 剪贴板写入（含降级，非安全上下文不抛）。 */
async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* 降级 */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

onMounted(async () => {
  try {
    const data = await fetchProducts({ page: 1 })
    productOptions.value = data.items || []
    // 深链：?product_id=N（ProductDetail 跳转携带；兼容旧 productId 写法）
    const qId = route.query.product_id ?? route.query.productId
    productId.value = qId ? Number(qId) : (productOptions.value[0]?.id ?? null)
    if (productId.value) {
      try {
        await loadForProduct()
      } catch {
        // 报价加载失败已由 offersError 呈现（页面保留商品选择，不整页空白）
      }
    }
  } catch {
    productOptions.value = []
  }
})

/** 切换店铺即换成本口径（服务端会重新校验归属），必须重算而不是复用上一店结果。 */
watch(costingShopId, () => {
  if (productId.value) loadCosting()
})
</script>

<style scoped>
.costing-loading { font-size: 13px; color: var(--v91-text-muted, #909399); padding: 8px 0; }
.gap-alert { margin-top: 10px; }
.ctx-strip { margin-bottom: 16px; }
.ctx-strip__row {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}
.ctx-item { display: flex; flex-direction: column; gap: 2px; }
.ctx-label { font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.ctx-value { font-weight: 600; color: var(--v91-text-strong); }
.ctx-spacer { flex: 1 1 auto; }
.ctx-selected { display: flex; align-items: center; gap: 4px; }
.ctx-caption {
  margin-top: 8px;
  font-size: var(--font-size-xs);
  color: var(--color-text-disabled);
}
.match-table-card { margin-bottom: 16px; }
.match-col { height: 100%; }
.match-col__title {
  font-weight: 600;
  margin-bottom: 8px;
}
.match-col__hint {
  margin-left: 8px;
  font-size: var(--font-size-xs);
  font-weight: 400;
  color: var(--color-text-secondary);
}
.match-col__sub {
  margin: 12px 0 6px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}
.match-col__compare { margin-top: 12px; }
.gap-tag { margin-right: 4px; }
.match-below { margin-bottom: 16px; }
.match-note { margin-top: 4px; }

.supplier-cell { line-height: 1.4; }
.supplier-name { font-weight: 600; }
.supplier-meta { font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.verify-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.cell-note {
  font-size: var(--font-size-xs);
  color: var(--color-warning);
  margin-top: 2px;
}
.amber-chip {
  display: inline-block;
  background: var(--v91-amber-surface);
  color: var(--color-warning);
  border-radius: var(--radius-sm);
  padding: 1px 6px;
  font-size: var(--font-size-xs);
}
.muted-text { color: var(--color-text-disabled); }
</style>

<style>
/* 选中行强调（tint-blue），穿透 el-table 行作用域 */
.offer-row--selected > td {
  background: var(--v91-tint-blue) !important;
}
</style>
