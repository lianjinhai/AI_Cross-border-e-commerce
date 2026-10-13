<template>
  <div class="page">
    <PageHeader title="店铺授权" subtitle="授权向导 · 状态徽标统一 · 失败原因直出">
      <template #actions>
        <el-button size="small" @click="mappingDialog = true">类目映射设置</el-button>
        <el-button v-if="canWrite()" type="primary" size="small" @click="openWizard">添加店铺</el-button>
      </template>
    </PageHeader>

    <el-card>
      <el-table :data="shops" v-loading="loading" size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="shop_name" label="店铺" min-width="160" show-overflow-tooltip />
        <el-table-column prop="platform" label="平台" width="100" />
        <el-table-column label="角色" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.role === 'source' ? 'warning' : 'success'">
              {{ row.role === 'source' ? '货源' : '销售' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="授权状态" width="120">
          <template #default="{ row }">
            <el-tooltip v-if="row.auth_message" :content="row.auth_message" placement="top">
              <el-tag size="small" :type="shopStatusTag(row.status).type">{{ shopStatusTag(row.status).text }}</el-tag>
            </el-tooltip>
            <el-tag v-else size="small" :type="shopStatusTag(row.status).type">{{ shopStatusTag(row.status).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="目标市场" width="100">
          <template #default="{ row }">{{ row.market || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="330" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canWrite() && row.role === 'sales'" size="small" type="primary"
              @click="openWizard(row)">授权 / 重新授权</el-button>
            <el-button v-if="canWrite() && row.status === 'authorized'" size="small" :loading="refreshing === row.id"
              @click="doRefresh(row)">刷新授权</el-button>
            <el-button size="small" :loading="syncing === row.id" :disabled="row.role !== 'sales'"
              @click="doSyncOrders(row)">同步订单</el-button>
            <el-button v-if="canAdmin()" size="small" type="danger" plain @click="doRemove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="还没有店铺，点击右上角「添加店铺」开始授权向导" /></template>
      </el-table>
      <!-- 失败原因直出（验收：OAuth 失败原因可见） -->
      <el-alert v-for="shop in failedShops" :key="shop.id" type="error" :closable="false" class="mt8"
        :title="`「${shop.shop_name || `#${shop.id}`}」授权失败：${shop.auth_message || '原因未知，请重新走授权向导'}`" />
    </el-card>

    <!-- 授权向导（拆分件） -->
    <el-dialog v-model="wizardVisible" title="店铺授权向导" width="640px" :close-on-click-modal="false" destroy-on-close>
      <ShopAuthWizard ref="wizardRef" :platform-options="platformOptions" @done="onWizardDone" @cancel="wizardVisible = false" />
    </el-dialog>

    <!-- 类目映射设置 -->
    <el-dialog v-model="mappingDialog" title="类目映射设置" width="680px">
      <el-alert type="info" :closable="false" class="mb12"
        title="把系统类目映射到平台类目 ID；上架时按平台取映射结果。" />
      <el-table :data="mappings" size="small" v-loading="loadingMappings" max-height="260">
        <el-table-column prop="platform" label="平台" width="100" />
        <el-table-column prop="system_category" label="系统类目" min-width="140" />
        <el-table-column prop="platform_category_id" label="平台类目 ID" min-width="140" />
        <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button v-if="canWrite()" size="small" type="danger" plain @click="doRemoveMapping(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="暂无类目映射" /></template>
      </el-table>
      <el-divider>新增映射</el-divider>
      <el-form label-width="100px">
        <el-form-item label="平台">
          <el-select v-model="mapping.platform" style="width:100%">
            <el-option v-for="p in platformOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="系统类目"><el-input v-model="mapping.system_category" /></el-form-item>
        <el-form-item label="平台类目 ID"><el-input v-model="mapping.platform_category_id" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="mapping.note" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mappingDialog = false">关闭</el-button>
        <el-button v-if="canWrite()" type="primary" @click="doSaveMapping">保存映射</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 店铺授权（UX-C）：授权向导（ShopAuthWizard 三步）+ 状态徽标统一（shopStatusTag
 * 单一语义源）+ 失败原因直出（auth_message）+ 类目映射设置。517 行旧页拆分重组。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import EmptyState from '../../components/EmptyState.vue'
import ShopAuthWizard from '../../features/shops/ShopAuthWizard.vue'
import { can, canAdmin, canWrite } from '../../permissions/permissions'
import {
  fetchCategoryMappings, fetchPlatforms, fetchShops, refresh, removeCategoryMapping,
  removeShop, saveCategoryMapping, syncOrders,
} from '../../api/domains/shops'
import { shopStatusTag } from '../../composables/listingFlow'

const shops = ref([])
const platformOptions = ref([])
const mappings = ref([])
const loading = ref(false)
const loadingMappings = ref(false)
const refreshing = ref(null)
const syncing = ref(null)
const wizardVisible = ref(false)
const wizardRef = ref()
const mappingDialog = ref(false)
const mapping = reactive({ platform: '', system_category: '', platform_category_id: '', note: '' })

const failedShops = computed(() => shops.value.filter((s) => s.status === 'failed'))

async function load() {
  loading.value = true
  try {
    const data = await fetchShops()
    shops.value = data.items || []
  } finally { loading.value = false }
}

async function loadPlatforms() {
  try {
    const data = await fetchPlatforms()
    platformOptions.value = (data.items || []).map((p) => ({
      value: p.platform || p.value || p.code, label: p.label || p.platform || p.value || p.code,
    })).filter((p) => p.value)
  } catch { platformOptions.value = [] }
}

async function loadMappings() {
  loadingMappings.value = true
  try { mappings.value = (await fetchCategoryMappings()).items || [] }
  finally { loadingMappings.value = false }
}

function openWizard(shop = null) {
  wizardVisible.value = true
  // 既有店铺重新授权：向导直接进到「平台授权」步。
  if (shop && shop.id) wizardRef.value?.bindShop(shop)
}

function onWizardDone({ stage }) {
  if (stage === 'authorized') {
    wizardVisible.value = false
    load()
  }
}

async function doRefresh(row) {
  refreshing.value = row.id
  try {
    await refresh(row.id)
    ElMessage.success('授权已刷新')
    await load()
  } finally { refreshing.value = null }
}

async function doSyncOrders(row) {
  syncing.value = row.id
  try {
    await syncOrders(row.id)
    ElMessage.success('订单同步已触发')
  } finally { syncing.value = null }
}

async function doRemove(row) {
  try {
    await ElMessageBox.confirm(`删除店铺「${row.shop_name || `#${row.id}`}」？授权凭据将一并清除。`, '确认删除', { type: 'warning' })
  } catch { return }
  await removeShop(row.id)
  ElMessage.success('已删除')
  await load()
}

async function doSaveMapping() {
  if (!mapping.platform || !mapping.system_category || !mapping.platform_category_id) {
    return ElMessage.warning('平台 / 系统类目 / 平台类目 ID 均必填')
  }
  await saveCategoryMapping({ ...mapping })
  ElMessage.success('映射已保存')
  Object.assign(mapping, { platform: '', system_category: '', platform_category_id: '', note: '' })
  await loadMappings()
}

async function doRemoveMapping(row) {
  try {
    await ElMessageBox.confirm(`删除映射「${row.system_category} → ${row.platform_category_id}」？`, '确认删除', { type: 'warning' })
  } catch { return }
  await removeCategoryMapping(row.id)
  await loadMappings()
}

onMounted(() => { load(); loadPlatforms(); loadMappings() })
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.mt8 { margin-top: 8px; }
</style>
