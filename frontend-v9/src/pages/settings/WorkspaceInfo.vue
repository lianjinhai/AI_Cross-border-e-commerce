<template>
  <div class="page">
    <PageHeader
      title="空间信息"
      subtitle="名称 / 类型（个人·企业）/ 经营目标 / 地区偏好 · 升级不触发数据迁移"
    >
      <template #actions>
        <el-button v-if="writable" type="primary" :loading="saving" @click="save">保存偏好</el-button>
      </template>
    </PageHeader>

    <SectionState :code="code" :error="error" @retry="load">
      <el-card shadow="never" class="mb16">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="空间名称">
            <el-input
              v-if="writable" v-model="form.name" :disabled="!writable"
            />
            <span v-else>{{ form.name || '—' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="空间类型">
            <el-tag :type="form.kind === 'PERSONAL' ? 'info' : 'success'" effect="plain">
              {{ form.kind === 'PERSONAL' ? '个人 PERSONAL' : form.kind === 'ORGANIZATION' ? '企业 ORGANIZATION' : (form.kind || '—') }}
            </el-tag>
            <span v-if="!form.kind" class="field-gap">字段未核（缺口标记）</span>
          </el-descriptions-item>
          <el-descriptions-item label="经营目标">
            <el-input
              v-if="writable" v-model="form.goal" placeholder="如：跨境女装 · 东南亚市场"
            />
            <span v-else>{{ form.goal || '—' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="地区偏好">
            <el-select
              v-if="writable" v-model="form.regions" multiple
              placeholder="选择目标地区" style="width: 100%"
            >
              <el-option v-for="r in REGION_OPTIONS" :key="r" :label="r" :value="r" />
            </el-select>
            <span v-else>{{ form.regions?.length ? form.regions.join('、') : '—' }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <DataQualityBanner
        tag="API_UNVERIFIED"
        detail="me/workspace 端点部分字段未核（经营目标/地区偏好写端点缺口）：未核字段仅读显示，缺口以标记明示，不做假保存成功"
      />
    </SectionState>

    <el-alert
      type="info" :closable="false" class="upgrade-note"
      title="个人升级企业"
      description="将 PERSONAL 空间升级为 ORGANIZATION 类型时，不触发 Product/Order 等既有数据迁移：历史数据保持归属，仅空间能力与成员权限扩展。"
    />
  </div>
</template>

<script setup>
/**
 * 空间信息（蓝图 R1 SET-01，包 2）：/app/settings/workspace（requiresOwner）。
 *
 * 数据源：me.js（workspace-context 字段）；经营目标/地区偏好写端点未核 →
 * 缺项标缺口，不触发迁移。个人升级企业不触发 Product/Order 迁移（文案明示）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { ElMessage } from '../../shared/ui'
import { ensureWorkspaceContext } from '../../shared/workspace'
import { can } from '../../permissions/permissions'

const writable = can('workspace:member:admin')
const REGION_OPTIONS = ['东南亚', '北美', '欧洲', '日本', '韩国', '拉美']

const form = reactive({
  name: '',
  kind: '',
  goal: '',
  regions: [],
})

const loading = ref(false)
const saving = ref(false)
const error = ref('')

const code = computed(() => {
  if (error.value) return 'ERROR'
  if (loading.value) return 'LOADING'
  return 'ready'
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const ctx = await ensureWorkspaceContext()
    if (!ctx) {
      error.value = '当前空间 Context 不可用（未登录或空间已失效）'
      return
    }
    form.name = ctx.workspace_name || ''
    form.kind = ctx.workspace_kind || ''
    // 经营目标/地区偏好：未核字段缺口 → 读 ctx 上已有键，缺则保持空并标缺口
    form.goal = ctx.goal || ctx.business_goal || ''
    form.regions = Array.isArray(ctx.regions) ? ctx.regions : []
  } catch (e) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!writable) return
  saving.value = true
  try {
    // 写端点未核：仅保存可写部分；缺口字段不伪造成功态。
    // 名称/目标/地区偏好若无真实写端点，提示"字段未核，暂不可保存"。
    ElMessage.info('空间信息保存：名称/目标/地区偏好写端点未核（缺口标记），已保持只读展示')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.field-gap {
  margin-left: 8px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}
.upgrade-note { margin-top: 4px; }
</style>
