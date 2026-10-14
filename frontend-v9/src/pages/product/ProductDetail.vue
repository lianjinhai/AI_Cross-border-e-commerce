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

      <!-- 渠道信息（GET /products/{id}/channels 只读；E01：读 channels 聚合，按店铺独立状态） -->
      <el-card class="mb16" shadow="never">
        <template #header><span class="card-title">渠道信息（只读）</span></template>
        <SectionState :state="channelState" :error="channelError" :empty-hint="channelEmptyHint" @retry="loadChannels">
          <EmptyState
            v-if="!channelLoading && !channelError && channelRows.length === 0"
            reason="NO_DATA" :hint="channelEmptyHint" />
          <div v-for="ch in channelRows" :key="ch.shop.id" class="channel-block">
            <div class="channel-head">
              <span class="channel-shop">{{ ch.shop.name || `店铺#${ch.shop.id}` }}</span>
              <span class="channel-market">{{ ch.shop.platform || '未知平台' }} · {{ ch.shop.market || '市场未知' }}</span>
            </div>
            <template v-if="ch.active">
              <div class="channel-row">
                <span class="channel-label">活跃上线</span>
                <el-tag size="small" :type="executionTag(ch.active.executionStatus)">
                  {{ ch.active.executionLabel }}
                </el-tag>
                <span class="channel-progress">{{ ch.active.progress }}</span>
                <span class="channel-next">下一步：{{ ch.active.nextAction }}</span>
                <el-button size="small" link type="primary"
                  @click="router.push(`/app/launch/${ch.active.id}`)">查看上线流程</el-button>
              </div>
            </template>
            <div v-else class="channel-row channel-muted">该店铺当前没有活跃上线流程</div>
            <template v-if="ch.history.length">
              <el-collapse class="channel-history">
                <el-collapse-item :title="`历史轮次（${ch.history.length}）`">
                  <div v-for="h in ch.history" :key="h.id" class="channel-row channel-muted">
                    <el-tag size="small" type="info">{{ h.executionLabel }}</el-tag>
                    <span>{{ h.progress }}</span>
                    <span class="channel-dim">{{ h.createdAt }}</span>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </template>
          </div>
        </SectionState>
      </el-card>

      <!-- 素材（assets + verify；E02：必须带目标店铺上下文，E05：真实字段映射） -->
      <el-card shadow="never">
        <template #header>
          <div class="between">
            <span class="card-title">素材与核验（按店铺隔离）</span>
            <div class="asset-tools">
              <el-select v-model="assetShopId" placeholder="选择目标店铺" size="small" style="width:240px" @change="onAssetShopChange">
                <el-option v-for="opt in shopOptions" :key="opt.id" :label="opt.label" :value="opt.id" />
              </el-select>
              <el-button v-if="canWrite()" size="small" :disabled="!assetShopId" @click="assetDialog = true">
                登记素材
              </el-button>
            </div>
          </div>
        </template>
        <template v-if="!assetShopId">
          <EmptyState reason="NO_DATA" hint="请先在上方选择目标店铺，素材按店铺的市场/平台隔离展示" />
        </template>
        <SectionState v-else :state="assetState" :error="assetError" empty-hint="该店铺还没有素材记录" @retry="loadAssets">
          <EmptyState
            v-if="!assetLoading && !assetError && assetRows.length === 0"
            reason="NO_DATA" hint="该店铺还没有素材记录" />
          <el-table v-if="assetRows.length" :data="assetRows" size="small">
            <el-table-column prop="assetKey" label="素材键" min-width="140" show-overflow-tooltip />
            <el-table-column prop="typeLabel" label="类型" width="100" />
            <el-table-column label="URI" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <a v-if="row.uri" :href="row.uri" target="_blank" rel="noopener" class="link">{{ row.uri }}</a>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column prop="version" label="版本" width="60" />
            <el-table-column label="权利状态" width="130">
              <template #default="{ row }">
                <el-tag :type="row.rightsType" size="small">{{ row.rightsLabel }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="核验状态" width="130">
              <template #default="{ row }">
                <el-tag :type="row.verificationType" size="small">{{ row.verificationLabel }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="市场/平台" width="130">
              <template #default="{ row }">{{ row.market }} / {{ row.platform }}</template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button v-if="canApprove() && row.verificationStatus !== 'VERIFIED'" size="small"
                  :loading="verifying === row.id" @click="openVerify(row)">核验</el-button>
              </template>
            </el-table-column>
          </el-table>
        </SectionState>
      </el-card>

      <!-- 登记素材（AssetIn：asset_key/expected_version/asset_type/uri/content_hash/rights_status/source + shop_id） -->
      <el-dialog v-model="assetDialog" title="登记素材" width="560px">
        <el-form label-width="110px">
          <el-form-item label="目标店铺">
            <el-select v-model="assetShopId" placeholder="选择目标店铺" style="width:100%">
              <el-option v-for="opt in shopOptions" :key="opt.id" :label="opt.label" :value="opt.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="素材键"><el-input v-model="assetForm.asset_key" placeholder="如 main_image" /></el-form-item>
          <el-form-item label="类型">
            <el-select v-model="assetForm.asset_type" style="width:100%">
              <el-option v-for="t in ASSET_TYPES" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="URI"><el-input v-model="assetForm.uri" placeholder="https://…" /></el-form-item>
          <el-form-item label="内容哈希"><el-input v-model="assetForm.content_hash" placeholder="sha256 64位十六进制" /></el-form-item>
          <el-form-item label="权利状态">
            <el-select v-model="assetForm.rights_status" style="width:100%">
              <el-option label="自有权利" value="OWNED" />
              <el-option label="供应商授权" value="SUPPLIER_AUTHORIZED" />
              <el-option label="已许可" value="LICENSED" />
              <el-option label="权利未知" value="UNKNOWN" />
            </el-select>
          </el-form-item>
          <el-form-item label="权利证据引用">
            <el-input v-model="assetForm.rights_evidence_ref"
              :placeholder="(assetForm.rights_status === 'SUPPLIER_AUTHORIZED' || assetForm.rights_status === 'LICENSED') ? '必填：https/asset/evidence 引用' : '可选'" />
          </el-form-item>
          <el-form-item label="来源"><el-input v-model="assetForm.source" placeholder="素材来源说明（必填）" /></el-form-item>
        </el-form>
        <div v-if="contentHashGap" class="asset-gap-hint">
          内容哈希需为 64 位 sha256 十六进制（后端 AssetRegistration.content_hash）。当前尚无素材上传/哈希服务，
          请填写素材文件的真实哈希，未知时不要提交。
        </div>
        <template #footer>
          <el-button @click="assetDialog = false">取消</el-button>
          <el-button type="primary" @click="doAddAsset">登记</el-button>
        </template>
      </el-dialog>

      <!-- 素材核验（ReviewIn：shop_id/expected_version/decision/evidence_ref/reason，需合规审批权） -->
      <el-dialog v-model="verifyDialog" title="素材核验" width="480px">
        <el-alert v-if="verifyError" :type="verifyError.includes('无权限') ? 'error' : 'warning'"
          :closable="false" show-icon class="mb12" :title="verifyError" />
        <el-form label-width="110px">
          <el-form-item label="决定">
            <el-select v-model="verifyForm.decision" style="width:100%">
              <el-option label="核验通过" value="VERIFIED" />
              <el-option label="驳回" value="REJECTED" />
            </el-select>
          </el-form-item>
          <el-form-item label="证据引用"><el-input v-model="verifyForm.evidence_ref" placeholder="https/asset/evidence 引用" /></el-form-item>
          <el-form-item label="原因"><el-input v-model="verifyForm.reason" type="textarea" :rows="3" placeholder="核验/驳回原因（必填）" /></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="verifyDialog = false">取消</el-button>
          <el-button type="primary" :loading="verifying" @click="doVerify">提交核验</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
/**
 * 商品详情（UX-C，路由化 /app/products/:id）：
 * 标准化信息 + 渠道信息（GET /products/{id}/channels 只读，E01 读 channels 聚合）
 * + 素材（assets + verify，E02 必须带 shop_id 上下文，E05 真实字段映射，E06 分区错误态）。
 * 详情页不再弹窗堆叠：旧 4 弹窗中「代发」归列表页标准下单向导，「采集」归列表统一入口。
 *
 * 渠道与素材各自独立加载、独立错误态（保留已加载数据 + 具体原因 + 重试，E06）；
 * 素材区未选目标店铺时禁止请求（不猜测默认店铺），登记/核验表单字段与后端
 * AssetIn/ReviewIn 逐字对齐（extra=forbid，不发送多余字段）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import EmptyState from '../../components/EmptyState.vue'
import ErrorState from '../../components/ErrorState.vue'
import SectionState from '../../components/SectionState.vue'
import { canApprove, canWrite } from '../../permissions/permissions'
import {
  addAsset, fetchAssets, fetchChannels, fetchProduct, isAssetContentHash, standardize, verifyAsset,
} from '../../api/domains/products'
import { fetchShops } from '../../api/domains/shops'
import {
  assetPageItems, assetRowView, buildShopOptions, launchItemView, normalizeChannels, sectionErrorText, shopContext, verifyErrorKind,
} from '../../shared/productDetailView'

/** 登记表单类型选项（asset_schema.py asset_type Literal 域）。 */
const ASSET_TYPES = [
  { label: '原图', value: 'ORIGINAL_IMAGE' },
  { label: '主图', value: 'MAIN_IMAGE' },
  { label: '详情图', value: 'DETAIL_IMAGE' },
  { label: '尺码图', value: 'SIZE_IMAGE' },
  { label: '实物照', value: 'PHYSICAL_PHOTO' },
  { label: '视频', value: 'VIDEO' },
  { label: '权利证据', value: 'RIGHTS_EVIDENCE' },
  { label: '标签', value: 'LABEL' },
  { label: '条码', value: 'BARCODE' },
  { label: '合规附件', value: 'COMPLIANCE_ATTACHMENT' },
]

const route = useRoute()
const router = useRouter()

const product = ref({})
const error = ref('')

// ── 渠道分区（E01/E06）：独立 loading / error / 数据，失败不当空 ──
const channelRows = ref([])
const channelLoading = ref(false)
const channelError = ref('')
const channelState = computed(() => channelLoading.value ? 'loading' : channelError.value ? 'error' : 'ready')
const channelEmptyHint = '该商品尚未在可访问的店铺中上线'

// ── 素材分区（E02/E05/E06）：按店铺隔离；未选店铺不请求 ──
const assetShopId = ref(null)
const shopList = ref(null)
const assetRows = ref([])
const assetLoading = ref(false)
const assetError = ref('')
const assetState = computed(() => assetLoading.value ? 'loading' : assetError.value ? 'error' : 'ready')

/** 店铺选择器选项：渠道行的店铺优先，shops API 列表兜底（缺省时仍可为空，不猜测默认店铺）。 */
const shopOptions = computed(() => buildShopOptions(
  channelRows.value.map((c) => c.shop),
  (shopList.value || {}).items || [],
))

const stdLoading = ref(false)
const verifying = ref(null)
const assetDialog = ref(false)
const verifyDialog = ref(false)
const assetForm = reactive({
  asset_key: '', asset_type: 'MAIN_IMAGE', uri: '', content_hash: '',
  rights_status: 'OWNED', rights_evidence_ref: '', source: '',
})
const verifyForm = reactive({ decision: 'VERIFIED', evidence_ref: '', reason: '' })
const verifyingRow = ref(null)
const verifyError = ref('')

const contentHashGap = computed(() => !isAssetContentHash(assetForm.content_hash))

async function load() {
  error.value = ''
  try {
    product.value = await fetchProduct(route.params.id)
  } catch (e) {
    error.value = sectionErrorText(e, '商品加载失败')
    return
  }
  // 店铺列表（店铺选择器兜底来源）与渠道/素材各自独立加载，互不阻断
  loadShopList()
  await loadChannels()
  // 素材区不做自动猜测：目标店铺必须由用户在店铺选择器中显式指定后才发起请求
}

async function loadShopList() {
  try { shopList.value = await fetchShops() }
  catch { shopList.value = null } // 选择器缺省来源失败时仍可用渠道行里的店铺
}

async function loadChannels() {
  channelLoading.value = true
  channelError.value = ''
  try {
    const view = normalizeChannels(await fetchChannels(route.params.id))
    channelRows.value = view.channels.map((c) => ({
      shop: c.shop,
      active: c.active ? launchItemView(c.active) : null,
      history: c.history.map(launchItemView),
    }))
  } catch (e) {
    // E06：保留已加载数据，显示具体原因 + 重试；渠道失败不影响素材区
    channelError.value = sectionErrorText(e, '渠道加载失败')
  } finally {
    channelLoading.value = false
  }
}

async function loadAssets() {
  if (!assetShopId.value) return
  assetLoading.value = true
  assetError.value = ''
  try {
    const data = await fetchAssets(route.params.id, { shopId: assetShopId.value })
    assetRows.value = assetPageItems(data).map((a) => decorateAssetRow(assetRowView(a)))
    assetReadyFlag.value = true
  } catch (e) {
    // E06：素材失败不当空，保留旧数据并独立报错
    assetError.value = sectionErrorText(e, '素材加载失败')
  } finally {
    assetLoading.value = false
  }
}

/** 展示态补充（判定结果在 shared/productDetailView 单点计算，模板只消费稳定字段）。 */
function decorateAssetRow(view) {
  view.rightsType = view.publishable ? 'success' : (view.verificationStatus === 'VERIFIED' ? 'warning' : 'info')
  view.verificationType = view.verificationStatus === 'VERIFIED' ? 'success' : 'info'
  return view
}

function executionTag(status) {
  const map = { COMPLETED: 'success', RUNNING: 'primary', BLOCKED: 'warning', FAILED: 'danger', CANCELLED: 'info' }
  return map[status] || 'info'
}

async function doStandardize() {
  stdLoading.value = true
  try {
    const data = await standardize(route.params.id)
    ElMessage.success(`已标准化：类目=${data.category}${data.is_duplicate ? `（疑似重复商品 #${data.duplicate_of}）` : ''}`)
    await load()
  } finally { stdLoading.value = false }
}

/** 登记素材（AssetIn 字段逐字对齐；expected_version 新素材为 0；market/platform 由目标店铺上下文推导）。 */
async function doAddAsset() {
  if (!assetShopId.value) return ElMessage.warning('请先选择目标店铺')
  if (!assetForm.asset_key.trim()) return ElMessage.warning('请填写素材键')
  if (!assetForm.uri.trim()) return ElMessage.warning('请填写素材 URI')
  if (!assetForm.source.trim()) return ElMessage.warning('请填写素材来源')
  if (contentHashGap.value) {
    return ElMessage.warning('内容哈希必须是 64 位 sha256 十六进制；暂无上传/哈希服务，未知哈希不要提交')
  }
  const needEvidence = ['SUPPLIER_AUTHORIZED', 'LICENSED'].includes(assetForm.rights_status)
  if (needEvidence && !assetForm.rights_evidence_ref.trim()) {
    return ElMessage.warning('授权/许可素材必须提供权利证据引用')
  }
  // market/platform 必须与目标店铺一致（后端 ASSET_USAGE_MISMATCH 校验）；由店铺上下文推导，不手填、不猜测
  const ctx = shopContext(
    channelRows.value.map((c) => c.shop),
    (shopList.value || {}).items || [],
    assetShopId.value,
  )
  if (!ctx || !ctx.market || !ctx.platform) {
    return ElMessage.warning('目标店铺缺少市场/平台配置，无法登记素材（后端要求素材适用范围与店铺一致）')
  }
  await addAsset(route.params.id, {
    shop_id: assetShopId.value,
    asset_key: assetForm.asset_key.trim(),
    expected_version: 0,
    asset_type: assetForm.asset_type,
    uri: assetForm.uri.trim(),
    content_hash: assetForm.content_hash.trim(),
    rights_status: assetForm.rights_status,
    rights_evidence_ref: assetForm.rights_evidence_ref.trim(),
    source: assetForm.source.trim(),
    market: ctx.market,
    platform: ctx.platform,
  })
  ElMessage.success('素材已登记（版本追加，不代表已核验）')
  assetDialog.value = false
  assetForm.asset_key = ''
  assetForm.uri = ''
  assetForm.content_hash = ''
  assetForm.rights_evidence_ref = ''
  assetForm.source = ''
  await loadAssets()
}

function openVerify(row) {
  verifyingRow.value = row
  verifyForm.decision = 'VERIFIED'
  verifyForm.evidence_ref = ''
  verifyForm.reason = ''
  verifyError.value = ''
  verifyDialog.value = true
}

async function doVerify() {
  const row = verifyingRow.value
  if (!row || !row.id) return
  if (!verifyForm.evidence_ref.trim()) return ElMessage.warning('请填写证据引用')
  if (!verifyForm.reason.trim()) return ElMessage.warning('请填写原因')
  verifying.value = row.id
  verifyError.value = ''
  try {
    await verifyAsset(route.params.id, row.id, {
      shop_id: assetShopId.value,
      expected_version: row.version,
      decision: verifyForm.decision,
      evidence_ref: verifyForm.evidence_ref.trim(),
      reason: verifyForm.reason.trim(),
    })
    ElMessage.success(`素材 #${row.id} 核验已提交（决策追加为新版本）`)
    verifyDialog.value = false
    await loadAssets()
  } catch (e) {
    // E04：区分 无权限(403)/自审限制(403)/版本冲突(409)；409/422 保留已填内容并提示刷新，不静默吞掉
    const kind = verifyErrorKind(e, '核验提交失败')
    verifyError.value = kind.message
    if (kind.kind === 'no_permission') {
      ElMessage.error(kind.message)
      verifyDialog.value = false // 无权限不保留空表单，如实收口
    } else {
      ElMessage.warning(kind.message) // 保留输入，等用户刷新后重新确认
    }
  } finally { verifying.value = null }
}

/** 切换目标店铺：重置该分区数据后按新上下文加载（E02 数据隔离）。 */
function onAssetShopChange() {
  assetRows.value = []
  assetError.value = ''
  loadAssets()
}

onMounted(load)
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.mb16 { margin-bottom: 16px; }
.card-title { font-weight: 600; }
.between { display: flex; justify-content: space-between; align-items: center; }
.images { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.thumb { width: 72px; height: 72px; border-radius: 6px; }
.link { color: var(--color-primary); }
</style>
