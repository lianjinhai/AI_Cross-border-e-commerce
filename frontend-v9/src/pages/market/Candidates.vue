<template>
  <div class="page">
    <JourneyJ0Bar />
    <PageHeader title="商品候选池" subtitle="发现与商品 · 候选商品聚合">
      <template #filters>
        <el-select v-model="sourceFilter" size="small" placeholder="来源" clearable style="width:140px">
          <el-option label="平台 API" value="api" />
          <el-option label="外部导入" value="external" />
          <el-option label="人工录入" value="manual" />
          <el-option label="内置演示" value="builtin" />
        </el-select>
      </template>
      <template #actions>
        <el-tag size="small" type="info">API_GAP · 候选端点未核</el-tag>
      </template>
    </PageHeader>

    <!-- J0 建立商品销售准备任务面板（仅末步 candidates 且 journey=j0 时显示） -->
    <el-card v-if="journeyActive" class="j0-prepare mb16" shadow="never">
      <template #header><span class="j0-prepare__title">建立商品销售准备任务</span></template>
      <el-alert type="info" :closable="false" class="mb12"
        title="真实含义：为所选商品建立商品主档（POST /products）"
        description="系统暂无独立的「销售准备任务」写端点（后端缺口，见交付报告），因此本向导以「商品主档」作为统一的准备载体——它才是后续上架/销售真正依赖的真实对象。不会伪造任务或自动建单。" />
      <div v-if="productId" class="j0-prepare__row">
        <span>已带入对象：</span>
        <el-tag size="small" type="success">商品主档 #{{ productId }} 已建立</el-tag>
        <EntityLink object-type="product" :object-id="productId" :return-to="`/app/market/candidates?journey=j0&productId=${productId}`" />
        <span class="j0-prepare__hint">（在「研究商品方向」转入商品池即已创建该主档）</span>
      </div>
      <el-alert v-else type="warning" :closable="false" class="mb12"
        title="尚未选定商品"
        description="请先在「研究商品方向」把候选转入商品池建立商品主档，再回到本步确认准备完成。" />
      <div class="j0-prepare__next">
        <el-button v-if="!productId" size="small" @click="goDiscovery">返回：研究商品方向</el-button>
        <span class="j0-prepare__hint">下一步真实动作：进入上线中心准备上架（独立工作流模块，本向导不强制）。</span>
      </div>
    </el-card>

    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />

    <!-- MK-03：Product Candidate 读端点未核（§7#13）→ 降级 products+来源筛选，角标 API_GAP；无货源也能保存机会 -->
    <SectionState :code="code" @retry="fetchAll" @action="onAction" :error="error">
      <DataQualityBanner
        tag="API_UNVERIFIED"
        detail="候选池端点未核，当前为商品库 + 来源筛选的降级视图（无货源时仍可保存机会）"
      />
      <el-table :data="filtered" size="small" class="mb16">
        <el-table-column prop="title" label="商品" show-overflow-tooltip />
        <el-table-column label="来源" width="120">
          <template #default="{ row }">
            <DataQualityBanner :tag="sourceTagOf(row.source)" detail="" style="margin:0" />
          </template>
        </el-table-column>
        <el-table-column label="数据可信度" width="140">
          <template #default="{ row }">
            <el-tag :type="tagToneOf(row.source)" size="small" effect="plain">
              {{ tagLabelOf(row.source) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <EntityLink object-type="product" :object-id="row.id" :return-to="'/app/market/candidates'" />
            <el-button link type="primary" size="small" @click="onSaveOpportunity(row)">保存为机会</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-alert
        v-if="!filtered.length && code === 'ready'"
        type="info" :closable="false" show-icon
        title="没有候选商品"
        description="没有货源也能保存机会：先保存机会，待候选端点接入后自动关联。"
      />
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 商品候选池（蓝图 R1 MK-03，P0）：/app/market/candidates。
 *
 * API_GAP（§7#13）：Product Candidate 读端点未核 → 降级实现：products 已接端点
 * + 来源筛选，角标"API_GAP"；无货源也能保存机会（保存动作走 TODO：机会写端点
 * 未接入时按钮只触发本地标记，不冒充成功——此处保存为前端草稿记录 + 明示待接入）。
 * 来源字段用 dataLabels 的 8 种标签如实标注可信度。每页 11 态全区块经 SectionState。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EntityLink from '../../components/EntityLink.vue'
import JourneyJ0Bar from '../../components/JourneyJ0Bar.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchProducts } from '../../api/domains/products'
import { tagInfo, envTag, DATA_TAGS } from '../../shared/dataLabels'
import { isJourneyActive } from '../../shared/journeyJ0View'

const route = useRoute()
const router = useRouter()

const envBanner = envTag()
const journeyActive = computed(() => isJourneyActive(route.query))
const productId = computed(() => route.query.productId || '')
function goDiscovery() {
  router.push({ path: '/app/market/discovery', query: { journey: 'j0' } })
}

const code = ref('LOADING')
const error = ref('')
const items = ref([])
const sourceFilter = ref('')

/** 来源 → dataLabels 8 标签码映射。 */
function sourceTagOf(source) {
  const s = String(source || '').toLowerCase()
  if (s === 'api' || s === 'platform') return 'API_UNVERIFIED'
  if (s === 'external' || s === 'csv' || s === 'import') return 'EXTERNAL_IMPORT'
  if (s === 'manual' || s === 'operator') return 'MANUAL_UNVERIFIED'
  if (s === 'builtin' || s === 'demo') return 'DEMO'
  return 'UNKNOWN'
}
const tagToneOf = (source) => tagInfo(sourceTagOf(source)).tone
const tagLabelOf = (source) => tagInfo(sourceTagOf(source)).label

const filtered = computed(() => {
  const list = items.value
  if (!sourceFilter.value) return list
  return list.filter((p) => {
    const s = String(p.source || '').toLowerCase()
    const map = {
      api: ['api', 'platform'],
      external: ['external', 'csv', 'import'],
      manual: ['manual', 'operator'],
      builtin: ['builtin', 'demo'],
    }
    return (map[sourceFilter.value] || [sourceFilter.value]).includes(s)
  })
})

function onAction(code_) {
  if (code_ === 'NOT_CONFIGURED') ElMessage.info('候选端点未接入，当前为降级视图')
}

/** 保存机会：机会写端点未接入 → 前端草稿 + 明示"待接入"，不冒充成功。 */
function onSaveOpportunity(row) {
  const drafts = JSON.parse(localStorage.getItem('v9_opportunity_drafts') || '[]')
  drafts.push({
    product_id: row.id,
    title: row.title,
    source: row.source,
    saved_at: new Date().toISOString(),
  })
  localStorage.setItem('v9_opportunity_drafts', JSON.stringify(drafts))
  ElMessage.info('机会已存为草稿（机会写端点待接入，正式保存需后端支持）')
}

async function fetchAll() {
  code.value = 'LOADING'
  error.value = ''
  try {
    const data = await fetchProducts({ page: 1 })
    items.value = Array.isArray(data?.items) ? data.items : []
    code.value = items.value.length ? 'ready' : 'EMPTY_NEW'
  } catch (e) {
    const detail = e?.response?.data?.detail
    error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
    code.value = 'ERROR'
  }
}

onMounted(fetchAll)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.j0-prepare__title { font-weight: 600; }
.j0-prepare__row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.j0-prepare__next { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.j0-prepare__hint { color: var(--color-text-secondary); font-size: 12px; }
.mb12 { margin-bottom: 12px; }
</style>
