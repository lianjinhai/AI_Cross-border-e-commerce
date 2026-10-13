<template>
  <div class="data-table">
    <el-table v-loading="loading" :data="items" border stripe>
      <el-table-column
        v-for="col in columns"
        :key="col.prop"
        :prop="col.prop"
        :label="col.label"
        :width="col.width"
        :min-width="col.minWidth"
        :fixed="col.fixed"
        :align="col.align"
      >
        <template v-if="$slots[`cell-${col.prop}`]" #default="scope">
          <slot :name="`cell-${col.prop}`" v-bind="scope" />
        </template>
      </el-table-column>
      <template #empty>
        <EmptyState :reason="emptyReason" :hint="emptyHint">
          <template #action><slot name="empty-action" /></template>
        </EmptyState>
      </template>
    </el-table>
    <el-pagination
      v-if="total > pageSize"
      class="data-table__pager"
      layout="prev, pager, next, total"
      :total="total"
      :page-size="pageSize"
      :current-page="page"
      @current-change="onPageChange"
    />
  </div>
</template>

<script setup>
/**
 * 列表页统一表格封装（V9 第 1 批，设计系统 §2 新增）：列定义 + 分页。
 * loader 形态：async ({ page, pageSize }) => { items, total }；分页状态同步到
 * route.query.page（URL 状态同步），刷新/回跳不丢页码。
 * 单元格自定义：具名插槽 `cell-<prop>`（scope 含 row）。
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EmptyState from './EmptyState.vue'

const props = defineProps({
  columns: { type: Array, default: () => [] },
  loader: { type: Function, required: true },
  pageSize: { type: Number, default: 20 },
  emptyReason: { type: String, default: 'NO_DATA' },
  emptyHint: { type: String, default: '' },
  // 变化时重置回第 1 页并重载的依赖（如筛选参数对象）。
  reloadKey: { type: [String, Number, Object], default: '' },
})

const route = useRoute()
const router = useRouter()

const items = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(Number(route.query.page) || 1)

async function load() {
  loading.value = true
  try {
    const data = await props.loader({ page: page.value, pageSize: props.pageSize })
    items.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total ?? 0)
  } finally {
    loading.value = false
  }
}

function onPageChange(next) {
  page.value = next
  // URL 状态同步：页码进 query，刷新/回跳不丢。
  router.replace({ query: { ...route.query, page: next > 1 ? String(next) : undefined } })
}

onMounted(load)
watch(() => props.reloadKey, () => { page.value = 1; load() })
</script>

<style scoped>
.data-table__pager {
  margin-top: var(--space-3);
  justify-content: flex-end;
}
</style>
