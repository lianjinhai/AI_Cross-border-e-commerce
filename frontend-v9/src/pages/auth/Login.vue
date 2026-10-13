<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2 class="login-title">AI 电商ERP</h2>
      <p class="login-sub">AI 原生跨境电商智能运营平台</p>
      <el-form @keyup.enter="doLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" data-test="login-username" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
        </el-form-item>
        <el-button type="primary" size="large" style="width:100%" :loading="loading" @click="doLogin">
          登 录
        </el-button>
      </el-form>
      <el-alert v-if="error" type="error" :closable="false" class="mt16" :title="error" />
      <el-alert class="mt16" type="info" :closable="false"
        title="演示账号：admin/admin123（管理员）｜ops/ops123（运营）｜viewer/viewer123（只读）" />
    </el-card>
  </div>
</template>

<script setup>
/**
 * 登录页（UX-E，302 表 #1：/login → /console/login）：
 * POST /auth/login → 存 token/user → loadWorkspaceContext → defaultLanding 分流
 * （超管→/console/overview、工厂→/factory/products、合规→合规台、其余→/app）。
 * 无注册页：后端无注册端点，不放入口（红线：不留虚构能力入口）。
 */
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { loadWorkspaceContext } from '../../shared/workspace'
import { defaultLanding } from '../../permissions/permissions'
import { login } from '../../api/domains/auth'

const router = useRouter()
const form = reactive({ username: '', password: '' })
const loading = ref(false)
const error = ref('')

async function doLogin() {
  if (!form.username.trim() || !form.password) {
    error.value = '请输入用户名与密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await login({ username: form.username.trim(), password: form.password })
    localStorage.setItem('erp_token', data.token)
    localStorage.setItem('erp_user', JSON.stringify(data.user))
    await loadWorkspaceContext()
    await router.push(defaultLanding())
  } catch (e) {
    error.value = e?.response?.data?.detail?.message
      || (typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : '')
      || '登录失败，请核对用户名与密码'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: linear-gradient(135deg, #1f2d3d 0%, #2b4c7e 100%);
}
.login-card { width: 420px; padding: 12px 8px; }
.login-title { text-align: center; margin-top: 0; }
.login-sub { text-align: center; color: var(--color-text-secondary); margin-bottom: 24px; }
.mt16 { margin-top: 16px; }
</style>
