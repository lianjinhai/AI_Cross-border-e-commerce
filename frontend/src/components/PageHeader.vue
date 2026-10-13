<template>
  <div class="page-header">
    <div class="page-header__text">
      <div class="page-header__breadcrumb">
        <slot name="breadcrumb" />
      </div>
      <div class="page-header__title">{{ title }}</div>
    </div>
    <div class="page-header__actions">
      <!-- 从上线流程跳入专业页（商品/Listing/店铺）时，回跳按钮由路由 query 驱动，
           专业页无需逐个改造即可返回原步骤；无合法 return_to 时不渲染该按钮。 -->
      <el-button v-if="returnTo" size="small" @click="goBack">返回上一步</el-button>
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
/**
 * 页头（UX-02；UX-03 增补回跳）。
 * 标题沿用现网字号（16px / 600）；`#breadcrumb`、`#actions` 具名插槽。
 * 当 `route.query.return_to` 通过站内白名单校验时，渲染「返回上一步」。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isSafeReturnTo } from '../utils/navigationReturn'

defineProps({
  title: { type: String, default: '' },
})

const route = useRoute()
const router = useRouter()

const returnTo = computed(() => {
  const value = route.query.return_to
  return typeof value === 'string' && isSafeReturnTo(value) ? value : ''
})

function goBack() {
  router.push(returnTo.value)
}
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-header__breadcrumb:empty {
  display: none;
}
.page-header__title {
  font-size: 16px;
  font-weight: 600;
}
</style>
