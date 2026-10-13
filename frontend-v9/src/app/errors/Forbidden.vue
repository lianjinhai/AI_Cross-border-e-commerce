<template>
  <div class="error-page">
    <el-result icon="error" title="403" sub-title="当前账号没有访问该页面的权限">
      <template #extra>
        <el-button type="primary" @click="goLanding">返回默认落地页</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup>
/**
 * 403 页（契约 §3.3.3）：已登录但白名单拒绝时的落点，
 * 页内可「返回默认落地页」（按角色分流 defaultLanding()）。
 */
import { defaultLanding } from '../../permissions/permissions'

function goLanding() {
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
