<template>
  <div class="page">
    <el-card class="filters">
      <el-select v-model="q.product_id" placeholder="商品" filterable clearable style="width:180px" @change="reload">
        <el-option v-for="p in productOptions" :key="p.id" :label="`#${p.id} ${p.title}`" :value="p.id" />
      </el-select>
      <el-select v-model="q.shop_id" placeholder="Store" clearable style="width:180px" @change="reload">
        <el-option v-for="s in shops" :key="s.id" :label="`${s.platform} · ${s.name}`" :value="s.id" />
      </el-select>
      <el-select v-model="q.platform" placeholder="平台" clearable style="width:130px" @change="reload">
        <el-option v-for="p in platforms" :key="p" :label="p" :value="p" />
      </el-select>
      <el-select v-model="q.market" placeholder="市场" clearable style="width:110px" @change="reload">
        <el-option v-for="m in markets" :key="m" :label="m" :value="m" />
      </el-select>
      <el-select v-model="q.execution_status" placeholder="执行状态" clearable style="width:150px" @change="reload">
        <el-option v-for="(meta, key) in EXECUTION_STATUS" :key="key" :label="meta.text" :value="key" />
      </el-select>
      <el-input v-model.number="q.owner_user_id" placeholder="责任人 ID" clearable style="width:120px" @change="reload" />
      <el-checkbox v-model="q.mine" @change="reload">需我处理</el-checkbox>
      <el-checkbox v-model="q.waiting_platform" @change="reload">等待平台</el-checkbox>
      <el-checkbox v-model="q.blocked_only" @change="reload">仅阻断</el-checkbox>
      <el-checkbox v-model="q.include_history" @change="reload">含历史</el-checkbox>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="primary" :loading="loading" @click="reload">刷新</el-button>
    </el-card>

    <el-card v-loading="loading">
      <el-empty v-if="!loading && !items.length" :description="empty.text" :image-size="80">
        <div class="empty-hint">{{ empty.hint }}</div>
        <el-button v-if="empty.action === 'retry'" type="primary" @click="reload">重试</el-button>
        <el-button v-else-if="empty.action === 'clear_filters'" @click="resetFilters">清除筛选</el-button>
        <el-button v-else-if="empty.action === 'add_shop'" @click="goShops">去店铺授权</el-button>
      </el-empty>

      <template v-else>
        <el-table :data="items" size="small" class="clickable" @row-click="openDetail">
          <el-table-column label="商品" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.product ? row.product.title : '—' }}</template>
          </el-table-column>
          <el-table-column label="目标平台 · Store" min-width="170" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.store">{{ row.store.platform }} · {{ row.store.name }}</span><span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="国家" width="78">
            <template #default="{ row }">{{ row.market || '—' }}</template>
          </el-table-column>
          <el-table-column label="履约方式" width="110">
            <template #default="{ row }">{{ row.fulfillment_mode || '—' }}</template>
          </el-table-column>
          <el-table-column label="执行状态" width="118">
            <template #default="{ row }">
              <el-tag size="small" :type="executionStatusMeta(row.execution_status).tag">
                {{ executionStatusMeta(row.execution_status).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="平台状态" width="126">
            <template #default="{ row }">
              <el-tag size="small" :type="platformStatusMeta(row.platform_status).tag">
                {{ platformStatusMeta(row.platform_status).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="完成/总数" width="96">
            <template #default="{ row }">{{ progressText(row.progress) }}</template>
          </el-table-column>
          <el-table-column label="阻断摘要" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span :class="{ affected: row.blocked_summary?.length }">{{ blockerText(row.blocked_summary) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="下一动作" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span :class="{ muted: !row.next_action?.executable }">{{ nextActionText(row.next_action) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="责任人" width="100">
            <template #default="{ row }">{{ ownerText(row.owner) }}</template>
          </el-table-column>
          <el-table-column label="环境 / 核验" min-width="200">
            <template #default="{ row }">
              <el-tag v-if="row.verification_notice" size="small" type="warning" effect="plain">
                {{ row.verification_notice }}
              </el-tag>
              <el-tag v-else size="small" type="success" effect="plain">正式接入</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
          :page-size="pageSize" v-model:current-page="pageNum" @current-change="load" />
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api'
import {
  EXECUTION_STATUS,
  blockerText,
  buildReturnTo,
  detailPath,
  emptyStateReason,
  executionStatusMeta,
  listLaunches,
  listQuery,
  loadContext,
  nextActionText,
  ownerText,
  parseReturnTo,
  platformStatusMeta,
  progressText,
} from '../composables/launchCenter'

const route = useRoute()
const router = useRouter()

const q = reactive({
  product_id: null, shop_id: null, platform: '', market: '', execution_status: '',
  owner_user_id: null, mine: false, waiting_platform: false, blocked_only: false, include_history: false,
})
const pageNum = ref(1)
const pageSize = ref(20)
const items = ref([])
const total = ref(0)
const loading = ref(false)
const context = ref(null)
const error = ref(null)
const productOptions = ref([])

const shops = computed(() => context.value?.shops || [])
const platforms = computed(() => [...new Set(shops.value.map((s) => s.platform).filter(Boolean))])
const markets = computed(() => [...new Set(shops.value.map((s) => s.market).filter(Boolean))])
const empty = computed(() => emptyStateReason({
  context: context.value, filters: q, error: error.value, total: total.value,
}))

async function loadContextSafely() {
  try { context.value = await loadContext() } catch { context.value = null }
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const data = await listLaunches(listQuery(q, { pageNum: pageNum.value, pageSize: pageSize.value }))
    items.value = data.items || []
    total.value = data.total || 0
  } catch (err) {
    error.value = err
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function reload() {
  pageNum.value = 1
  load()
}

function resetFilters() {
  Object.assign(q, {
    product_id: null, shop_id: null, platform: '', market: '', execution_status: '',
    owner_user_id: null, mine: false, waiting_platform: false, blocked_only: false, include_history: false,
  })
  reload()
}

function openDetail(row) {
  router.push(detailPath(row.id, buildReturnTo(q)))
}

function goShops() {
  router.push('/shops')
}

async function loadProducts() {
  try {
    const { data } = await api.get('/products', { params: { page_num: 1, page_size: 50 } })
    productOptions.value = data.items || []
  } catch {
    productOptions.value = []
  }
}

onMounted(async () => {
  // 从详情返回时按 return_to 还原筛选（AC-14.7；白名单由数据层校验）。
  const restored = parseReturnTo(route.query.return_to)
  if (restored) Object.assign(q, restored)
  await Promise.all([loadContextSafely(), loadProducts()])
  load()
})
</script>

<style scoped>
.filters { margin-bottom: 16px; }
.filters :deep(.el-card__body) { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.clickable :deep(.el-table__row) { cursor: pointer; }
.empty-hint { color: #909399; margin-bottom: 8px; }
.muted { color: #a8abb2; }
.affected { color: #e6a23c; }
</style>
