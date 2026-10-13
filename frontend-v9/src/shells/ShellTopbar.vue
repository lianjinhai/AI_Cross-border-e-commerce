<template>
  <div class="shell-topbar__account">
    <el-tag v-if="roleKey" size="small" type="info" class="shell-topbar__role">{{ roleLabel }}</el-tag>
    <el-dropdown trigger="click" @command="onCommand">
      <span class="shell-topbar__user">
        <el-icon><UserFilled /></el-icon>
        <span v-if="userName">{{ userName }}</span>
        <el-icon class="shell-topbar__caret"><ArrowDown /></el-icon>
      </span>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-if="impersonating" command="exit-impersonate">退出代客</el-dropdown-item>
          <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup>
/**
 * 顶栏账户区（AppShell 子件，NAVIGATION §4「账户」行）：
 * 角色徽标 + 用户菜单（退出登录；退出代客仅代客时出现）。
 */
import { computed } from 'vue'

const props = defineProps({
  space: { type: String, default: 'workspace' },
  roleKey: { type: String, default: '' },
  userName: { type: String, default: '' },
  impersonating: { type: Boolean, default: false },
})

const emit = defineEmits(['logout', 'exit-impersonate'])

const ROLE_LABELS = {
  OWNER: '所有者', OPERATOR: '运营', READ_ONLY: '只读', COMPLIANCE: '合规员',
  PLATFORM_ADMIN: '平台管理员', FACTORY_COLLABORATOR: '工厂伙伴',
}

const roleLabel = computed(() => ROLE_LABELS[props.roleKey] || props.roleKey)

function onCommand(cmd) {
  if (cmd === 'logout') emit('logout')
  if (cmd === 'exit-impersonate') emit('exit-impersonate')
}
</script>

<style scoped>
.shell-topbar__account {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.shell-topbar__user {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: var(--color-text-regular);
  font-size: var(--font-size-md);
}
.shell-topbar__caret { font-size: 12px; }
</style>
