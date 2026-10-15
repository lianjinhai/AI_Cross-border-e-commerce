<template>
  <div class="page">
    <PageHeader title="Listing 工作台" subtitle="生成 → 编辑预览 → 合规 → 发布 → 回执（单页分步流）">
      <template #actions>
        <el-button v-if="returnTo" size="small" @click="goBackToTasks">返回待办</el-button>
        <el-button v-if="canWrite()" type="primary" size="small" @click="openFlow(null)">AI 生成 Listing</el-button>
      </template>
    </PageHeader>

    <!-- 单页分步流（选中 Listing 时替换列表视图；关闭即回到列表，无路由断点） -->
    <el-card v-if="flowVisible" class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">Listing 分步流{{ flowListing.id ? `（#${flowListing.id}）` : '' }}</span>
          <el-button link size="small" @click="flowVisible = false">返回列表</el-button>
        </div>
      </template>
      <ListingFlow :listing="flowListing.id ? flowListing : null" @exit="closeFlow" @updated="onFlowUpdated" />
    </el-card>

    <template v-else>
      <el-card class="mb16">
        <div class="filter-bar">
          <el-input v-model="q.keyword" placeholder="标题/商品搜索" style="width:200px" size="small" clearable @change="reload" />
          <el-select v-model="q.platform" placeholder="平台" style="width:130px" size="small" clearable @change="reload">
            <el-option v-for="p in PLATFORMS" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
          <el-select v-model="q.status" placeholder="状态" style="width:130px" size="small" clearable @change="reload">
            <el-option label="草稿" value="draft" /><el-option label="已发布" value="published" />
          </el-select>
        </div>
      </el-card>

      <el-card>
        <el-table :data="items" v-loading="loading" size="small">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="product_title" label="商品" min-width="180" show-overflow-tooltip />
          <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
          <el-table-column prop="platform" label="平台" width="90" />
          <el-table-column label="风险" width="90">
            <template #default="{ row }">
              <el-tag :type="row.risk_level === 'high' ? 'danger' : 'info'" size="small">
                {{ row.risk_level || 'normal' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" @click="openFlow(row)">分步流</el-button>
              <el-button v-if="row.status === 'published'" size="small" @click="openFlow(row)">查看回执</el-button>
            </template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="还没有 Listing，点击右上角开始 AI 生成" /></template>
        </el-table>
        <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
          :page-size="pageSize" v-model:current-page="page" @current-change="load" />
      </el-card>

      <!-- 发布审批队列（常驻面板：批准 → 单独执行上架） -->
      <PublishActions class="mt16" @executed="load" />
    </template>
  </div>
</template>

<script setup>
/**
 * Listing 工作台（UX-C）：单页分步流（ListingFlow，无路由断点）+ 列表 + 保存视图筛选。
 * PublicationReceipts 常驻于分步流「回执」步骤；发布审批队列常驻列表页。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import EmptyState from '../../components/EmptyState.vue'
import ListingFlow from '../../features/listings/ListingFlow.vue'
import PublishActions from '../../features/listings/PublishActions.vue'
import { canWrite } from '../../permissions/permissions'
import { fetchListings } from '../../api/domains/listings'
import { safeReturnToTasks } from '../../shared/taskCenterView'

const PLATFORMS = [
  { value: 'tiktok', label: 'TikTok Shop' },
  { value: 'amazon', label: 'Amazon' },
  { value: 'shopee', label: 'Shopee' },
]

const route = useRoute()
const router = useRouter()

/** J2 闭环：从待办点入时带 return_to=/app/tasks?...，规范化后回跳（无则隐藏按钮）。 */
const returnTo = computed(() => {
  const v = route.query.return_to
  return typeof v === 'string' ? safeReturnToTasks(v) : ''
})
function goBackToTasks() {
  router.push(returnTo.value || '/app/tasks')
}

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const q = reactive({ keyword: '', platform: '', status: '' })
const flowVisible = ref(false)
const flowListing = ref({})

async function load() {
  loading.value = true
  try {
    const data = await fetchListings({ page: page.value, platform: q.platform, status: q.status })
    items.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

function reload() {
  page.value = 1
  load()
}

function openFlow(row) {
  flowListing.value = row ? { ...row } : {}
  flowVisible.value = true
}

function closeFlow() {
  flowVisible.value = false
  flowListing.value = {}
  load()
}

function onFlowUpdated(updated) {
  flowListing.value = { ...flowListing.value, ...updated }
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.mt16 { margin-top: 16px; }
.between { display: flex; justify-content: space-between; align-items: center; }
.card-title { font-weight: 600; }
.filter-bar { display: flex; gap: 12px; flex-wrap: wrap; }
</style>
