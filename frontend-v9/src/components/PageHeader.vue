<template>
  <div class="page-header">
    <div class="page-header__text">
      <div class="page-header__breadcrumb">
        <slot name="breadcrumb" />
      </div>
      <div class="page-header__title">{{ title }}</div>
      <div v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</div>
    </div>
    <div class="page-header__actions">
      <!-- 从上线流程跳入专业页（商品/Listing/店铺）时，回跳按钮由路由 query 驱动，
           专业页无需逐个改造即可返回原步骤；无合法 return_to 时不渲染该按钮。 -->
      <el-button v-if="returnTo" size="small" @click="goBack">返回上一步</el-button>
      <slot name="filters" />
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
/**
 * 页头（V9 第 1 批公共组件，契约 §2/设计系统 §2）：标题+副题+主操作区+面包屑。
 * slots：breadcrumb / filters / actions。当 `route.query.return_to` 通过站内
 * 白名单校验时渲染「返回上一步」（AC-14.7 闭环）。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isSafeReturnTo } from '../shared/navigationReturn'

defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
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
.page-header__subtitle {
  margin-top: 2px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>
