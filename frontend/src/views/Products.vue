<template>
  <div class="page">
    <el-card class="mb16">
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <el-input v-model="q.keyword" placeholder="标题/SKU 搜索" style="width:220px" clearable @change="load" />
        <el-select v-model="q.category" placeholder="类目" style="width:140px" clearable @change="load">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button v-if="can('product:write')" type="primary" @click="dialog = true">新增商品</el-button>
        <el-button v-if="can('product:write')" type="success" @click="collectDialog = true">批量采集（演示源）</el-button>
        <el-button v-if="can('product:write')" type="warning" @click="urlDialog = true">URL 精准采集（真实抓取）</el-button>
        <el-button plain @click="exportCsv">导出 CSV</el-button>
      </div>
    </el-card>

    <el-card>
      <el-table :data="items" v-loading="loading" size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="图" width="70">
          <template #default="{ row }">
            <el-image v-if="(row.images || []).length" :src="row.images[0]" fit="cover"
              style="width:44px;height:44px;border-radius:6px"
              :preview-src-list="row.images" preview-teleported />
          </template>
        </el-table-column>
        <el-table-column prop="sku" label="SKU" width="110" />
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="category" label="类目" width="110" />
        <el-table-column label="机会分" width="140">
          <template #default="{ row }">
            <el-progress v-if="row.score_total != null" :percentage="row.score_total"
              :color="row.score_total > 75 ? '#67C23A' : '#409EFF'" />
            <span v-else style="color:#c0c4cc">未评分</span>
          </template>
        </el-table-column>
        <el-table-column prop="source_platform" label="来源" width="90" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="showDetail(row)">详情</el-button>
            <el-button v-if="can('product:write')" size="small" type="primary" :loading="stdLoading === row.id" @click="standardize(row)">标准化</el-button>
            <el-button v-if="is1688(row) && can('purchase:write')" size="small" type="warning" @click="openDropship(row)">一件代发</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" v-model:current-page="page" @current-change="load" />
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawer" :title="`商品详情 #${detail.id || ''}`" size="620px">
      <template v-if="detail.id">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="标题" :span="2">{{ detail.title }}</el-descriptions-item>
          <el-descriptions-item label="SKU">{{ detail.sku }}</el-descriptions-item>
          <el-descriptions-item label="类目">{{ detail.category }}</el-descriptions-item>
          <el-descriptions-item label="来源平台">{{ detail.source_platform }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
        </el-descriptions>
        <h4>属性</h4>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item v-for="(v, k) in detail.attrs" :key="k" :label="k">{{ v }}</el-descriptions-item>
        </el-descriptions>
        <el-tabs style="margin-top:12px">
          <el-tab-pane label="经营表现（数据飞轮）">
            <el-alert type="info" :closable="false" style="margin-bottom:10px"
              title="来自真实订单的经营结果会反哺选品评分（演示数据不计入）" />
            <el-descriptions v-if="performance.product_id" :column="2" border size="small">
              <el-descriptions-item label="表现分">
                <b :style="{ color: performance.has_data ? '#67C23A' : '#909399' }">
                  {{ performance.performance_score }}
                </b>
                <span v-if="!performance.has_data" style="color:#909399">（暂无真实销售，按中性分评估）</span>
              </el-descriptions-item>
              <el-descriptions-item label="统计窗口">{{ performance.window_days }} 天</el-descriptions-item>
              <el-descriptions-item label="售出件数">{{ performance.units_sold }}</el-descriptions-item>
              <el-descriptions-item label="销售额">${{ (performance.revenue || 0).toFixed(2) }}</el-descriptions-item>
              <el-descriptions-item label="毛利率">{{ ((performance.margin || 0) * 100).toFixed(1) }}%</el-descriptions-item>
              <el-descriptions-item label="退款率">{{ ((performance.refund_rate || 0) * 100).toFixed(1) }}%</el-descriptions-item>
              <el-descriptions-item label="售罄率">{{ ((performance.sell_through || 0) * 100).toFixed(1) }}%</el-descriptions-item>
              <el-descriptions-item label="计算时间">{{ performance.computed_at }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
          <el-tab-pane label="选品评分">
            <el-table :data="detail.scores || []" size="small">
              <el-table-column prop="total" label="机会分" width="80" />
              <el-table-column prop="demand" label="需求" width="70" />
              <el-table-column prop="competition" label="竞争" width="70" />
              <el-table-column prop="profit" label="利润" width="70" />
              <el-table-column prop="risk" label="风险" width="70" />
              <el-table-column prop="reasons" label="依据" show-overflow-tooltip>
                <template #default="{ row }">{{ (row.reasons || []).join('；') }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane :label="`货源报价 (${(detail.offers || []).length})`">
            <el-table :data="detail.offers || []" size="small">
              <el-table-column prop="supplier_name" label="供应商" />
              <el-table-column prop="price" label="采购价(¥)" width="100" />
              <el-table-column prop="ship_days" label="发货天数" width="90" />
              <el-table-column prop="moq" label="起订量" width="80" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane :label="`Listing (${(detail.listings || []).length})`">
            <el-table :data="detail.listings || []" size="small">
              <el-table-column prop="platform" label="平台" width="90" />
              <el-table-column prop="title" label="标题" show-overflow-tooltip />
              <el-table-column prop="status" label="状态" width="90" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="定价">
            <el-descriptions v-if="detail.pricing" :column="2" border size="small">
              <el-descriptions-item label="当前价">${{ detail.pricing.price }}</el-descriptions-item>
              <el-descriptions-item label="建议价">${{ detail.pricing.suggested_price }}</el-descriptions-item>
              <el-descriptions-item label="单件利润">${{ detail.pricing.profit }}</el-descriptions-item>
              <el-descriptions-item label="利润率">{{ ((detail.pricing.margin || 0) * 100).toFixed(1) }}%</el-descriptions-item>
            </el-descriptions>
            <el-empty v-else description="尚未生成定价" :image-size="60" />
          </el-tab-pane>
          <el-tab-pane label="合规">
            <template v-if="detail.compliance">
              <el-tag :type="detail.compliance.risk_level === 'high' ? 'danger' : detail.compliance.risk_level === 'mid' ? 'warning' : 'success'">
                {{ detail.compliance.risk_level }}（{{ detail.compliance.score }} 分）
              </el-tag>
              <div v-for="(iss, i) in detail.compliance.issues" :key="i" style="margin-top:8px;font-size:13px">
                ⚠️ {{ iss.detail }}
              </div>
            </template>
            <el-empty v-else description="尚未检测" :image-size="60" />
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>

    <!-- 新增 -->
    <el-dialog v-model="dialog" title="新增商品" width="520px">
      <el-form label-width="90px">
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="类目"><el-input v-model="form.category" /></el-form-item>
        <el-form-item label="采购价¥"><el-input-number v-model="form.supplier_price" :min="1" /></el-form-item>
        <el-form-item label="售价$"><el-input-number v-model="form.sale_price" :min="1" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="createProduct">保存</el-button>
      </template>
    </el-dialog>

    <!-- 采集 -->
    <el-dialog v-model="collectDialog" title="模拟平台采集" width="480px">
      <el-form label-width="90px">
        <el-form-item label="来源平台">
          <el-select v-model="collect.source_platform">
            <el-option label="1688（跨境货源）" value="1688" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词"><el-input v-model="collect.keyword" placeholder="留空=全部" /></el-form-item>
        <el-form-item label="数量"><el-input-number v-model="collect.count" :min="1" :max="20" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="collectDialog = false">取消</el-button>
        <el-button v-if="can('purchase:write')" type="primary" :loading="collecting" @click="doCollect">开始采集</el-button>
      </template>
    </el-dialog>

    <!-- 一件代发下单（1688 货源店铺） -->
    <el-dialog v-model="dsDialog" title="1688 一件代发下单" width="520px">
      <el-form label-width="100px">
        <el-form-item label="货源店铺">
          <el-select v-model="ds.shop_id" placeholder="选择已授权的 1688 货源店铺" style="width:100%">
            <el-option v-for="s in dsShops" :key="s.id" :value="s.id"
              :label="`${s.shop_name}${s.is_demo ? '（演示）' : s.status === 'authorized' ? '' : '（未授权，不可下单）'}`"
              :disabled="!s.is_demo && s.status !== 'authorized'" />
          </el-select>
        </el-form-item>
        <el-form-item label="代发数量"><el-input-number v-model="ds.qty" :min="1" :max="999" /></el-form-item>
        <el-form-item label="收件人"><el-input v-model="ds.consignee" placeholder="真实下单时传给平台" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="ds.phone" /></el-form-item>
        <el-form-item label="收货地址"><el-input v-model="ds.address" /></el-form-item>
      </el-form>
      <el-alert type="info" :closable="false"
        title="向 1688 货源店铺按 offer 原始链接代发下单；销售店铺不能用作代发源（两类店铺不可混用）。" />
      <template v-if="dsResult.po_no">
        <el-divider>下单结果</el-divider>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="采购单">{{ dsResult.purchase.po_no }}</el-descriptions-item>
          <el-descriptions-item label="平台单号">{{ dsResult.platform_trade_no }}</el-descriptions-item>
          <el-descriptions-item label="通道">{{ dsResult.mode === 'demo' ? '演示' : '真实 API' }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="dsDialog = false">关闭</el-button>
        <el-button type="primary" :loading="dsLoading" @click="doDropship">提交代发订单</el-button>
      </template>
    </el-dialog>
    <!-- URL 真实采集 -->
    <el-dialog v-model="urlDialog" title="真实抓取采集" width="560px">
      <el-tabs v-model="collectTab">
        <el-tab-pane label="输入商品页链接" name="url">
          <el-form label-width="90px">
            <el-form-item label="商品页URL">
              <el-input v-model="collectUrl.url" placeholder="https://detail.1688.com/offer/xxx.html 或任意商品页" />
            </el-form-item>
          </el-form>
          <el-alert type="info" :closable="false"
            title="管线：静态抓取 → 无头浏览器渲染（过反爬/等渲染）。遇到登录墙或验证码时请改用「粘贴网页源码」。" />
        </el-tab-pane>
        <el-tab-pane label="粘贴网页源码（兜底）" name="html">
          <el-form label-width="90px">
            <el-form-item label="页面URL">
              <el-input v-model="collectHtml.url" placeholder="可选，用于识别来源域名" />
            </el-form-item>
            <el-form-item label="网页源码">
              <el-input v-model="collectHtml.html" type="textarea" :rows="9"
                placeholder="浏览器打开商品页 → 右键「查看网页源代码」→ 全选复制 → 粘贴到这里" />
            </el-form-item>
          </el-form>
          <el-alert type="info" :closable="false"
            title="适用于 1688/淘宝等强反爬站点：你本地浏览器已通过验证，复制源码即可解析入库。" />
        </el-tab-pane>
      </el-tabs>
      <template v-if="urlResult.id">
        <el-divider>抓取结果（引擎：{{ urlEngine }}）</el-divider>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="标题">{{ urlResult.title }}</el-descriptions-item>
          <el-descriptions-item label="解析价格">${{ urlResult.attrs?.sale_price }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ urlResult.source_platform }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="urlDialog = false">关闭</el-button>
        <el-button v-if="collectTab === 'url'" type="primary" :loading="urlLoading" @click="doCollectUrl">开始抓取</el-button>
        <el-button v-else type="primary" :loading="urlLoading" @click="doCollectHtml">解析并入库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
import { can } from '../permissions'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const q = reactive({ keyword: '', category: '' })
const drawer = ref(false)
const detail = ref({})
const dialog = ref(false)
const collectDialog = ref(false)
const collecting = ref(false)
const stdLoading = ref(null)
const performance = ref({})

// ---- 一件代发（1688 货源店铺） ----
const dsDialog = ref(false)
const dsLoading = ref(false)
const dsShops = ref([])
const dsResult = ref({})
const ds = reactive({ shop_id: null, product_id: null, qty: 1, consignee: '', phone: '', address: '' })

const is1688 = (row) => (row.source_platform || '').includes('1688') || (row.source_url || '').includes('1688')

async function openDropship(row) {
  ds.product_id = row.id
  ds.qty = 1
  ds.consignee = ''
  ds.phone = ''
  ds.address = ''
  dsResult.value = {}
  dsDialog.value = true
  const { data } = await api.get('/shops')
  dsShops.value = (data.items || []).filter((s) => s.role === 'source' && s.platform === '1688')
  if (!dsShops.value.length) ElMessage.warning('暂无 1688 货源店铺，请先到「店铺授权」添加')
}

async function doDropship() {
  if (!ds.shop_id) return ElMessage.warning('请选择货源店铺')
  dsLoading.value = true
  try {
    const { data } = await api.post('/purchases/dropship', ds)
    dsResult.value = { ...data, po_no: data.purchase.po_no }
    ElMessage.success(`代发下单成功（${data.mode === 'demo' ? '演示' : '真实'}）平台单号 ${data.platform_trade_no}`)
  } finally { dsLoading.value = false }
}
const categories = ['家居', '3C配件', '宠物用品', '户外运动', '美妆工具', '母婴用品', '厨房用品', '服饰配件', '汽车用品']
const form = reactive({ title: '', category: '', supplier_price: 10, sale_price: 20 })
const collect = reactive({ source_platform: '1688', keyword: '', count: 5 })
const urlDialog = ref(false)
const urlLoading = ref(false)
const urlResult = ref({})
const urlEngine = ref('')
const collectUrl = reactive({ url: '' })
const collectHtml = reactive({ url: '', html: '' })
const collectTab = ref('url')

async function doCollectUrl() {
  if (!collectUrl.url.trim()) return ElMessage.warning('请输入商品页 URL')
  urlLoading.value = true
  try {
    const { data } = await api.post('/products/collect_url', collectUrl)
    urlResult.value = data.item
    urlEngine.value = data.engine
    ElMessage.success(`抓取成功（${data.engine}）：${data.parsed.title.slice(0, 30)}…`)
    load()
  } finally { urlLoading.value = false }
}

async function doCollectHtml() {
  if (collectHtml.html.trim().length < 500) return ElMessage.warning('请粘贴完整的网页源码（不少于 500 字符）')
  urlLoading.value = true
  try {
    const { data } = await api.post('/products/collect_html', collectHtml)
    urlResult.value = data.item
    urlEngine.value = data.engine
    ElMessage.success(`解析成功：${data.parsed.title.slice(0, 30)}…`)
    load()
  } finally { urlLoading.value = false }
}

async function exportCsv() {
  const res = await api.get('/products/export', { responseType: 'blob' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(res.data)
  a.download = 'products.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/products', { params: { ...q, page_num: page.value, page_size: pageSize } })
    items.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

async function showDetail(row) {
  const { data } = await api.get(`/products/${row.id}`)
  detail.value = data
  drawer.value = true
  // M1：并行加载经营表现（数据飞轮），失败不影响详情展示
  performance.value = {}
  try {
    const r = await api.get(`/discovery/performance/${row.id}`)
    performance.value = r.data
  } catch { /* 全局拦截器已提示 */ }
}

async function standardize(row) {
  stdLoading.value = row.id
  try {
    const { data } = await api.post(`/products/${row.id}/standardize`)
    ElMessage.success(`已标准化：类目=${data.category}${data.is_duplicate ? `（疑似重复商品 #${data.duplicate_of}）` : ''}`)
    load()
  } finally { stdLoading.value = null }
}

async function createProduct() {
  await api.post('/products', {
    title: form.title, category: form.category,
    attrs: { supplier_price: form.supplier_price, sale_price: form.sale_price },
  })
  ElMessage.success('已创建')
  dialog.value = false
  load()
}

async function doCollect() {
  collecting.value = true
  try {
    const { data } = await api.post('/products/collect', collect)
    ElMessage.success(`采集完成，新增 ${data.collected} 个商品`)
    collectDialog.value = false
    load()
  } finally { collecting.value = false }
}

onMounted(load)
</script>
