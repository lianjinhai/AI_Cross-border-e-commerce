<template>
  <div class="page">
    <PageHeader title="报价与供货能力" subtitle="报价 / MOQ / 币种 / 库存时效（由产品与产能拆分）">
      <template #actions>
        <el-button size="small" @click="goProducts">管理产品与产能</el-button>
      </template>
    </PageHeader>

    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />

    <el-alert
      type="info" :closable="false" show-icon class="mb16"
      title="本页只读展示本厂供货能力字段；编辑请进入「产品与产能」。"
      description="报价/MOQ/币种/库存时效由产品与产能页拆分至此，主入口 /factory/products 保留完整编辑。"
    />

    <SectionState :code="code" @retry="load" :error="error" empty-hint="还没有供货能力数据">
      <el-table :data="items" size="small">
        <template v-for="col in capabilityCols" :key="col.key">
          <el-table-column :prop="col.key" :label="col.label">
            <template v-if="col.key === 'unit_price'" #default="{ row }">
              {{ formatMoney(row.unit_price, row.currency) }}
            </template>
            <template v-else #default="{ row }">
              {{ row[col.key] == null ? '—' : row[col.key] }}
            </template>
          </el-table-column>
        </template>
        <template #empty>
          <EmptyState reason="NO_DATA" hint="还没有供货能力数据，请先进入「产品与产能」维护" />
        </template>
      </el-table>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 报价/库存/产能（蓝图 R1 包 3 · FP-03，§B.3）：/factory/capability。
 *
 * 由 FactoryProducts（FP-02 主入口 /factory/products）拆出的**只读供货能力视图**：
 * 报价/MOQ/币种/库存时效列由 shared/factoryCatalogSplit.js 的 CAPABILITY_COLUMNS 驱动，
 * 与主入口共享同一字段切分，避免字段重复实现。只读：编辑仍走 /factory/products。
 * 11 态全区块经 SectionState code；金额缺值显"—"（不渲染 0）。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchPortalProducts } from '../../api/domains/factoryNetwork'
import { CAPABILITY_COLUMNS, splitCatalogRow } from '../../shared/factoryCatalogSplit'
import { envTag } from '../../shared/dataLabels'

const envBanner = envTag()
const router = useRouter()

const items = ref([])
const code = ref('LOADING')
const error = ref('')

const capabilityCols = CAPABILITY_COLUMNS

/** 金额缺值显"—"（缺值不渲染 0）；有币种时拼"币种 值"。 */
function formatMoney(value, currency) {
  if (value == null) return '—'
  const c = currency ? `${currency} ` : ''
  return `${c}${value}`
}

/** 行拆分：capability 视图只取供货能力字段（保留商品主档 id 作 key）。 */
function toCapabilityRows(rows = []) {
  return rows.map((row) => {
    const { capability } = splitCatalogRow(row)
    return capability
  })
}

function goProducts() {
  router.push('/factory/products')
}

function load() {
  code.value = 'LOADING'
  error.value = ''
  fetchPortalProducts()
    .then((data) => {
      const rows = data?.items || []
      items.value = toCapabilityRows(rows)
      code.value = rows.length ? 'ready' : 'EMPTY_NEW'
    })
    .catch((e) => {
      const detail = e?.response?.data?.detail
      error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
      code.value = 'ERROR'
    })
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
</style>
