<template>
  <div class="page">
    <PageHeader title="商品发现" subtitle="市场趋势 · 机会评分 · 一键选品落池">
      <template #actions>
        <el-button v-if="canWrite" size="small" @click="trendImportDialog = true">导入真实趋势</el-button>
        <el-button v-if="canWrite" type="primary" size="small" :loading="scanning" @click="scan">AI 扫描趋势</el-button>
      </template>
    </PageHeader>

    <!-- 市场趋势 -->
    <el-card class="mb16">
      <template #header><span class="card-title">市场趋势（关键词 × 平台 × 30天增长）</span></template>
      <!-- 数据来源如实提示，演示数据不伪装成真实数据 -->
      <el-alert v-if="trendSource.hint" :title="trendSource.hint" :closable="false"
        :type="trendSource.has_real_data ? 'success' : 'warning'" style="margin-bottom:10px" />
      <el-table :data="trends" size="small" max-height="260">
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
                {{ perf.units_sold }} 件 / ${{ Number(perf.revenue || 0).toFixed(2) }}
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
 * 商品发现（UX-C）：趋势扫描 + 评分卡（因子透出）+ AI 选品一键转入商品池
 * （J1 断链归零）+ 趋势 CSV 导入向导。转池逻辑见 composables/discoveryTransfer.js。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import { canWrite } from '../../permissions/permissions'
import {
  expandKeywords, fetchPerformance, fetchScores, fetchTrendSource, fetchTrends,
  importTrends, pickCandidates, scanTrends,
} from '../../api/domains/discovery'
import { candidateToProductPayload, transferCandidates } from '../../composables/discoveryTransfer'

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
    if (created.length) ElMessage.success(`已转入商品池：${created[0].title || `#${created[0].id}`}`)
    if (failed.length) ElMessage.error(failed[0].reason)
  } finally { transferring.value = null }
}

async function loadScores() {
  loadingScores.value = true
  try {
    const data = await fetchScores({ page: page.value })
    scores.value = data.items
    scoresTotal.value = data.total
  } finally { loadingScores.value = false }
}

async function loadPerformance() {
  loadingPerf.value = true
  try {
    perf.value = await fetchPerformance(perfProductId.value)
  } catch {
    perf.value = null
  } finally { loadingPerf.value = false }
}

onMounted(() => { loadTrends(); loadTrendSource(); loadScores() })
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
</style>
