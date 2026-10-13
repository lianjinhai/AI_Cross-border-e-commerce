<template>
  <div class="page">
    <PageHeader title="合规报告" subtitle="发现与商品 · 合规报告中心">
      <template #actions>
        <el-tag size="small" type="info">待接入</el-tag>
      </template>
    </PageHeader>

    <!-- 数据质量标签常显（部署层注入） -->
    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />

    <!-- API_GAP：compliance 域端点未核 → 只读骨架 + 明示"待接入"，禁假按钮/假数据/假成功态 -->
    <SectionState :code="code" @retry="fetchAll" @action="onAction" :error="error">
      <!-- 报告区：未接 → NOT_CONFIGURED（未连接合规服务） -->
      <el-card class="mb16" shadow="never">
        <template #header>
          <div class="between"><span class="card-title">合规检测</span><span class="scope">API_GAP · 后端未接入</span></div>
        </template>
        <el-alert
          type="info" :closable="false" show-icon
          title="合规报告待接入"
          description="合规检测端点尚未接入，当前无真实报告数据。本区块为只读占位，不显示任何虚假报告或成功态。"
        />
      </el-card>

      <!-- 关联 Listing 评审队列（listings 域已接，可用真实数据） -->
      <el-card class="mb16" shadow="never">
        <template #header>
          <div class="between"><span class="card-title">待评审 Listing</span><span class="scope">来源：listings 评审队列</span></div>
        </template>
        <SectionState :code="reviewCode" @retry="loadReviews">
          <el-table v-if="reviewCode === 'ready'" :data="reviewItems" size="small">
            <el-table-column prop="product" label="商品" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="110">
              <template #default="{ row }"><StatusBadge :status="row.status" /></template>
            </el-table-column>
            <el-table-column prop="updated_at" label="更新时间" width="170" />
          </el-table>
        </SectionState>
      </el-card>

      <!-- 业务状态区：BusinessStatus（未核验默认中性样式） -->
      <el-card shadow="never">
        <template #header><span class="card-title">服务状态</span></template>
        <BusinessStatus standard="WAITING_EXTERNAL" note="合规服务接入待完成，当前无实时检测数据" />
      </el-card>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 合规报告中心（蓝图 R1 CO-01，P0，替换 StubPage）：/app/compliance。
 *
 * API_GAP：compliance 域端点未核（§7）→ 只读骨架 + 明示"待接入"，禁止假按钮/假数据/假成功态。
 * 已接的 listings 评审队列区用真实数据；金额/来源字段用 dataLabels。每页 11 态全区块
 * 经 SectionState 渲染，文案不页面自写。
 */
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import BusinessStatus from '../../components/BusinessStatus.vue'
import { fetchListings } from '../../api/domains/listings'
import { envTag } from '../../shared/dataLabels'

const envBanner = envTag()

const code = ref('LOADING')
const error = ref('')
const reviewItems = ref([])
const reviewLoading = ref(false)

/** 评审队列 11 态。 */
const reviewCode = computed(() => {
  if (reviewLoading.value) return 'LOADING'
  if (!reviewItems.value.length) return 'EMPTY_NEW'
  return 'ready'
})

function onAction() { /* NOT_CONFIGURED 主行动：进入设置（本无设置项，无操作） */ }

async function loadReviews() {
  reviewLoading.value = true
  try {
    const data = await fetchListings({ status: 'pending_review' })
    reviewItems.value = (data?.items || []).slice(0, 20)
  } catch {
    reviewItems.value = [] // 次级区失败不阻断主流程（合规域未接，评审区独立降级）
  } finally {
    reviewLoading.value = false
  }
}

async function fetchAll() {
  code.value = 'LOADING'
  error.value = ''
  try {
    // 合规域 API_GAP：无真实端点，直接落 NOT_CONFIGURED（不造假数据）
    await loadReviews()
    code.value = 'NOT_CONFIGURED'
  } catch (e) {
    const detail = e?.response?.data?.detail
    error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
    code.value = 'ERROR'
  }
}

onMounted(fetchAll)
</script>

<style scoped>
.between { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.card-title { font-size: 15px; font-weight: 600; }
.scope { color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.mb16 { margin-bottom: 16px; }
</style>
