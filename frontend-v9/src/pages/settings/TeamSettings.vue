<template>
  <div class="page">
    <PageHeader title="用户与角色" subtitle="成员管理（OWNER 专属） · 按角色枚举给权限说明卡">
      <template #actions>
        <el-button v-if="writable" type="primary" @click="openCreate">新增用户</el-button>
      </template>
    </PageHeader>

    <SectionState :state="listState" :error="error" :trace-id="traceId" @retry="load">
      <FormSection title="权限说明" description="角色能力范围人读版；权威判定以后端 workspace_context 下发的权限目录为准">
        <div class="guide-grid">
          <el-card v-for="g in ROLE_GUIDES" :key="g.key" shadow="never" class="guide-card">
            <h4 class="guide-title">{{ g.title }}</h4>
            <ul class="guide-list">
              <li v-for="(p, i) in g.points" :key="i">{{ p }}</li>
            </ul>
          </el-card>
        </div>
      </FormSection>

      <FormSection title="成员列表" :description="ROLE_CHANGE_NOTE">
        <el-table :data="items" v-loading="loading" size="small">
          <el-table-column prop="username" label="用户名" min-width="140" />
          <el-table-column prop="display_name" label="姓名" min-width="120" />
          <el-table-column label="角色" width="220">
            <!-- 展示 Context 权威大写枚举，与 workspace_context 下发口径一致 -->
            <template #default="{ row }">
              <el-tag size="small" :type="roleTagType(row.role)">{{ roleEnumLabel(row.role) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">
                {{ row.status === 'active' ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button v-if="writable" link @click="edit(row)">编辑</el-button>
              <el-button v-if="writable" link type="danger" :disabled="row.id === meId" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="暂无成员" /></template>
        </el-table>
      </FormSection>
    </SectionState>

    <el-dialog v-model="dialog" :title="form.id ? '编辑用户' : '新增用户'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="用户名"><el-input v-model="form.username" :disabled="!!form.id" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="角色">
          <!-- value 保持 legacy 小写（后端唯一接受的取值），label 展示大写枚举 -->
          <el-select v-model="form.role" style="width: 100%">
            <el-option v-for="x in ROLE_OPTIONS" :key="x.value" :label="x.label" :value="x.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password" type="password" show-password
            :placeholder="form.id ? '留空不修改' : '至少 10 位'"
          />
        </el-form-item>
        <el-form-item v-if="form.id" label="状态">
          <el-select v-model="form.status" style="width: 100%">
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
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import SectionState from '../../components/SectionState.vue'
import { can } from '../../permissions/permissions'
import { normalizeError } from '../../shared/api/errors'
import { contextUserId } from '../../shared/workspace'
import { fetchUsers, createUser, updateUser, deleteUser } from '../../api/domains/users'
import { ROLE_CHANGE_NOTE, ROLE_GUIDES, ROLE_OPTIONS, roleEnumLabel } from '../../features/settings/roleGuides'

const writable = can('workspace:member:admin')

const items = ref([])
const loading = ref(false)
const error = ref('')
const traceId = ref('')
const dialog = ref(false)
const saving = ref(false)

/** 当前用户 id 只从 Workspace Context 取（唯一身份来源；用于禁止删除自己）。 */
const meId = computed(() => contextUserId())

const listState = computed(() => {
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  if (!items.value.length) return 'empty'
  return 'ready'
})

function roleTagType(role) {
  return { admin: 'danger', compliance_approver: 'warning', operator: 'primary', viewer: 'info' }[role] || 'info'
}

async function load() {
  loading.value = true
  error.value = ''
  traceId.value = ''
  try {
    const data = await fetchUsers()
    items.value = data.items || []
  } catch (e) {
    const norm = normalizeError(e)
    error.value = norm.message
    traceId.value = norm.traceId || ''
  } finally {
    loading.value = false
  }
}

const blank = () => ({
  id: null, username: '', display_name: '', role: 'operator', password: '', status: 'active',
})
const form = reactive(blank())

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
      await updateUser(form.id, body)
    } else {
      await createUser({ ...form })
    }
    dialog.value = false
    ElMessage.success('用户已保存（角色修改即时反映菜单可见性）')
    load()
  } catch (e) {
    ElMessage.error(normalizeError(e).message)
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除用户 ${row.username}？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  await deleteUser(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.guide-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--space-3); }
.guide-title { margin: 0 0 8px; }
.guide-list { margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.8; color: var(--color-text-regular, #606266); }
</style>
