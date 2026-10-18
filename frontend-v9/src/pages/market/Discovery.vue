<template>
  <div class="page">
    <JourneyJ0Bar />
    <PageHeader title="商品发现" subtitle="商品方向研究 · 市场趋势 · 机会评分">
      <template #actions>
        <el-button v-if="canWrite" size="small" @click="trendImportDialog = true">导入真实趋势</el-button>
        <el-button v-if="canWrite" type="primary" size="small" :loading="scanning" @click="scan">AI 扫描趋势</el-button>
      </template>
    </PageHeader>

    <!-- 候选方向卡片：从评分行（按机会分 Top N）派生，带证据状态与依据 -->
    <el-card class="section mb16">
      <template #header>
        <div class="section-head">
          <span class="card-title">候选方向（按机会分 Top {{ topN }}）</span>
          <span class="freshness">{{ freshnessLabel }}</span>
        </div>
      </template>

      <!-- 筛选行：关键词 / 类目 为真实本地语义；市场·预算无后端数据，仅作画像参考 -->
      <div class="filter-row">
        <el-input v-model="filterKeyword" placeholder="关键词（筛选趋势与候选方向）" clearable
          size="small" style="width:240px" />
        <el-select v-model="filterCategory" placeholder="类目" clearable size="small" style="width:160px">
          <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
        </el-select>
        <div class="profile-chips">
          <template v-for="chip in contextChips" :key="chip.key">
            <router-link v-if="!chip.present" :to="{ path: '/onboarding', query: { step: '1' } }"
              class="chip chip--gap">{{ chip.label }}：待补</router-link>
            <span v-else class="chip chip--ok">{{ chip.label }}：{{ chip.value }}（本页范围参考）</span>
          </template>
        </div>
      </div>

      <div v-if="visibleCandidates.length" class="card-grid">
        <el-card v-for="c in visibleCandidates" :key="c.productId" class="dir-card"
          :class="(c.evidenceKind === 'api' || c.evidenceKind === 'csv') ? 'dir-card--ok' : 'dir-card--pending'">
          <div class="dir-card__head">
            <span class="dir-card__title" :title="c.title">{{ c.title }}</span>
            <el-tag :type="(c.evidenceKind === 'api' || c.evidenceKind === 'csv') ? 'success' : 'warning'"
              size="small">{{ c.evidenceLabel }}</el-tag>
          </div>
          <div v-if="c.evidenceKind !== 'api' && c.evidenceKind !== 'csv'" class="dir-card__flag">待验证</div>

          <div class="score-grid">
            <div v-for="f in scoreFields" :key="f.key" class="score-cell">
              <div class="score-cell__k">{{ f.label }}</div>
              <el-progress :percentage="c[f.key]" :stroke-width="6" :show-text="false"
                :color="c[f.key] > 75 ? 'var(--color-danger)' : (c[f.key] > 50 ? 'var(--color-warning)' : 'var(--color-primary)')" />
              <div class="score-cell__v">{{ c[f.key] }}</div>
            </div>
          </div>

          <div class="dir-card__foot">
            <el-button text size="small" @click="toggleReason(c.productId)">
              {{ expandedReasons[c.productId] ? '收起依据' : '查看依据' }}
            </el-button>
            <span class="dir-card__total">机会分 {{ c.total }}</span>
          </div>

          <div v-if="expandedReasons[c.productId]" class="reasons">
            <div class="reasons__row"><b>评分模型：</b>{{ c.model }}</div>
            <ul class="reasons__list">
              <li v-for="(r, i) in c.reasons" :key="i">{{ r }}</li>
            </ul>
            <div class="reasons__basis"><b>证据说明：</b>{{ c.evidenceBasis }}</div>
          </div>
        </el-card>
      </div>
      <el-empty v-else description="暂无评分数据，先对商品评分或 AI 选品" :image-size="60" />

      <el-alert v-if="hasDemoEvidence" type="warning" :closable="false" class="verify-alert"
        title="标注「待验证」的卡片，其需求来自内置演示趋势或默认估算，不等同于真实海外市场数据；导入官方API / CSV 趋势后可转为「有依据」。" />
    </el-card>

    <!-- 高级视图：专业表格折叠收纳，全部既有能力保留 -->
    <el-collapse v-model="advancedOpen" class="mb16">
      <el-collapse-item title="高级视图：市场趋势 · 关键词扩展 · 机会评分" name="advanced">
        <!-- 市场趋势 -->
        <el-card class="mb16">
          <template #header><span class="card-title">市场趋势（关键词 × 平台 × 30天增长）</span></template>
          <el-alert v-if="trendSource.hint" :title="trendSource.hint" :closable="false"
            :type="trendSource.has_real_data ? 'success' : 'warning'" style="margin-bottom:10px" />
          <el-table :data="filteredTrends" size="small" max-height="260">
            <el-table-column prop="keyword" label="关键词" min-width="180" />
            <el-table-column prop="platform" label="平台" width="100" />
            <el-table-column label="来源" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.source === 'api'" size="small" type="success">官方API</el-tag>
                <el-tag v-else-if="row.source === 'csv'" size="small" type="primary">CSV导入</el-tag>
                <el-tag v-else size="small" type="info">内置演示</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="search_volume" label="月搜索量" width="110" sortable />
            <el-table-column label="30天增长" width="140" sortable prop="growth_30d">
              <template #default="{ row }">
                <el-tag :type="row.growth_30d > 60 ? 'danger' : 'info'" size="small">
                  {{ row.growth_30d > 0 ? '+' : '' }}{{ row.growth_30d }}%
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="竞争度" width="200">
              <template #default="{ row }">
                <el-progress :percentage="row.competition" :stroke-width="10"
                  :color="row.competition > 75 ? 'var(--color-danger)' : 'var(--color-warning)'" />
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 关键词扩展 + 一键选品 -->
        <el-row :gutter="16" class="mb16">
          <el-col :span="16">
            <el-card>
              <template #header>
                <div style="display:flex;gap:12px;align-items:center">
                  <span>关键词扩展</span>
                  <el-input v-model="keyword" placeholder="输入核心词，如 yoga mat" style="width:280px" size="small"
                    @keyup.enter="expand" />
                  <el-button type="primary" size="small" @click="expand">AI 扩展</el-button>
                </div>
              </template>
              <div>
                <el-tag v-for="k in expanded" :key="k" class="mr8" style="margin-bottom:8px" type="info">{{ k }}</el-tag>
                <el-empty v-if="!expanded.length" description="输入关键词后点击 AI 扩展" :image-size="60" />
              </div>
            </el-card>
          </el-col>
          <el-col :span="8">
            <el-card>
              <template #header>一键 AI 选品</template>
              <el-button type="primary" style="width:100%" :loading="picking" @click="pick">
                选出机会分最高的 3 个商品
              </el-button>
              <template v-if="picked.length">
                <el-alert type="success" :closable="false" style="margin-top:12px"
                  :title="`已选出 ${picked.length} 个机会商品，可一键转入商品池`" />
                <div v-for="(item, i) in picked" :key="i" class="picked-row">
                  <span class="picked-title">{{ item.title || `候选 #${i + 1}` }}</span>
                  <el-button size="small" type="success" plain :loading="transferring === i"
                    @click="transferOne(item, i)">转入商品池</el-button>
                </div>
              </template>
              <el-divider />
              <div class="muted" style="margin-bottom:8px">
                数据飞轮：表现分由真实订单聚合（仅 api/import/manual 来源，演示数据不计入）
              </div>
              <div style="display:flex;gap:8px">
                <el-input-number v-model="perfProductId" :min="1" size="small" style="width:130px" />
                <el-button size="small" :loading="loadingPerf" @click="loadPerformance">查商品表现分</el-button>
              </div>
              <div v-if="perf" style="margin-top:12px">
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="表现分">
                    <el-tag :type="perf.has_data ? 'success' : 'info'" size="small">
                      {{ perf.performance_score }}{{ perf.has_data ? '' : '（无真实销售，中性分）' }}
                    </el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="窗口">{{ perf.window_days }} 天</el-descriptions-item>
                  <el-descriptions-item label="售出 / 销售额">
                    {{ perf.units_sold }} 件 / {{ Number(perf.revenue || 0).toFixed(2) }}（币种未知）
                  </el-descriptions-item>
                  <el-descriptions-item label="毛利率 / 退款率">
                    {{ (Number(perf.margin || 0) * 100).toFixed(1) }}% /
                    {{ (Number(perf.refund_rate || 0) * 100).toFixed(1) }}%
                  </el-descriptions-item>
                  <el-descriptions-item label="售罄率">{{ (Number(perf.sell_through || 0) * 100).toFixed(1) }}%</el-descriptions-item>
                </el-descriptions>
              </div>
            </el-card>
          </el-col>
        </el-row>

        <!-- 商品机会评分（因子透出 + 一键转入） -->
        <el-card>
          <template #header><span class="card-title">商品机会评分</span></template>
          <el-table :data="scores" size="small" v-loading="loadingScores">
            <el-table-column prop="product_id" label="商品 ID" width="90" />
            <el-table-column label="机会分" width="220">
              <template #default="{ row }">
                <el-progress :percentage="row.total" :color="row.total > 75 ? 'var(--color-success)' : 'var(--color-primary)'" />
              </template>
            </el-table-column>
            <el-table-column prop="demand" label="需求" width="80" />
            <el-table-column prop="competition" label="竞争" width="80" />
            <el-table-column prop="profit" label="利润" width="80" />
            <el-table-column prop="risk" label="风险" width="80" />
            <el-table-column prop="model" label="评分模型" width="100" />
            <el-table-column label="评分依据" show-overflow-tooltip>
              <template #default="{ row }">{{ (row.reasons || []).join('；') }}</template>
            </el-table-column>
          </el-table>
          <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="scoresTotal"
            :page-size="pageSize" v-model:current-page="page" @current-change="loadScores" />
        </el-card>
      </el-collapse-item>
    </el-collapse>

    <!-- 趋势 CSV 导入向导（格式校验错误行直出） -->
    <el-dialog v-model="trendImportDialog" title="导入真实趋势数据（CSV）" width="620px">
      <el-alert type="info" :closable="false" style="margin-bottom:10px"
        title="从平台后台或第三方工具导出关键词数据，导入后来源标记为「CSV导入」，内置演示词池不会覆盖这些真实数据。" />
      <el-input v-model="trendCsv" type="textarea" :rows="8"
        placeholder="表头需含关键词列，可选搜索量/增长率/竞争度/平台。示例：&#10;关键词,搜索量,增长率,竞争度,平台&#10;led strip lights,32000,85.2,62,google&#10;（也支持英文表头 keyword,volume,growth,competition,platform）" />
      <div style="margin-top:8px">
        <input type="file" accept=".csv,text/csv" @change="onTrendFile" />
      </div>
      <el-alert v-if="trendImportResult.errors && trendImportResult.errors.length"
        type="warning" :closable="false" style="margin-top:10px"
        :title="`${trendImportResult.errors.length} 行有问题：${trendImportResult.errors.slice(0, 3).join('；')}`" />
      <template #footer>
        <el-button @click="trendImportDialog = false">关闭</el-button>
        <el-button type="primary" :loading="trendImporting" @click="doImportTrends">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 商品发现（UX-C）：候选方向研究 + 趋势扫描 + 评分卡（因子透出）+ AI 选品一键转入商品池
 * （J1 断链归零）+ 趋势 CSV 导入向导。
 *
 * B2 重构：顶部「候选方向卡片」从评分行（按 total 取 Top N）派生，每张卡带需求证据
 * 状态（待验证 / 有依据，复用 api/csv/builtin 谱系）与「查看依据」展开；专业表格移入
 * 折叠的「高级视图」。所有筛选为真实本地语义（关键词 / 类目）；市场·预算无后端数据，
 * 仅以会话画像 chips 作为「本页范围参考」，不伪装成筛选。转池逻辑见 composables/discoveryTransfer.js。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import JourneyJ0Bar from '../../components/JourneyJ0Bar.vue'
import { canWrite } from '../../permissions/permissions'
import {
  expandKeywords, fetchPerformance, fetchScores, fetchTrendSource, fetchTrends,
  importTrends, pickCandidates, scanTrends,
} from '../../api/domains/discovery'
import { fetchProduct } from '../../api/domains/products'
import { candidateToProductPayload, transferCandidates } from '../../composables/discoveryTransfer'
import { isJourneyActive } from '../../shared/journeyJ0View'
import { loadSessionProfile } from '../../shared/onboardingProfile'
import {
  buildContextChips, deriveCandidateDirections, filterCandidatesByCategory,
  filterCandidatesByKeyword, filterTrendsByKeyword, freshnessTimestamp, listCategories,
} from '../../shared/discoveryView'

const route = useRoute()
const router = useRouter()

const topN = 5
const scoreFields = [
  { key: 'demand', label: '需求' },
  { key: 'competition', label: '竞争' },
  { key: 'profit', label: '利润' },
  { key: 'risk', label: '风险' },
]

const trends = ref([])
const keyword = ref('')
const expanded = ref([])
const picked = ref([])
const scores = ref([])
const scoresTotal = ref(0)
const page = ref(1)
const pageSize = 10
const scanning = ref(false)
const trendSource = ref({})
const trendImportDialog = ref(false)
const trendImporting = ref(false)
const trendCsv = ref('')
const trendImportResult = ref({})
const picking = ref(false)
const loadingScores = ref(false)
const perfProductId = ref(1)
const perf = ref(null)
const loadingPerf = ref(false)
const transferring = ref(null)

// B2：候选方向卡片 + 筛选 + 画像上下文
const filterKeyword = ref('')
const filterCategory = ref('')
const candidates = ref([])
const allScoreRows = ref([])
const expandedReasons = ref({})
const advancedOpen = ref([])
const profile = ref(loadSessionProfile())

const contextChips = computed(() => buildContextChips(profile.value))
const categoryOptions = computed(() => listCategories(candidates.value))
const visibleCandidates = computed(() => {
  const byCat = filterCandidatesByCategory(candidates.value, filterCategory.value)
  return filterCandidatesByKeyword(byCat, filterKeyword.value)
})
const filteredTrends = computed(() => filterTrendsByKeyword(trends.value, filterKeyword.value))
const freshnessLabel = computed(() => {
  const t = freshnessTimestamp({ trends: trends.value, scores: allScoreRows.value })
  return t ? `数据时间：${t}` : '更新时间未知'
})
const hasDemoEvidence = computed(() => candidates.value.some(
  (c) => c.evidenceKind === 'builtin' || c.evidenceKind === 'none',
))

function toggleReason(id) {
  expandedReasons.value = { ...expandedReasons.value, [id]: !expandedReasons.value[id] }
}

async function loadTrendSource() {
  try { trendSource.value = await fetchTrendSource() } catch { /* 全局拦截器已提示 */ }
}

function onTrendFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => { trendCsv.value = String(reader.result || '') }
  reader.readAsText(file, 'utf-8')
}

async function doImportTrends() {
  if (!trendCsv.value.trim()) return ElMessage.warning('请粘贴 CSV 内容或选择文件')
  trendImporting.value = true
  try {
    const data = await importTrends({ csvText: trendCsv.value })
    trendImportResult.value = data
    ElMessage.success(`导入 ${data.imported} 条，更新 ${data.updated} 条`)
    await loadTrends()
    loadTrendSource()
    loadCandidateDirections()
  } finally { trendImporting.value = false }
}

async function loadTrends() {
  const data = await fetchTrends()
  trends.value = data.items
}

async function scan() {
  scanning.value = true
  try {
    const data = await scanTrends()
    trends.value = data.items
    ElMessage.success('趋势已刷新')
    loadCandidateDirections()
  } finally { scanning.value = false }
}

async function expand() {
  if (!keyword.value.trim()) return ElMessage.warning('请输入关键词')
  const data = await expandKeywords(keyword.value)
  expanded.value = data.keywords
}

async function pick() {
  picking.value = true
  try {
    const data = await pickCandidates(3)
    picked.value = data.items
    ElMessage.success(`已选出 ${data.items.length} 个机会商品`)
  } finally { picking.value = false }
}

/** 一键转入商品池：候选转 POST /products 载荷；缺标题的候选如实报原因。 */
async function transferOne(item, index) {
  if (!candidateToProductPayload(item)) {
    ElMessage.warning('该候选缺少标题，无法转入商品池')
    return
  }
  transferring.value = index
  try {
    const { created, failed } = await transferCandidates([item])
    if (created.length) {
      ElMessage.success(`已转入商品池：${created[0].title || `#${created[0].id}`}`)
      // J0 链路：把新建的商品主档 id 透传进 query，下游步骤共享同一对象上下文
      if (isJourneyActive(route.query) && created[0].id != null) {
        router.replace({ query: { ...route.query, productId: String(created[0].id) } })
      }
    }
    if (failed.length) ElMessage.error(failed[0].reason)
  } finally { transferring.value = null }
}

async function loadScores() {
  loadingScores.value = true
  try {
    const data = await fetchScores({ page: page.value, pageSize })
    scores.value = data.items
    scoresTotal.value = data.total
  } finally { loadingScores.value = false }
}

/** 候选方向：一次拉全评分行（page_size=200）→ 取 Top N → 并行解析商品标题/类目。 */
async function loadCandidateDirections() {
  try {
    const data = await fetchScores({ page: 1, pageSize: 200 })
    const all = data.items || []
    allScoreRows.value = all
    if (!all.length) { candidates.value = []; return }
    const top0 = deriveCandidateDirections({ scores: all, productsById: {}, trends: trends.value, topN })
    const ids = top0.map((c) => c.productId)
    const map = {}
    const settled = await Promise.allSettled(ids.map((id) => fetchProduct(id)))
    settled.forEach((r, i) => {
      if (r.status === 'fulfilled' && r.value && r.value.id != null) map[ids[i]] = r.value
    })
    candidates.value = deriveCandidateDirections({ scores: all, productsById: map, trends: trends.value, topN })
  } catch { /* 全局拦截器已提示 */ }
}

async function loadPerformance() {
  loadingPerf.value = true
  try {
    perf.value = await fetchPerformance(perfProductId.value)
  } catch {
    perf.value = null
  } finally { loadingPerf.value = false }
}

onMounted(async () => {
  await Promise.all([loadTrends(), loadTrendSource(), loadScores()])
  await loadCandidateDirections()
})
</script>

<style scoped>
.card-title { font-weight: 600; }
.mb16 { margin-bottom: 16px; }
.mr8 { margin-right: 8px; }
.muted { color: var(--color-text-secondary); font-size: 12px; }
.picked-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid var(--color-border-light);
}
.picked-title { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 候选方向区 */
.section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.freshness { font-size: 12px; color: var(--color-text-secondary); }
.filter-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.profile-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: var(--radius-round);
  border: 1px solid var(--v91-border);
  white-space: nowrap;
}
.chip--ok { background: var(--v91-tint-blue); color: var(--v91-text-strong); }
.chip--gap { background: var(--v91-amber-surface); color: var(--v91-text-strong); text-decoration: none; }
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.dir-card {
  background: var(--v91-surface);
  border: 1px solid var(--v91-border);
}
.dir-card--pending { background: var(--v91-amber-surface); }
.dir-card--ok:hover { background: var(--v91-tint-blue); }
.dir-card__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.dir-card__title {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dir-card__flag {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--v91-text-strong);
  background: var(--v91-amber-surface);
  border: 1px solid var(--v91-border);
  border-radius: var(--radius-sm);
  padding: 1px 8px;
}
.score-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 14px; margin: 10px 0; }
.score-cell__k { font-size: 12px; color: var(--color-text-secondary); }
.score-cell__v { font-size: 13px; font-weight: 600; }
.dir-card__foot { display: flex; align-items: center; justify-content: space-between; }
.dir-card__total { font-size: 12px; color: var(--color-text-secondary); }
.reasons {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--v91-border);
  font-size: 12px;
}
.reasons__list { margin: 6px 0; padding-left: 18px; }
.reasons__list li { margin-bottom: 2px; }
.reasons__basis { color: var(--color-text-secondary); }
.verify-alert { margin-top: 12px; margin-bottom: 0; }
</style>
