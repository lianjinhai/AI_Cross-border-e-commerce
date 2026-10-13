<template>
  <div class="page">
    <PageHeader title="数据源与规则" subtitle="平台规则 / 市场数据源 · 版本 / 有效期 / 回滚" />

    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />

    <SectionState :code="code" @retry="loadRules" :error="error" empty-hint="暂无平台规则数据">
      <el-card shadow="never">
        <template #header>
          <div class="between">
            <span class="card-title">平台规则包</span>
            <el-button size="small" @click="goMaintenance">到维护页检查更新</el-button>
          </div>
        </template>
        <el-table :data="rules" size="small">
          <template v-for="col in ruleCols" :key="col.key">
            <el-table-column :prop="col.key" :label="col.label" :min-width="col.key === 'origin' ? 180 : 110">
              <template #default="{ row }">
                <template v-if="col.key === 'platform'">{{ platformLabel(row.platform) }}</template>
                <template v-else-if="col.key === 'last_error'">{{ ruleCellText(row, col.key) }}</template>
                <template v-else>{{ ruleCellText(row, col.key) }}</template>
              </template>
            </el-table-column>
          </template>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-tooltip :content="writePolicy.disable.reason" :disabled="writePolicy.disable.executable">
                <el-button size="small" :disabled="!writePolicy.disable.executable" @click="noop">停用</el-button>
              </el-tooltip>
            </template>
          </el-table-column>
          <template #empty>
            <EmptyState reason="NO_DATA" hint="暂无平台规则数据（可维护来源见「维护」页）" />
          </template>
        </el-table>
        <!-- §5.19：来源/适用范围/版本/有效期/最近拉取/错误/回滚；缺项显"—"或"未接入"，不编造 -->
        <el-alert
          type="info" :closable="false" show-icon class="mt12"
          title="规则写端点未接入"
          description="启用/停用等写操作在规则写端点接入前不可用；来源/版本由维护页同步，有效期/回滚待接入。"
        />
      </el-card>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 数据源与规则（蓝图 R1 包 3 · PC-04，§B.3 / §5.19）：/console/rules。
 *
 * admin 规则端点（Maintenance 现有"平台规则包"能力并入）：来源/版本读自
 * fetchPlatformRules（维护页同源），展示来源/适用范围/版本/有效期/最近拉取/错误/回滚。
 * 缺项（有效期/最近拉取/回滚）显"—"或"未接入"（shared/consoleRules.js 判定），不编造；
 * 规则写端点未接入 → 写按钮灰化，不触发 API。11 态全区块经 SectionState code。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchPlatformRules } from '../../api/domains/shops'
import { platformLabel } from '../../composables/tenantAdmin'
import {
  RULES_COLUMNS, ruleCellText, rulesWritePolicy,
} from '../../shared/consoleRules'
import { envTag } from '../../shared/dataLabels'

const envBanner = envTag()
const router = useRouter()

const rules = ref([])
const code = ref('LOADING')
const error = ref('')

const ruleCols = RULES_COLUMNS
/** 规则写端点未核 → 写动作恒不可执行（灰化）。 */
const writePolicy = {
  disable: rulesWritePolicy('disable', { rulesWriteAvailable: false }),
}

function noop() { /* 写操作未接入：无副作用，不触发 API。 */ }

function goMaintenance() {
  router.push('/console/maintenance')
}

function loadRules() {
  code.value = 'LOADING'
  error.value = ''
  fetchPlatformRules()
    .then((data) => {
      rules.value = data?.items || []
      code.value = rules.value.length ? 'ready' : 'EMPTY_NEW'
    })
    .catch((e) => {
      const detail = e?.response?.data?.detail
      error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
      code.value = 'ERROR'
    })
}

onMounted(loadRules)
</script>

<style scoped>
.card-title { font-weight: 600; }
.between { display: flex; justify-content: space-between; align-items: center; }
.mt12 { margin-top: 12px; }
</style>
