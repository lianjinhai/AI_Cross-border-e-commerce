<template>
  <el-card class="mb16">
    <template #header>
      <span>发布审批队列</span>
      <el-button text @click="load">刷新</el-button>
    </template>
    <el-alert title="批准不会立即上架；请核对目标店铺后单独执行。工作流需在执行成功后恢复。"
      type="info" :closable="false" class="mb16" />
    <el-table :data="items" v-loading="loading" size="small">
      <el-table-column prop="id" label="Action" width="85" />
      <el-table-column prop="target_id" label="Listing" width="85" />
      <el-table-column label="目标" min-width="120">
        <template #default="{ row }">{{ row.evidence?.shop_id ? `店铺 #${row.evidence.shop_id}` : '本地模拟' }}</template>
      </el-table-column>
      <el-table-column prop="reason" label="提案依据" min-width="220" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">{{ row.status === 'APPROVED' ? '已批准待执行' : '等待审批' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <template v-if="row.status === 'PENDING_APPROVAL'">
            <el-button size="small" :disabled="busy" @click="decide(row, true)">批准</el-button>
            <el-button size="small" :disabled="busy" type="danger" @click="decide(row, false)">拒绝</el-button>
          </template>
          <el-button v-else size="small" :disabled="busy" type="primary" @click="execute(row)">执行上架</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { onMounted } from 'vue'
import { usePublishActionQueue } from '../composables/publishActionQueue'

const emit = defineEmits(['executed'])
const { items, loading, busy, load, decide, execute } = usePublishActionQueue(() => emit('executed'))
defineExpose({ load })
onMounted(load)
</script>
