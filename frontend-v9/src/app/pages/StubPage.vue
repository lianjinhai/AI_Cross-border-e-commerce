<template>
  <div class="page">
    <PageHeader :title="title" :subtitle="subtitle" />
    <el-empty :description="`${title} 页面由后续阶段（UX-C/D/E）按 V9 页面矩阵交付`">
      <p class="stub__hint">
        路由、权限与导航已按 V9 契约冻结接通；本页仅为占位，不含任何可点击业务入口。
      </p>
    </el-empty>
  </div>
</template>

<script setup>
/**
 * 路由占位页（UX-B）：真实页面由 UX-C/D/E 交付。
 *
 * 为什么需要它：UX-B 阶段路由 path/meta/懒加载结构按契约一次冻结并接通守卫，
 * 但页面本体未交付——占位页显式声明「未交付」，绝不伪造业务功能或可点击入口
 * （对应硬约束：后端未有的能力不留可点击入口）。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'

const route = useRoute()
const title = computed(() => route.meta?.title || '页面')
const subtitle = computed(() => route.meta?.domain || '')
</script>

<style scoped>
.stub__hint {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>
