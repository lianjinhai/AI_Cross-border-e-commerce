<template>
  <div v-if="rows.length" class="blockers">
    <div class="blockers__head">
      <span class="blockers__title">阻断与补齐</span>
      <span class="muted">阻断 {{ rows.length }} 项<template v-if="stuck">，其中 {{ stuck }} 项当前无法在流程内完成</template></span>
    </div>
    <div v-for="(row, index) in rows" :key="`${row.code}-${row.stepCode}-${index}`" class="blockers__row">
      <div class="blockers__main">
        <el-tag size="small" type="danger" effect="light">{{ row.code }}</el-tag>
        <span class="blockers__msg">{{ row.message }}</span>
        <span v-if="row.stepCode" class="muted blockers__step">{{ row.stepCode }}</span>
      </div>
      <div class="blockers__act">
        <span v-if="row.repair.note" class="muted blockers__note">{{ row.repair.note }}</span>
        <el-button v-if="row.repair.canNavigate" size="small" type="primary" plain @click="go(row)">
          {{ row.repair.label }}
        </el-button>
        <el-tag v-else size="small" type="info" effect="plain">{{ row.repair.label }}</el-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { blockerViews, unrepairableCount } from '../../shared/launchRepair'

/**
 * 阻断清单（P0-4）：每条同时给出**原因**与**补齐入口**。
 *
 * 红线：`connected === false` 的补齐动作要显式写「未接入」，
 * 不做成看起来能完成、点了却无事发生的按钮。
 */
const props = defineProps({
  blockers: { type: Array, default: () => [] },
})

const router = useRouter()
const rows = computed(() => blockerViews(props.blockers))
const stuck = computed(() => unrepairableCount(props.blockers))

function go(row) {
  if (!row?.repair?.canNavigate) return
  router.push(row.repair.path)
}
</script>

<style scoped>
.blockers {
  border: 1px solid var(--el-color-danger-light-7, #f3c4c4);
  border-radius: 8px;
  padding: 12px 14px;
  background: var(--el-color-danger-light-9, #fef4f4);
}
.blockers__head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.blockers__title { font-weight: 600; font-size: 13px; }
.blockers__row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-top: 1px solid var(--el-color-danger-light-8, #f9dcdc);
}
.blockers__row:first-of-type { border-top: none; }
.blockers__main { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; min-width: 0; }
.blockers__msg { font-size: 13px; line-height: 1.5; }
.blockers__step { font-size: 12px; }
.blockers__act { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.blockers__note { font-size: 12px; max-width: 340px; text-align: right; line-height: 1.4; }
</style>
