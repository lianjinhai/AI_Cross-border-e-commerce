<template>
  <div class="next-action-panel">
    <div v-if="primary && primaryPolicy.mode === 'enabled'" class="next-action-panel__primary">
      <el-button
        :type="primary.confirm ? 'primary' : 'primary'"
        :plain="!primary.confirm"
        size="small"
        @click="onSelect(primary)"
      >
        {{ primary.label }}
      </el-button>
    </div>
    <div v-else-if="primaryPolicy.mode === 'unavailable'" class="next-action-panel__unavailable">
      <el-button type="primary" size="small" disabled>暂不支持</el-button>
      <span class="next-action-panel__reason">{{ primaryPolicy.reason }}</span>
    </div>
    <div v-else-if="primaryPolicy.mode === 'readOnly'" class="next-action-panel__readonly">
      <el-tag type="info" size="small">只读</el-tag>
      <span class="next-action-panel__reason">{{ primaryPolicy.reason }}</span>
    </div>

    <div v-if="secondary.length" class="next-action-panel__secondary">
      <el-button
        v-for="item in secondary"
        :key="item.code"
        size="small"
        @click="onSelect(item)"
      >
        {{ item.label }}
      </el-button>
    </div>

    <div v-if="readOnly && !primary" class="next-action-panel__readonly-note">当前角色无可用动作</div>
    <slot name="reason" />
  </div>
</template>

<script setup>
/**
 * 下一步动作面板（蓝图 §6.4，包 1 P0 全新组件）。
 *
 * 规则：恰一个 primary；无权限=不渲染并显只读解释；业务不可执行=reason+补救入口；
 * 技术未接通=灰化+"暂不支持"；confirm=true 走 AsyncActionDialog。
 * 纯函数源：shared/nextAction.js（pickPrimaryAction / renderPolicy / splitActions）。
 */
import { computed } from 'vue'
import { pickPrimaryAction, renderPolicy, splitActions } from '../shared/nextAction'

const props = defineProps({
  /** 可用动作列表 [{code,label,kind:'primary'|'secondary',reason?,confirm?,apiGap?}] */
  availableActions: { type: Array, default: () => [] },
  /** 对象身份 {type,id,store}。 */
  object: { type: Object, default: () => ({}) },
  /** 只读模式（无权限）。 */
  readOnly: { type: Boolean, default: false },
  /** 是否具备动作权限。 */
  permission: { type: Boolean, default: true },
})

const emit = defineEmits(['select', 'confirm'])

const { primary, secondary } = computed(() => splitActions(props.availableActions))

const primaryPolicy = computed(() => {
  if (!primary.value) return { mode: 'readOnly', reason: props.availableActions.length ? '' : '无可用动作' }
  return renderPolicy(primary.value, props.permission && !props.readOnly)
})

function onSelect(action) {
  if (!action) return
  const policy = renderPolicy(action, props.permission && !props.readOnly)
  if (policy.mode !== 'enabled') return
  if (action.confirm) emit('confirm', action)
  else emit('select', action)
}
</script>

<style scoped>
.next-action-panel__primary,
.next-action-panel__unavailable,
.next-action-panel__readonly {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.next-action-panel__secondary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.next-action-panel__reason {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}
.next-action-panel__readonly-note {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>
