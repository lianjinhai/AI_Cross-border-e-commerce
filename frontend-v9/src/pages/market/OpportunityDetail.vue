<template>
  <div class="page">
    <PageHeader title="市场机会" subtitle="发现与商品 · 机会详情">
      <template #actions>
        <EntityLink
          v-if="opportunity.id"
          object-type="market"
          :object-id="opportunity.id"
          :return-to="'/app/market/discovery'"
        >返回发现页</EntityLink>
      </template>
    </PageHeader>

    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />

    <!-- 详情端点 API_GAP（§7 缺独立详情端点）→ 读端点聚合 + 明示"待接入"，禁假数据 -->
    <SectionState :code="code" @retry="fetchAll" :error="error">
      <!-- 机会概要：discovery 读端点聚合（趋势/评分/来源），来源用 dataLabels 如实区分 -->
      <el-card class="mb16" shadow="never">
        <template #header>
          <div class="between"><span class="card-title">{{ opportunity.title || '机会详情' }}</span>
            <DataQualityBanner v-if="opportunity.source" :tag="sourceTag" detail="" style="margin:0" />
          </div>
        </template>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="机会分">{{ opportunity.score ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="数据来源">{{ sourceLabel }}</el-descriptions-item>
          <el-descriptions-item label="类别">{{ opportunity.category || '—' }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ opportunity.updated_at || '—' }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 证据区：EvidencePanel（未核验默认中性，来源/时效/适用范围） -->
      <el-card class="mb16" shadow="never">
        <template #header><span class="card-title">决策依据</span></template>
        <EvidencePanel
          :items="opportunity.evidence || []"
          :risks="opportunity.risks || []"
          :source="opportunity.source"
          :verified="false"
          :scope="opportunity.scope || '单机会'"
          :expires-at="opportunity.expires_at || ''"
        />
      </el-card>

      <!-- 相关商品（discovery pick → 候选，走 products 已接端点） -->
      <el-card shadow="never">
        <template #header>
          <div class="between"><span class="card-title">相关候选</span><span class="scope">来源：discovery/pick（已接）</span></div>
        </template>
        <SectionState :code="relatedCode" @retry="loadRelated">
          <el-table v-if="relatedCode === 'ready'" :data="related" size="small">
            <el-table-column prop="title" label="商品" show-overflow-tooltip />
            <el-table-column prop="score" label="机会分" width="100" />
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <EntityLink object-type="product" :object-id="row.id" :return-to="'/app/market/discovery'" />
              </template>
            </el-table-column>
          </el-table>
        </SectionState>
      </el-card>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 市场机会详情（蓝图 R1 MK-02，P0，hidden）：/app/market/opportunity/:id。
 *
 * API_GAP：缺独立机会详情端点（§7）→ 读端点聚合（discovery 趋势/评分/pick），
 * 无真实端点处标"待接入"，禁假数据。来源字段用 dataLabels 如实区分
 * （api/csv/builtin）。每页 11 态全区块经 SectionState 渲染。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EvidencePanel from '../../components/EvidencePanel.vue'
import EntityLink from '../../components/EntityLink.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchTrends, fetchScores, pickCandidates } from '../../api/domains/discovery'
import { tagInfo, envTag } from '../../shared/dataLabels'

const route = useRoute()
const envBanner = envTag()

/** 机会 id（:id）；本页当前由 discovery 列表行进入。 */
const opportunityId = computed(() => String(route.params.id || ''))

const code = ref('LOADING')
const error = ref('')
const opportunity = ref({ id: opportunityId.value })
const related = ref([])
const relatedLoading = ref(false)

/** 来源 → dataLabels 标签码（api→API_UNVERIFIED / csv·external→EXTERNAL_IMPORT / builtin→MANUAL_UNVERIFIED）。 */
const sourceTag = computed(() => {
  const src = String(opportunity.value.source || '').toLowerCase()
  if (src === 'api') return 'API_UNVERIFIED'
  if (src === 'csv' || src === 'external' || src === 'import') return 'EXTERNAL_IMPORT'
  return 'MANUAL_UNVERIFIED'
})
const sourceLabel = computed(() => tagInfo(sourceTag.value).label)

const relatedCode = computed(() => {
  if (relatedLoading.value) return 'LOADING'
  if (!related.value.length) return 'EMPTY_NEW'
  return 'ready'
})

async function loadRelated() {
  relatedLoading.value = true
  try {
    const data = await pickCandidates(5)
    related.value = Array.isArray(data?.items) ? data.items : (Array.isArray(data) ? data : [])
  } catch {
    related.value = []
  } finally {
    relatedLoading.value = false
  }
}

async function fetchAll() {
  code.value = 'LOADING'
  error.value = ''
  try {
    // 无独立详情端点：尝试从趋势/评分聚合出该机会（有则填，无则落 NOT_CONFIGURED）
    const [trends, scores] = await Promise.all([fetchTrends().catch(() => null), fetchScores().catch(() => null)])
    const trendList = trends?.items || []
    const found = trendList.find((t) => String(t.id) === opportunityId.value)
    if (found) {
      opportunity.value = {
        ...found,
        id: opportunityId.value,
        score: found.score ?? scores?.items?.[0]?.score,
      }
      code.value = 'ready'
    } else {
      // 未命中 → 只读占位，明示"机会详情端点待接入"
      opportunity.value = { id: opportunityId.value }
      code.value = 'NOT_CONFIGURED'
    }
    await loadRelated()
  } catch (e) {
    const detail = e?.response?.data?.detail
    error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
    code.value = 'ERROR'
  }
}

onMounted(fetchAll)
watch(opportunityId, fetchAll)
</script>

<style scoped>
.between { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.card-title { font-size: 15px; font-weight: 600; }
.scope { color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.mb16 { margin-bottom: 16px; }
</style>
