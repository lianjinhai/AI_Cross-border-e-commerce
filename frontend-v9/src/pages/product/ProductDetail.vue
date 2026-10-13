<template>
  <div class="page">
    <PageHeader :title="product.title || '商品详情'" subtitle="标准化信息 · 渠道只读 · 素材核验">
      <template #actions>
        <el-button size="small" @click="router.back()">返回</el-button>
        <el-button v-if="canWrite()" type="primary" size="small" :loading="stdLoading" @click="doStandardize">
          重新标准化
        </el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="error" class="mb16" :message="error" @retry="load" />

    <template v-else>
      <!-- 基本信息 -->
      <el-card class="mb16" shadow="never">
        <template #header><span class="card-title">基本信息</span></template>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="ID">#{{ product.id }}</el-descriptions-item>
          <el-descriptions-item label="SKU">{{ product.sku || '—' }}</el-descriptions-item>
          <el-descriptions-item label="类目">{{ product.category || '未标准化' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <StatusBadge :status="product.status || 'raw'" />
          </el-descriptions-item>
          <el-descriptions-item label="来源平台">{{ product.source_platform || '—' }}</el-descriptions-item>
          <el-descriptions-item label="来源链接">
            <a v-if="product.source_url" :href="product.source_url" target="_blank" rel="noopener" class="link">查看源页</a>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item label="采购价 ¥">{{ product.attrs?.supplier_price ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="售价 $">{{ product.attrs?.sale_price ?? '—' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="(product.images || []).length" class="images">
          <el-image v-for="(img, i) in product.images" :key="i" :src="img" fit="cover"
            :preview-src-list="product.images" preview-teleported class="thumb" />
        </div>
      </el-card>

      <!-- 渠道信息（GET /products/{id}/channels 只读） -->
      <el-card class="mb16" shadow="never">
        <template #header><span class="card-title">渠道信息（只读）</span></template>
        <el-table :data="channels" size="small" v-loading="loadingChannels">
          <el-table-column prop="channel" label="渠道" width="120" />
          <el-table-column prop="external_id" label="外部引用" min-width="160" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column prop="synced_at" label="同步时间" width="170" />
          <template #empty><EmptyState reason="NO_DATA" hint="该商品尚未分发到任何渠道" /></template>
        </el-table>
      </el-card>

      <!-- 素材（assets + verify） -->
      <el-card shadow="never">
        <template #header>
          <div class="between">
            <span class="card-title">素材与核验</span>
            <el-button v-if="canWrite()" size="small" @click="assetDialog = true">新增素材</el-button>
          </div>
        </template>
        <el-table :data="assets" size="small" v-loading="loadingAssets">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="type" label="类型" width="100" />
          <el-table-column label="URL" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <a v-if="row.url" :href="row.url" target="_blank" rel="noopener" class="link">{{ row.url }}</a>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column prop="verified" label="核验" width="90">
            <template #default="{ row }">
              <el-tag :type="row.verified ? 'success' : 'info'" size="small">{{ row.verified ? '已核验' : '未核验' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <el-button v-if="canWrite() && !row.verified" size="small" :loading="verifying === row.id"
                @click="doVerify(row)">核验</el-button>
            </template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="还没有素材记录" /></template>
        </el-table>
      </el-card>

      <!-- 新增素材 -->
      <el-dialog v-model="assetDialog" title="新增素材" width="480px">
        <el-form label-width="90px">
          <el-form-item label="类型">
            <el-select v-model="assetForm.type" style="width:100%">
              <el-option label="图片" value="image" /><el-option label="视频" value="video" />
            </el-select>
          </el-form-item>
          <el-form-item label="URL"><el-input v-model="assetForm.url" placeholder="https://…" /></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="assetDialog = false">取消</el-button>
          <el-button type="primary" @click="doAddAsset">保存</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
/**
 * 商品详情（UX-C，路由化 /app/products/:id）：
 * 标准化信息 + 渠道信息（GET /products/{id}/channels 只读）+ 素材（assets + verify）。
 * 详情页不再弹窗堆叠：旧 4 弹窗中「代发」归列表页标准下单向导，「采集」归列表统一入口。
 */
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import EmptyState from '../../components/EmptyState.vue'
import ErrorState from '../../components/ErrorState.vue'
import { canWrite } from '../../permissions/permissions'
import { addAsset, fetchAssets, fetchChannels, fetchProduct, standardize, verifyAsset } from '../../api/domains/products'

const route = useRoute()
const router = useRouter()

const product = ref({})
const channels = ref([])
const assets = ref([])
const error = ref('')
const loadingChannels = ref(false)
const loadingAssets = ref(false)
const stdLoading = ref(false)
const verifying = ref(null)
const assetDialog = ref(false)
const assetForm = reactive({ type: 'image', url: '' })

async function load() {
  error.value = ''
  try {
    product.value = await fetchProduct(route.params.id)
  } catch (e) {
    error.value = e?.response?.data?.detail?.message || e?.message || '商品加载失败'
    return
  }
  loadingChannels.value = true
  try { channels.value = (await fetchChannels(route.params.id)).items || [] }
  catch { channels.value = [] } // 渠道只读信息缺失不阻断详情
  finally { loadingChannels.value = false }
  await loadAssets()
}

async function loadAssets() {
  loadingAssets.value = true
  try { assets.value = (await fetchAssets(route.params.id)).items || [] }
  finally { loadingAssets.value = false }
}

async function doStandardize() {
  stdLoading.value = true
  try {
    const data = await standardize(route.params.id)
    ElMessage.success(`已标准化：类目=${data.category}${data.is_duplicate ? `（疑似重复商品 #${data.duplicate_of}）` : ''}`)
    await load()
  } finally { stdLoading.value = false }
}

async function doVerify(row) {
  verifying.value = row.id
  try {
    await verifyAsset(route.params.id, row.id)
    ElMessage.success('素材核验通过')
    await loadAssets()
  } finally { verifying.value = null }
}

async function doAddAsset() {
  if (!assetForm.url.trim()) return ElMessage.warning('请填写素材 URL')
  await addAsset(route.params.id, { type: assetForm.type, url: assetForm.url.trim() })
  ElMessage.success('素材已添加')
  assetDialog.value = false
  assetForm.url = ''
  await loadAssets()
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.card-title { font-weight: 600; }
.between { display: flex; justify-content: space-between; align-items: center; }
.images { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.thumb { width: 72px; height: 72px; border-radius: 6px; }
.link { color: var(--color-primary); }
</style>
