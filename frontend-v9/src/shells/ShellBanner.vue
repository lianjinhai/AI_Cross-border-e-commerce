<template>
  <div>
    <el-alert
      v-if="impersonating"
      type="warning"
      :closable="false"
      show-icon
      class="shell-banner__item"
    >
      <template #title>
        <span>代客访问中{{ workspaceName ? `：${workspaceName}` : '' }}；所有操作将记入审计</span>
        <el-button size="small" type="warning" plain class="shell-banner__btn" @click="$emit('exit-impersonate')">
          退出代客
        </el-button>
      </template>
    </el-alert>
    <el-alert
      v-if="readOnly"
      type="info"
      :closable="false"
      show-icon
      class="shell-banner__item"
      title="只读模式：当前账号仅有查看权限，写操作已隐藏（fail-closed）"
    />
    <slot />
  </div>
</template>

<script setup>
/**
 * 状态横幅（AppShell 子件，NAVIGATION §4）：代客中（常显+一键退出）> 只读态。
 * partial 数据完整性提示由页面级横幅经 #banner 插槽追加。
 */
defineProps({
  impersonating: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
  workspaceName: { type: String, default: '' },
})

defineEmits(['exit-impersonate'])
</script>

<style scoped>
.shell-banner__item { border-radius: 0; }
.shell-banner__btn { margin-left: var(--space-3); }
</style>
