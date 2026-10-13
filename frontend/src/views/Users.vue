<template>
  <div class="page">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>用户与角色</span>
          <el-button v-if="can('workspace:member:admin')" type="primary" @click="openCreate">新增用户</el-button>
        </div>
      </template>
      <el-alert
        type="info"
        :closable="false"
        class="mb16"
        title="管理员维护租户成员；合规审批（COMPLIANCE）只负责上架人工审批，只读（READ_ONLY）仅可查看。"
      />
      <el-table :data="items" v-loading="loading">
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="display_name" label="姓名" />
        <el-table-column label="角色">
          <!-- 展示 Context 权威的大写枚举，与 workspace_context 下发口径一致 -->
          <template #default="{ row }">{{ roleEnumLabel(row.role) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" />
        <el-table-column label="操作">
          <template #default="{ row }">
            <el-button v-if="can('workspace:member:admin')" link @click="edit(row)">编辑</el-button>
            <el-button v-if="can('workspace:member:admin')" link type="danger" :disabled="row.id === me.id" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" :title="form.id ? '编辑用户' : '新增用户'">
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="!!form.id" />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.display_name" />
        </el-form-item>
        <el-form-item label="角色">
          <!-- el-option 的 value 保持 legacy 小写（后端唯一接受的取值），label 展示大写枚举 -->
          <el-select v-model="form.role">
            <el-option v-for="x in roles" :key="x.value" :label="x.label" :value="x.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="form.id ? '留空不修改' : '至少 10 位'"
          />
        </el-form-item>
        <el-form-item v-if="form.id" label="状态">
          <el-select v-model="form.status">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'
import { can } from '../permissions'
import { contextUserId } from '../workspace'

// Phase 1.8：当前用户 id 只从 Workspace Context 取（唯一身份来源）。
// 这里仅用于「禁止删除自己」的前端体验优化；后端 `DELETE /auth/users/{id}`
// 有同样的 400 保护，因此 Context 未就绪时 me.id 为 null 不会造成越权。
// 用 computed 而非常量：切换 Workspace 后 Context 会重载，id 必须跟着变。
const me = computed(() => ({ id: contextUserId() }))
const items = ref([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)

/**
 * UX-B8 角色枚举统一：UI 展示与 Context 权威大写枚举一致。
 *
 * 为什么不直接把提交值改成大写：后端 `POST/PUT /auth/users` 只接受 legacy 小写
 * （`admin/compliance_approver/operator/viewer`，见 backend/app/routers/auth.py 第 96、
 * 119 行校验），而 Context（backend/app/services/workspace_context.py 的
 * `_LEGACY_ROLE_MAP`）把 legacy 归一为大写枚举下发。因此做「展示大写 ↔ 提交原值」
 * 映射即可对齐 UI，无需改后端。若后端将来直接接受大写，再切 value 为本枚举。
 */
const ROLE_ENUM = {
  admin: 'OWNER',
  compliance_approver: 'COMPLIANCE',
  operator: 'OPERATOR',
  viewer: 'READ_ONLY',
}
const roles = [
  { value: 'admin', label: 'OWNER（管理员）' },
  { value: 'compliance_approver', label: 'COMPLIANCE（合规审批员）' },
  { value: 'operator', label: 'OPERATOR（运营）' },
  { value: 'viewer', label: 'READ_ONLY（只读）' },
]
function roleEnumLabel(value) {
  return ROLE_ENUM[value] || value
}

const blank = () => ({
  id: null, username: '', display_name: '', role: 'operator', password: '', status: 'active',
})
const form = reactive(blank())

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/auth/users', { params: { page_size: 100 } })
    items.value = data.items || []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, blank())
  dialog.value = true
}

function edit(row) {
  Object.assign(form, blank(), row, { password: '' })
  dialog.value = true
}

async function save() {
  if (!form.id && (!form.username || form.password.length < 10)) {
    return ElMessage.warning('用户名必填，初始密码至少 10 位')
  }
  saving.value = true
  try {
    if (form.id) {
      const body = { display_name: form.display_name, role: form.role, status: form.status }
      if (form.password) body.password = form.password
      await api.put(`/auth/users/${form.id}`, body)
    } else {
      await api.post('/auth/users', form)
    }
    dialog.value = false
    ElMessage.success('用户已保存')
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除用户 ${row.username}？`, '确认', { type: 'warning' })
  await api.delete(`/auth/users/${row.id}`)
  load()
}

onMounted(load)
</script>
