<template>
  <div class="page">
    <PageHeader
      title="货源发现"
      subtitle="1688 / 私域工厂 / 手动供应商三来源 · 筛选 SKU / 成本币种 / MOQ / 交期"
    >
      <template #filters>
        <el-select v-model="filter.costCurrency" size="small" placeholder="成本币种" clearable style="width: 110px">
          <el-option v-for="c in CURRENCIES" :key="c" :label="c" :value="c" />
        </el-select>
        <el-input
          v-model="filter.sku" size="small" placeholder="SKU 关键词"
          clearable style="width: 150px"
        />
        <el-input
          v-model="filter.moqMax" size="small" placeholder="MOQ ≤" type="number"
          clearable style="width: 110px"
        />
        <el-input
          v-model="filter.shipDaysMax" size="small" placeholder="交期 ≤ 天" type="number"
          clearable style="width: 120px"
        />
      </template>
      <template #actions>
        <el-button @click="router.push('/app/supply/suppliers')">供应商库</el-button>
        <el-button @click="router.push('/app/supply/matching')">货源匹配</el-button>
      </template>
    </PageHeader>

    <!-- 来源 Tab：1688 / 私域工厂 / 手动供应商（三来源，不作 Sales 标签） -->
    <el-card shadow="never" class="mb16">
      <el-tabs v-model="activeTab">
        <el-tab-pane
          v-for="tab in SOURCING_TABS"
          :key="tab.key"
          :name="tab.key"
          :label="tab.label"
        >
          <!-- 1688 Tab：未接入标记（§7#7），只读骨架 + 禁用按钮 tooltip -->
          <div v-if="tabView.apiGap" class="tab-pane__gap">
            <SectionState code="NOT_CONFIGURED" action-text="手动添加供应商">
            </SectionState>
            <el-alert
              type="info" :closable="false" class="mt12"
              :title="tabView.hint"
              description="1688 货源 API 端点未核（§7#7）：未接入前本 Tab 只读，不渲染假数据。可在「手动供应商」Tab 或供应商库中手工录入 1688 货源信息。"
            />
            <el-tooltip
              content="1688 未接入，手动添加供应商可用"
              placement="top"
            >
              <el-button type="primary" disabled class="mt12">从 1688 拉取货源</el-button>
            </el-tooltip>
          </div>

          <!-- 工厂/手动 Tab：真实数据（suppliers.js） -->
          <div v-else>
            <DataQualityBanner
              v-if="!tabView.items.length"
              tag="UNKNOWN"
              detail="当前来源暂无数据，可到供应商库新增源头工厂或手动供应商"
              :links="[{ label: '进入供应商库', path: '/app/supply/suppliers' }]"
            />
            <DataTable
              v-else
              :columns="supplierColumns"
              :loader="makeLoader(tab.key)"
              :reload-key="filterKey"
              empty-hint="该来源暂无匹配供应商"
            >
              <template #cell-verification_status="{ row }">
                <el-tag size="small" :type="row.verification_status === 'verified' ? 'success' : 'warning'">
                  {{ row.verification_status || 'candidate' }}
                </el-tag>
              </template>
              <template #cell-cost_currency="{ row }">
                <span>{{ row.cost_currency || '—' }}</span>
              </template>
              <template #cell-moq="{ row }">{{ row.moq ?? '—' }}</template>
              <template #cell-ship_days="{ row }">{{ row.ship_days ?? '—' }}</template>
            </DataTable>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
/**
 * 货源发现（蓝图 R1 SU-01，包 2）：/app/supply/sourcing。
 *
 * 数据源：1688 端点未核（§7#7）→ 1688 Tab "未接入，手动添加可用"；
 * 手动供应商/工厂走 suppliers.js 真实数据。三来源 Tab（不作 Sales 标签）。
 * 筛选：SKU / 成本币种 / MOQ / 交期（纯函数 shared/sourcingView.js）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import DataTable from '../../components/DataTable.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchSuppliers } from '../../api/domains/suppliers'
import {
  SOURCING_TABS, splitSourcingTab, filterSourcing,
} from '../../shared/sourcingView'

const router = useRouter()
const CURRENCIES = ['CNY', 'USD', 'EUR']

const activeTab = ref('manual')
const filter = reactive({ sku: '', costCurrency: '', moqMax: null, shipDaysMax: null })

const supplierColumns = [
  { prop: 'name', label: '供应商', minWidth: 150 },
  { prop: 'verification_status', label: '核验', width: 90 },
  { prop: 'cost_currency', label: '成本币种', width: 100 },
  { prop: 'moq', label: 'MOQ', width: 80 },
  { prop: 'ship_days', label: '交期(天)', width: 90 },
  { prop: 'rating', label: '评分', width: 70 },
]

const suppliers = ref([])
const filterKey = computed(() => JSON.stringify({ tab: activeTab.value, ...filter }))

/** 当前 Tab 视图（1688 恒 apiGap + 空列；工厂/手动按 source 分列）。 */
const tabView = computed(() => splitSourcingTab(suppliers.value, activeTab.value))

/** 经共享筛选函数（SKU/币种/MOQ/交期）的展示集——DataTable 走 loader，此处供 Banner 判空。 */
const filteredItems = computed(() => filterSourcing(tabView.value.items, filter))

/** DataTable loader：按当前 Tab + 筛选过滤，返回 {items,total}。 */
function makeLoader(tabKey) {
  return async () => {
    const view = splitSourcingTab(suppliers.value, tabKey)
    return { items: filterSourcing(view.items, filter), total: filterSourcing(view.items, filter).length }
  }
}

async function loadSuppliers() {
  try {
    const data = await fetchSuppliers()
    suppliers.value = data.items || []
  } catch {
    suppliers.value = []
  }
}

onMounted(loadSuppliers)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.mt12 { margin-top: 12px; }
.tab-pane__gap { padding: 8px 0; }
</style>
