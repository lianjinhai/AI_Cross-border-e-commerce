<template>
  <el-dialog :model-value="modelValue" :title="`执行动作：${actionName}`" width="520px"
    @update:model-value="onVisible">
    <el-alert v-if="conflictMessage" type="warning" show-icon :closable="false" class="mb12" :title="conflictMessage" />
    <el-alert v-if="uncertain" type="info" show-icon :closable="false" class="mb12"
      title="结果待核查：外部调用结果未确认，请先刷新状态再决定，避免重复提交" />
    <el-alert v-if="doubleConfirm && !conflictMessage" type="warning" show-icon :closable="false" class="mb12"
      title="高风险动作：请核对影响范围后再提交" />

    <el-form label-width="96px" @submit.prevent>
      <el-form-item v-if="priceRequired" label="申报价" required>
        <el-input-number v-model="form.price" :min="0.01" :precision="2" :step="1" controls-position="right" />
      </el-form-item>
      <el-form-item v-if="priceRequired" label="币种" required>
        <el-select v-model="form.currency" placeholder="必须选择" style="width: 160px">
          <el-option v-for="code in CURRENCIES" :key="code" :label="code" :value="code" />
        </el-select>
        <span class="hint">金额离开币种就是错数，因此不设默认币种</span>
      </el-form-item>
      <el-form-item v-if="materialRequired" label="材料引用">
        <el-input v-model="form.material_ref" placeholder="平台后台核验材料链接或编号" />
      </el-form-item>
      <el-form-item label="备注" :required="noteRequired">
        <el-input v-model="form.note" type="textarea" :rows="3" placeholder="填写操作依据（审计留痕）" />
      </el-form-item>
      <el-form-item v-if="doubleConfirm" label="二次确认">
        <el-checkbox v-model="form.confirmed">我已确认这是高风险操作，并知晓其影响</el-checkbox>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!submittable" @click="submit">执行</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from '../../shared/ui'
import {
  actionPayload, errorEnvelope, executeAction, isUncertainError, needsDoubleConfirm, requiresMaterial,
  requiresNote, requiresPrice,
} from '../../composables/launchCenter'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  runId: { type: Number, default: 0 },
  action: { type: Object, default: () => ({}) },
  stepCode: { type: String, default: '' },
  revision: { type: Number, default: 0 },
})
const emit = defineEmits(['update:modelValue', 'executed', 'conflict'])

const form = reactive({ note: '', material_ref: '', confirmed: false, price: null, currency: '' })
/** 常用币种；不预选任何一个，避免替用户默认成 USD。 */
const CURRENCIES = ['USD', 'CNY', 'EUR', 'GBP', 'JPY']
const submitting = ref(false)
const uncertain = ref(false)
const conflictMessage = ref('')

const actionName = computed(() => props.action?.action || '')
const doubleConfirm = computed(() => needsDoubleConfirm(actionName.value, props.action || {}))
const materialRequired = computed(() => requiresMaterial(actionName.value))
const priceRequired = computed(() => requiresPrice(actionName.value))
const noteRequired = computed(() => requiresNote(actionName.value))
const submittable = computed(() => !submitting.value && !uncertain.value
  && (!doubleConfirm.value || form.confirmed)
  && (!materialRequired.value || form.material_ref.trim().length > 0)
  && (!priceRequired.value || (Number(form.price) > 0 && /^[A-Z]{3}$/.test(form.currency || '')))
  && (!noteRequired.value || form.note.trim().length > 0))

watch(() => props.modelValue, (open) => { if (open) reset() })

function reset() {
  form.note = ''
  form.material_ref = ''
  form.confirmed = false
  form.price = null
  form.currency = ''
  submitting.value = false
  uncertain.value = false
  conflictMessage.value = ''
}

function close() {
  emit('update:modelValue', false)
}

function onVisible(visible) {
  if (!visible) close()
}

async function submit() {
  if (!submittable.value) return
  submitting.value = true
  conflictMessage.value = ''
  try {
    const launch = await executeAction(props.runId, actionName.value, actionPayload(actionName.value, form),
      { expectedRevision: props.revision, stepCode: props.stepCode })
    ElMessage.success('动作已执行')
    emit('executed', launch)
    close()
  } catch (err) {
    const envelope = errorEnvelope(err)
    if (envelope.code === 'REVISION_CONFLICT') {
      // AC-15.5：保留用户未提交输入；刷新状态；高风险动作需**重新**确认（不自动再次确认）。
      form.confirmed = false
      conflictMessage.value = `流程已更新（当前版本 ${envelope.current_revision}）：${envelope.message}。请核对后重新确认。`
      emit('conflict', envelope)
    } else if (isUncertainError(err)) {
      uncertain.value = true  // AC-15.6：不诱导连续重发
    } else {
      ElMessage.error(envelope.message)
    }
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.hint { margin-left: 8px; color: var(--color-text-secondary); font-size: var(--font-size-xs); }
</style>
