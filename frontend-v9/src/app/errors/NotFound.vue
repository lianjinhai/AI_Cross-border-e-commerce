<template>
  <div class="error-page">
    <el-result icon="warning" title="404" sub-title="页面不存在或已被迁移">
      <template #extra>
        <el-button type="primary" @click="goHome">返回我的首页</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup>
/**
 * 404 页（契约 §3.3.3）：未匹配路由统一落此页（不做静默 /app 兜底，
 * 便于暴露 302 映射遗漏）。「返回我的首页」按角色分流到 defaultLanding()。
 */
import { defaultLanding } from '../../permissions/permissions'

function goHome() {
  window.location.assign(defaultLanding())
}
</script>

<style scoped>
.error-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--color-bg);
}
</style>
