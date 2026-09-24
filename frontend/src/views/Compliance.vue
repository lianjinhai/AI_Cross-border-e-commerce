<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card class="mb16">
          <template #header>发起合规检测</template>
          <el-form label-width="90px">
            <el-form-item label="检测对象">
              <el-radio-group v-model="form.target_type">
                <el-radio-button value="product">商品</el-radio-button>
                <el-radio-button value="listing">Listing</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="对象 ID">
              <el-input-number v-model="form.ref_id" :min="1" style="width:100%" />
            </el-form-item>
            <el-button v-if="can('compliance:check')" type="primary" style="width:100%" :loading="checking" @click="check">
              开始检测（品牌/宣称/图片/规则）
            </el-button>
          </el-form>
          <el-alert style="margin-top:12px" type="info" :closable="false"
            title="检测项：商标侵权（高危）、广告法违禁宣称、图片水印/缺失、平台规则" />
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card>
          <template #header>检测报告</template>
          <el-table :data="reports" v-loading="loading" size="small">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="target_type" label="对象" width="90" />
            <el-table-column label="对象ID" width="90">
              <template #default="{ row }">{{ row.product_id || row.listing_id }}</template>
            </el-table-column>
            <el-table-column label="合规分" width="160">
              <template #default="{ row }">
                <el-progress :percentage="row.score" :color="row.score >= 85 ? '#67C23A' : row.score >= 60 ? '#E6A23C' : '#F56C6C'" />
              </template>
            </el-table-column>
            <el-table-column label="风险" width="80"><template #default="{ row }"><run-status :status="row.risk_level" /></template></el-table-column>
            <el-table-column label="问题数" width="80">
              <template #default="{ row }">{{ (row.issues || []).length }}</template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="160" />
            <el-table-column label="操作" width="90">
              <template #default="{ row }"><el-button size="small" @click="show(row)">详情</el-button></template>
            </el-table-column>
          </el-table>
          <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
            :page-size="pageSize" v-model:current-page="page" @current-change="load" />
        </el-card>
      </el-col>
    </el-row>

    <el-drawer v-model="drawer" title="合规报告详情" size="480px">
      <template v-if="current.id">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="风险等级"><run-status :status="current.risk_level" /></el-descriptions-item>
          <el-descriptions-item label="合规分">{{ current.score }}</el-descriptions-item>
        </el-descriptions>
        <h4>问题列表</h4>
        <el-empty v-if="!(current.issues || []).length" description="未发现问题" :image-size="60" />
        <el-alert v-for="(iss, i) in current.issues" :key="i" style="margin-bottom:8px"
          :type="iss.level === 'high' ? 'error' : 'warning'" :closable="false"
          :title="iss.detail" :description="`证据：${iss.evidence || '-'}`" />
        <h4>整改建议</h4>
        <ul style="color:#606266"><li v-for="(s, i) in current.suggestions" :key="i">{{ s }}</li></ul>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
import { can } from '../permissions'
import RunStatus from './RunStatus.vue'

const reports = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const checking = ref(false)
const drawer = ref(false)
const current = ref({})
const form = reactive({ target_type: 'product', ref_id: 1 })

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/compliance/reports', { params: { page_num: page.value, page_size: pageSize } })
    reports.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

async function check() {
  checking.value = true
  try {
    const { data } = await api.post('/compliance/check', form)
    ElMessage.success(`检测完成：风险 ${data.risk_level.toUpperCase()}，合规分 ${data.score}`)
    load()
  } finally { checking.value = false }
}

function show(row) { current.value = row; drawer.value = true }

onMounted(load)
</script>
