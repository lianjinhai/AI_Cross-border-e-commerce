<template>
  <div class="page">
    <PageHeader title="商品池" subtitle="采集 · 标准化 · 代发下单">
      <template #actions>
        <el-button v-if="canWrite" type="primary" size="small" @click="dialog = true">新增商品</el-button>
        <el-button v-if="canWrite" size="small" @click="openCollect">采集商品</el-button>
        <el-button size="small" @click="exportProductsCsv">导出 CSV</el-button>
      </template>
    </PageHeader>

    <el-card class="mb16">
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <el-input v-model="q.keyword" placeholder="标题/SKU 搜索" style="width:220px" clearable @change="reload" />
        <el-select v-model="q.category" placeholder="类目" style="width:140px" clearable @change="reload">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
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
              :color="row.score_total > 75 ? 'var(--color-success)' : 'var(--color-primary)'" />
            <span v-else style="color:var(--color-text-disabled)">未评分</span>
          </template>
        </el-table-column>
        <el-table-column prop="source_platform" label="来源" width="90" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row)">详情</el-button>
            <el-button v-if="canWrite" size="small" type="primary" :loading="stdLoading === row.id" @click="standardize(row)">标准化</el-button>
            <el-button v-if="is1688(row) && can('purchase:write')" size="small" type="warning" @click="openDropship(row)">一件代发</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" v-model:current-page="page" @current-change="load" />
    </el-card>

    <!-- 新增商品 -->
    <el-dialog v-model="dialog" title="新增商品" width="520px">
      <el-form label-width="90px">
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="类目"><el-input v-model="form.category" /></el-form-item>
        <el-form-item label="采购价¥"><el-input-number v-model="form.supplier_price" :min="1" /></el-form-item>
        <el-form-item label="售价$"><el-input-number v-model="form.sale_price" :min="1" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="submitCreateProduct">保存</el-button>
      </template>
    </el-dialog>

    <!-- 采集统一单入口：演示开关区隔演示采集与真实抓取 -->
    <el-dialog v-model="collectDialog" title="采集商品（统一入口）" width="600px">
      <el-alert :type="demoMode ? 'warning' : 'info'" :closable="false" style="margin-bottom:12px"
        :title="demoMode
          ? '演示模式：数据来自内置演示源（1688 演示词池），来源会标记为演示，不与真实数据混算'
          : '真实抓取模式：管线为 静态抓取 → 无头浏览器渲染（过反爬/等渲染）；遇到登录墙或验证码请改用「粘贴网页源码」'" />
      <div style="margin-bottom:12px">
        <el-switch v-model="demoMode" active-text="演示采集" inactive-text="真实抓取" />
      </div>
      <template v-if="demoMode">
        <el-form label-width="90px">
          <el-form-item label="来源平台">
            <el-select v-model="collect.source_platform">
              <el-option label="1688（跨境货源演示词池）" value="1688" />
            </el-select>
          </el-form-item>
          <el-form-item label="关键词"><el-input v-model="collect.keyword" placeholder="留空=全部" /></el-form-item>
          <el-form-item label="数量"><el-input-number v-model="collect.count" :min="1" :max="20" /></el-form-item>
        </el-form>
      </template>
      <el-tabs v-else v-model="realTab">
        <el-tab-pane label="输入商品页链接" name="url">
          <el-form label-width="90px">
            <el-form-item label="商品页URL">
              <el-input v-model="collectUrl.url" placeholder="https://detail.1688.com/offer/xxx.html 或任意商品页" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="粘贴网页源码（兜底）" name="html">
          <el-form label-width="90px">
            <el-form-item label="页面URL">
              <el-input v-model="collectHtml.url" placeholder="可选，用于识别来源域名" />
            </el-form-item>
            <el-form-item label="网页源码">
              <el-input v-model="collectHtml.html" type="textarea" :rows="8"
                placeholder="浏览器打开商品页 → 右键「查看网页源代码」→ 全选复制 → 粘贴到这里" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
      <template v-if="collectResult.id">
        <el-divider>采集结果（引擎：{{ collectEngine }}）</el-divider>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="标题">{{ collectResult.title }}</el-descriptions-item>
          <el-descriptions-item label="解析价格">${{ collectResult.attrs?.sale_price }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ collectResult.source_platform }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="collectDialog = false">关闭</el-button>
        <el-button type="primary" :loading="collecting" @click="doCollect">开始采集</el-button>
      </template>
    </el-dialog>

    <!-- 一件代发下单向导（1688 货源店铺） -->
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
  </div>
</template>

<script setup>
/**
 * 商品池（UX-C）：列表 + 详情路由化（/app/products/:id）。
 * 采集统一单入口：演示采集由显式开关隔离，与真实抓取区隔（J1 采集区隔演示）；
 * 一件代发走标准下单向导（选择已授权 1688 货源店铺）。
 */
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import { can, canWrite } from '../../permissions/permissions'
import {
  collectDemo, collectFromHtml, createProduct, exportCsv, fetchProducts,
  scrapeByUrl, standardize as apiStandardize, createDropshipOrder,
} from '../../api/domains/products'
import { fetchShops } from '../../api/domains/shops'

const router = useRouter()

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const q = reactive({ keyword: '', category: '' })
const dialog = ref(false)
const stdLoading = ref(null)

// 采集统一入口
const collectDialog = ref(false)
const demoMode = ref(false)
const collecting = ref(false)
const collect = reactive({ source_platform: '1688', keyword: '', count: 5 })
const collectUrl = reactive({ url: '' })
const collectHtml = reactive({ url: '', html: '' })
const realTab = ref('url')
const collectResult = ref({})
const collectEngine = ref('')

// 一件代发
const dsDialog = ref(false)
const dsLoading = ref(false)
const dsShops = ref([])
const dsResult = ref({})
const ds = reactive({ shop_id: null, product_id: null, qty: 1, consignee: '', phone: '', address: '' })

const categories = ['家居', '3C配件', '宠物用品', '户外运动', '美妆工具', '母婴用品', '厨房用品', '服饰配件', '汽车用品']
const form = reactive({ title: '', category: '', supplier_price: 10, sale_price: 20 })

const is1688 = (row) => (row.source_platform || '').includes('1688') || (row.source_url || '').includes('1688')

async function load() {
  loading.value = true
  try {
    const data = await fetchProducts({ page: page.value, keyword: q.keyword, source: q.category })
    items.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

function reload() {
  page.value = 1
  load()
}

function openDetail(row) {
  router.push(`/app/products/${row.id}`)
}

function openCollect() {
  demoMode.value = false
  collectResult.value = {}
  collectDialog.value = true
}

async function doCollect() {
  collecting.value = true
  try {
    if (demoMode.value) {
      const data = await collectDemo({
        sourcePlatform: collect.source_platform, keyword: collect.keyword, count: collect.count,
      })
      ElMessage.success(`采集完成，新增 ${data.collected} 个商品`)
      collectDialog.value = false
    } else if (realTab.value === 'url') {
      if (!collectUrl.url.trim()) { ElMessage.warning('请输入商品页 URL'); return }
      const data = await scrapeByUrl({ url: collectUrl.url })
      collectResult.value = data.item
      collectEngine.value = data.engine
      ElMessage.success(`抓取成功（${data.engine}）：${data.parsed.title.slice(0, 30)}…`)
    } else {
      if (collectHtml.html.trim().length < 500) { ElMessage.warning('请粘贴完整的网页源码（不少于 500 字符）'); return }
      const data = await collectFromHtml({ url: collectHtml.url, html: collectHtml.html })
      collectResult.value = data.item
      collectEngine.value = data.engine
      ElMessage.success(`解析成功：${data.parsed.title.slice(0, 30)}…`)
    }
    load()
  } finally { collecting.value = false }
}

async function exportProductsCsv() {
  const res = await exportCsv()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(res.data)
  a.download = 'products.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function submitCreateProduct() {
  await createProduct({
    title: form.title, category: form.category,
    attrs: { supplier_price: form.supplier_price, sale_price: form.sale_price },
  })
  ElMessage.success('已创建')
  dialog.value = false
  load()
}

async function standardize(row) {
  stdLoading.value = row.id
  try {
    const data = await apiStandardize(row.id)
    ElMessage.success(`已标准化：类目=${data.category}${data.is_duplicate ? `（疑似重复商品 #${data.duplicate_of}）` : ''}`)
    load()
  } finally { stdLoading.value = null }
}

async function openDropship(row) {
  ds.product_id = row.id
  Object.assign(ds, { qty: 1, consignee: '', phone: '', address: '' })
  dsResult.value = {}
  dsDialog.value = true
  const data = await fetchShops()
  dsShops.value = (data.items || []).filter((s) => s.role === 'source' && s.platform === '1688')
  if (!dsShops.value.length) ElMessage.warning('暂无 1688 货源店铺，请先到「店铺授权」添加')
}

async function doDropship() {
  if (!ds.shop_id) return ElMessage.warning('请选择货源店铺')
  dsLoading.value = true
  try {
    const data = await createDropshipOrder(ds.product_id, {
      shop_id: ds.shop_id, qty: ds.qty, consignee: ds.consignee, phone: ds.phone, address: ds.address,
    })
    dsResult.value = { ...data, po_no: data.purchase.po_no }
    ElMessage.success(`代发下单成功（${data.mode === 'demo' ? '演示' : '真实'}）平台单号 ${data.platform_trade_no}`)
  } finally { dsLoading.value = false }
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
</style>
