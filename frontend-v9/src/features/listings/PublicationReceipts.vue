<template>
  <div v-loading="loading">
    <el-alert type="info" :closable="false" title="提交成功不等于已在售。请选择对应店铺的回执查看；历史记录可能尚未核验。" />
    <el-select v-model="selectedId" placeholder="选择店铺回执" style="width:100%;margin:16px 0" @change="result = null">
      <el-option v-for="item in items" :key="item.id" :value="item.id"
                 :label="`${item.shop_name || item.shop_id} · ${item.external_id || '尚无回执'}`" />
    </el-select>
    <el-pagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" />
    <template v-if="selected">
      <p>平台状态：{{ selected.platform_status }} · 核验状态：{{ selected.verification_status }}</p>
      <el-button v-if="selected.can_query_submission" @click="query" :loading="querying">查询此店铺提交结果</el-button>
      <p v-else>该记录暂无可用的自动状态查询。</p>
    </template>
    <el-empty v-if="!loading && !items.length" description="没有可归属店铺的发布回执" />
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <pre v-if="result" style="white-space:pre-wrap;max-height:360px;overflow:auto">{{ JSON.stringify(result, null, 2) }}</pre>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchListingReceipts } from '../../api/domains/listings'
import { queryPublicationReceipt } from '../../composables/publicationReceipts'

/**
 * 发布回执面板（listings 域组件，PublicationReceipts 逻辑平移）：
 * 数据走 api/domains/listings.fetchListingReceipts（契约 §4.2 修订版），页面不直接 import axios。
 */
const props = defineProps({ listingId: { type: Number, required: true } })
const items = ref([]), selectedId = ref(null), loading = ref(false), querying = ref(false)
const page = ref(1), total = ref(0)
const result = ref(null), error = ref('')
const selected = computed(() => items.value.find(item => item.id === selectedId.value))
async function load() {
  loading.value = true
  selectedId.value = null; result.value = null
  try {
    const data = await fetchListingReceipts(props.listingId)
    items.value = data.items; total.value = data.total
  }
  catch (e) { error.value = e.response?.data?.detail || e.message }
  finally { loading.value = false }
}
onMounted(load)
async function query() {
  querying.value = true; error.value = ''; result.value = null
  try { result.value = await queryPublicationReceipt(selected.value) }
  catch (e) { error.value = e.response?.data?.detail || e.message }
  finally { querying.value = false }
}
</script>
