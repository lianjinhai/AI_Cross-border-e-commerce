<template>
  <el-select
    v-model="keyword"
    filterable
    remote
    clearable
    size="small"
    class="nav-search__select"
    placeholder="搜索页面"
    :remote-method="search"
    :loading="false"
    @change="go"
  >
    <el-option
      v-for="item in results"
      :key="item.path"
      :label="item.label"
      :value="item.path"
    />
  </el-select>
</template>

<script setup>
/**
 * 跨域页面搜索（顶栏规范「全局搜索」的 UX-B 子集）：按页面名检索当前空间菜单树
 * 并直达深链。前端聚合**已冻结的导航数据**，不引入后端新端点、不伪造数据面。
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  navigation: { type: Array, default: () => [] },
})

const router = useRouter()
const keyword = ref('')
const results = ref([])

function search(query) {
  const q = String(query || '').trim().toLowerCase()
  if (!q) { results.value = []; return }
  results.value = props.navigation
    .flatMap((domain) => domain.children.map((child) => ({
      path: child.path,
      label: `${domain.label} / ${child.label}`,
    })))
    .filter((item) => item.label.toLowerCase().includes(q))
    .slice(0, 10)
}

function go(path) {
  if (!path) return
  router.push(path)
  keyword.value = ''
  results.value = []
}
</script>

<style scoped>
.nav-search__select {
  width: 200px;
}
</style>
