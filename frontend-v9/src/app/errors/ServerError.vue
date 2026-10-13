<template>
  <div class="error-page">
    <el-result icon="error" title="500" sub-title="服务异常，请稍后重试">
      <template #extra>
        <el-button @click="reload">刷新重试</el-button>
        <el-button type="primary" @click="goHome">返回我的首页</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup>
/**
 * 500 页（契约 §3.3.3）：全局错误边界落点。
 */
import { defaultLanding } from '../../permissions/permissions'

function reload() {
  window.location.reload()
}

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
