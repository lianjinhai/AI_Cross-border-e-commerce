<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2 style="text-align:center;margin-top:0">🤖 AI 电商ERP</h2>
      <p style="text-align:center;color:#909399;margin-bottom:24px">AI 原生跨境电商智能运营平台</p>
      <el-form @keyup.enter="doLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名（admin / ops / viewer）" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
        </el-form-item>
        <el-button type="primary" size="large" style="width:100%" :loading="loading" @click="doLogin">
          登 录
        </el-button>
      </el-form>
      <el-alert style="margin-top:16px" type="info" :closable="false"
        title="演示账号：admin/admin123（管理员）｜ops/ops123（运营）｜viewer/viewer123（只读）" />
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { loadWorkspaceContext } from '../workspace'

const router = useRouter()
const form = reactive({ username: 'admin', password: 'admin123' })
const loading = ref(false)

async function doLogin() {
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', form)
    localStorage.setItem('erp_token', data.token)
    localStorage.setItem('erp_user', JSON.stringify(data.user))
    await loadWorkspaceContext()
    router.push('/dashboard')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap { display: flex; align-items: center; justify-content: center; height: 100vh;
  background: linear-gradient(135deg, #1f2d3d 0%, #2b4c7e 100%); }
.login-card { width: 420px; padding: 12px 8px; }
</style>
