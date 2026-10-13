<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    :width="width"
    :close-on-click-modal="false"
    @update:model-value="(v) => $emit('update:modelValue', v)"
    @closed="$emit('cancel')"
  >
    <span>{{ message }}</span>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button :type="level === 'danger' ? 'danger' : 'primary'" @click="$emit('confirm')">
        {{ confirmText }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
/**
 * 确认弹窗（V9 第 1 批，设计系统 §2 新增）：统一确认交互，含危险级。
 * level='danger' 时确认按钮为红色，用于不可逆/高危操作（如取消上线流程）。
 */
defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '确认操作' },
  message: { type: String, default: '' },
  level: { type: String, default: 'normal' },
  confirmText: { type: String, default: '确定' },
  width: { type: String, default: '420px' },
})

defineEmits(['update:modelValue', 'confirm', 'cancel'])
</script>
