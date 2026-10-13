<template>
  <div class="page">
    <PageHeader title="工厂首页" subtitle="本厂待办 · 我方 SKU">
      <template #actions>
        <el-tag :type="counts.connected ? 'info' : 'warning'" size="small">
          {{ counts.connected ? '待办已同步' : '待办未接入' }}
        </el-tag>
      </template>
    </PageHeader>

    <!-- 安全约束（蓝图 §9）：不展示卖家平台核价/安全底价/GMV/真实贡献利润，只收工厂身份绑定数据 -->
    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />

    <!-- 待办数据源 factory_network portal 未核 → 未接入落"暂无任务"空态，禁编造计数 -->
    <SectionState :code="code" @retry="load" @action="onAction" :error="error" empty-hint="暂无任务">
      <el-card shadow="never" class="mb16">
        <template #header><span class="card-title">今天需要处理</span></template>
        <el-row :gutter="16">
          <el-col v-for="g in TODO_GROUPS" :key="g.code" :span="8">
            <MetricCard :label="g.label + '待办'" :value="counts[g.code]" />
          </el-col>
        </el-row>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="between">
            <span class="card-title">我方 SKU 与可供货数据</span>
            <el-button link type="primary" size="small" @click="goCatalog">管理我方 SKU</el-button>
          </div>
        </template>
        <el-table :data="items" size="small">
          <el-table-column prop="factory_sku" label="工厂 SKU" width="160" />
          <el-table-column prop="title" label="产品" min-width="200" show-overflow-tooltip />
          <el-table-column prop="category" label="类目" width="120" />
          <el-table-column label="供货数据更新" width="160">
            <template #default="{ row }">
              <el-tag :type="row.verified_at ? 'success' : 'info'" size="small" effect="plain">
                {{ row.verified_at ? '已核验' : '未核验' }}
              </el-tag>
            </template>
          </el-table-column>
          <template #empty>
            <EmptyState reason="NO_DATA" :hint="emptyCopy.title" />
          </template>
        </el-table>
      </el-card>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 工厂门户首页（蓝图 R1 包 3 · FP-01，§B.3）：/factory 重定向目标。
 *
 * 本厂待办（报价/备货/贴标）+ 我方 SKU 侧栏。待办数据源 factory_network portal
 * 端点**未核** → 未接入落"暂无任务"空态（共享 factoryHome.js 判定），禁止编造待办计数。
 * 安全约束（蓝图 §9）：不展示卖家平台核价/安全底价/GMV/真实贡献利润，只收工厂身份绑定数据。
 * 11 态全区块经 SectionState code；环境标签经 DataQualityBanner（envTag 常显）。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '../../components/PageHeader.vue'
import MetricCard from '../../components/MetricCard.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { useRouter } from 'vue-router'
import { fetchPortalMe, fetchPortalProducts } from '../../api/domains/factoryNetwork'
import { envTag } from '../../shared/dataLabels'
import {
  TODO_GROUPS, hasTodoSource, todoCounts, homeStateCode, emptyHomeCopy,
} from '../../shared/factoryHome'

const envBanner = envTag()
const router = useRouter()

const counts = ref({ quote: 0, stocking: 0, labeling: 0, total: 0, connected: false })
const items = ref([])
const code = ref('LOADING')
const error = ref('')

const emptyCopy = emptyHomeCopy()

async function load() {
  code.value = 'LOADING'
  error.value = ''
  try {
    const [me, products] = await Promise.all([fetchPortalMe(), fetchPortalProducts()])
    counts.value = todoCounts(hasTodoSource(me) ? me : null)
    items.value = (products?.items || []).slice(0, 8)
    code.value = homeStateCode(false, false, counts.value)
  } catch (e) {
    const detail = e?.response?.data?.detail
    error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
    code.value = 'ERROR'
  }
}

function onAction(c) {
  if (c === 'EMPTY_NEW') ElMessage.info('本厂待办数据源待接入；我方 SKU 维护请进入「产品与产能」')
}

function goCatalog() {
  router.push('/factory/products')
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.card-title { font-weight: 600; }
.between { display: flex; justify-content: space-between; align-items: center; }
</style>
