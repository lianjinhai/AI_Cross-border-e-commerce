import { ref } from 'vue'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'

export function usePublishActionQueue(onExecuted = () => {}) {
  const items = ref([]), loading = ref(false), busy = ref(false)
  async function load() {
    loading.value = true
    try {
      const responses = await Promise.all(['PENDING_APPROVAL', 'APPROVED'].map(status =>
        api.get('/actions', { params: { action_type: 'PUBLISH_LISTING', status } })))
      items.value = responses.flatMap(response => response.data.items)
    } finally { loading.value = false }
  }
  async function decide(row, approve) {
    if (busy.value || row.status !== 'PENDING_APPROVAL') return
    try {
      const { value } = await ElMessageBox.prompt('填写审批依据；请核对 Listing 内容、规则版本及目标店铺',
        approve ? '批准发布提案' : '拒绝发布提案', { inputValidator: value => !!value?.trim() || '审批意见不能为空' })
      busy.value = true
      await api.post(`/actions/${row.id}/${approve ? 'approve' : 'reject'}`, { note: value.trim() })
      await load()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') throw error
    } finally { busy.value = false }
  }
  async function execute(row) {
    if (busy.value || row.status !== 'APPROVED') return
    try {
      await ElMessageBox.confirm(`执行 Action #${row.id}，将 Listing #${row.target_id} 上架到审批目标。`, '确认执行')
      busy.value = true
      const { data } = await api.post(`/actions/${row.id}/execute`)
      if (data.status === 'SUCCESS') {
        ElMessage.success('发布已执行；如来自工作流，请恢复该流程')
        onExecuted()
      } else ElMessage.error(data.outcome?.error || '发布执行失败，请核对现场并重新提案')
      await load()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') throw error
    } finally { busy.value = false }
  }
  return { items, loading, busy, load, decide, execute }
}
