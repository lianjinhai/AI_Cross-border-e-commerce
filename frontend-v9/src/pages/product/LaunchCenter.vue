<template>
  <div class="page">
    <PageHeader title="上线中心" subtitle="创建上线向导 · 保存视图 · 空态分因">
      <template #actions>
        <el-button v-if="canWrite()" type="primary" size="small" @click="openWizard">创建上线流程</el-button>
      </template>
    </PageHeader>

    <el-card class="mb16">
      <AdvancedFilter saved-views-key="launch" :filters="filters">
        <el-select v-model="filters.execution_status" placeholder="执行状态" style="width:150px" size="small" clearable @change="reload">
          <el-option v-for="(meta, key) in EXECUTION_STATUS" :key="key" :label="meta.text" :value="key" />
        </el-select>
        <el-select v-model="filters.shop_id" placeholder="店铺" style="width:160px" size="small" clearable filterable @change="reload">
          <el-option v-for="s in contextShops" :key="s.id" :label="s.shop_name || `#${s.id}`" :value="s.id" />
        </el-select>
        <el-checkbox v-model="filters.mine" size="small" @change="reload">只看我的</el-checkbox>
        <el-checkbox v-model="filters.blocked_only" size="small" @change="reload">只看阻断</el-checkbox>
      </AdvancedFilter>
    </el-card>

    <el-card>
      <SectionState :state="listState" :error="error" @retry="load" :empty-hint="emptyHint">
        <el-table :data="items" v-loading="loading" size="small" @row-click="openDetail">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="product_title" label="商品" min-width="160" show-overflow-tooltip />
          <el-table-column prop="shop_name" label="店铺" width="140" show-overflow-tooltip />
          <el-table-column label="进度" width="90">
            <template #default="{ row }">{{ progressText(row.progress) }}</template>
          </el-table-column>
          <el-table-column label="执行状态" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="executionStatusMeta(row.execution_status).tag">
                {{ executionStatusMeta(row.execution_status).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="下一动作" min-width="200">
            <template #default="{ row }">{{ nextActionText(row.next_action) }}</template>
          </el-table-column>
          <el-table-column label="业务摘要" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ guidedSummary(row) }}</template>
          </el-table-column>
        </el-table>
        <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
          :page-size="pageSize" v-model:current-page="page" @current-change="load" />
      </SectionState>
    </el-card>

    <!-- 创建上线向导：选商品 → 选店铺 → 确认 -->
    <el-dialog v-model="wizardVisible" title="创建上线流程" width="560px" :close-on-click-modal="false">
      <el-steps :active="wizardStep" align-center finish-status="success" class="mb12">
        <el-step title="选商品" /><el-step title="选店铺" /><el-step title="确认创建" />
      </el-steps>
      <div v-if="wizardStep === 0">
        <el-select v-model="wizard.productId" filterable placeholder="搜索商品标题" style="width:100%">
          <el-option v-for="p in products" :key="p.id" :label="`#${p.id} ${p.title}`" :value="p.id" />
        </el-select>
      </div>
      <div v-else-if="wizardStep === 1">
        <el-alert v-if="!usableShops.length" type="warning" :closable="false"
          title="没有可用的销售店铺：请先到「店铺授权」完成授权" />
        <el-select v-else v-model="wizard.shopId" filterable placeholder="选择已授权销售店铺" style="width:100%">
          <el-option v-for="s in usableShops" :key="s.id" :label="s.shop_name || `#${s.id}`" :value="s.id" />
        </el-select>
      </div>
      <el-descriptions v-else :column="1" border size="small">
        <el-descriptions-item label="商品">{{ wizardProductTitle }}</el-descriptions-item>
        <el-descriptions-item label="店铺">{{ wizardShopName }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="wizardVisible = false">取消</el-button>
        <el-button v-if="wizardStep > 0" @click="wizardStep -= 1">上一步</el-button>
        <el-button v-if="wizardStep < 2" type="primary" :disabled="!wizard.productId" @click="wizardStep += 1">下一步</el-button>
        <el-button v-else type="primary" :loading="creating" :disabled="!wizard.shopId" @click="doCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 上线中心（UX-C）：创建向导化（选商品→选店铺→确认）+ 筛选保存视图。
 * 列表/上下文/空态分因/return_to 往返全部复用 composables/launchCenter.js（T03 冻结契约）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import AdvancedFilter from '../../components/AdvancedFilter.vue'
import { canWrite } from '../../permissions/permissions'
import { fetchProducts } from '../../api/domains/products'
import {
  EXECUTION_STATUS, buildReturnTo, createLaunch, detailPath, emptyStateReason, errorEnvelope,
  executionStatusMeta, guidedSummary, listLaunches, listQuery, loadContext,
  nextActionText, parseReturnTo, progressText,
} from '../../composables/launchCenter'

const router = useRouter()
const route = useRoute()

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const error = ref('')
const context = ref(null)
const filters = reactive({ execution_status: '', shop_id: null, mine: false, blocked_only: false })
const wizardVisible = ref(false)
const wizardStep = ref(0)
const wizard = reactive({ productId: null, shopId: null })
const products = ref([])
const creating = ref(false)

const contextShops = computed(() => context.value?.shops || [])
const usableShops = computed(() => contextShops.value.filter((s) => s.usable))
const wizardProductTitle = computed(() => {
  const p = products.value.find((x) => x.id === wizard.productId)
  return p ? `#${p.id} ${p.title}` : '—'
})
const wizardShopName = computed(() => {
  const s = contextShops.value.find((x) => x.id === wizard.shopId)
  return s ? (s.shop_name || `#${s.id}`) : '—'
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listLaunches(listQuery({ ...filters }, { pageNum: page.value, pageSize }))
    items.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    error.value = errorEnvelope(e).message
  } finally { loading.value = false }
}

async function loadContextData() {
  try { context.value = await loadContext() } catch { context.value = null }
}

function reload() {
  page.value = 1
  load()
}

const emptyReason = computed(() => emptyStateReason({
  context: context.value, filters: { ...filters }, error: error.value || null, total: total.value,
}))
const emptyHint = computed(() => emptyReason.value.hint || '')
const listState = computed(() => {
  if (loading.value && !items.value.length) return 'loading'
  if (error.value) return 'error'
  if (!items.value.length) return emptyReason.value.code === 'NO_PERMISSION' ? 'nopermission' : 'empty'
  return 'ready'
})

function openDetail(row) {
  const { path, query } = detailPath(row.id, buildReturnTo({ ...filters }))
  router.push({ path, query })
}

async function openWizard() {
  wizard.productId = null
  wizard.shopId = null
  wizardStep.value = 0
  wizardVisible.value = true
  if (!products.value.length) {
    try { products.value = (await fetchProducts({ page: 1 })).items || [] } catch { products.value = [] }
  }
  if (!context.value) await loadContextData()
}

async function doCreate() {
  creating.value = true
  try {
    const run = await createLaunch({ productId: wizard.productId, shopId: wizard.shopId })
    ElMessage.success('上线流程已创建')
    wizardVisible.value = false
    router.push(`/app/launch/${run.id}`)
  } catch (e) {
    const envelope = errorEnvelope(e)
    // 已有同商品同店铺流程：给直达入口，不重复创建。
    if (envelope.existing_launch_id) {
      ElMessage.warning(`该商品与店铺已存在上线流程 #${envelope.existing_launch_id}`)
      router.push(`/app/launch/${envelope.existing_launch_id}`)
      wizardVisible.value = false
      return
    }
    ElMessage.error(envelope.message)
  } finally { creating.value = false }
}

onMounted(() => {
  // 从详情回跳时还原保存的筛选（return_to 往返，类型归一）。
  const restored = parseReturnTo(route.query.return_to || '')
  if (restored) Object.assign(filters, restored)
  load()
  loadContextData()
})
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.mb12 { margin-bottom: 12px; }
</style>
