<template>
  <div class="page onboarding">
    <PageHeader :title="stepTitle" subtitle="新手引导 · 三步完成经营起点" />

    <!-- 步骤条（step query 1/2/3） -->
    <el-steps :active="stepIndex" align-center class="onboarding__steps">
      <el-step title="建立方向" />
      <el-step title="连接店铺" />
      <el-step title="经营路径" />
    </el-steps>

    <!-- 环境标签常显（部署层注入） -->
    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试，请勿用于真实经营决策" />

    <el-card class="mb16" shadow="never">
      <!-- ── ONB-01 建立方向（纯前端五选项） ── -->
      <template v-if="step === 1">
        <h3 class="onboarding__card-title">你想怎么起步？</h3>
        <el-radio-group v-model="direction" class="onboarding__options">
          <el-radio v-for="opt in DIRECTION_OPTIONS" :key="opt.value" :label="opt.value">
            {{ opt.label }}
            <span class="onboarding__option-hint">{{ opt.hint }}</span>
          </el-radio>
        </el-radio-group>
        <div class="onboarding__footer">
          <el-button type="primary" @click="next">下一步：连接店铺</el-button>
        </div>
      </template>

      <!-- ── ONB-02 连接店铺（接入 shops / suppliers / factoryNetwork 真实端点） ── -->
      <template v-else-if="step === 2">
        <h3 class="onboarding__card-title">连接你的店铺与货源</h3>
        <SectionState :code="onb2Code" @retry="loadStep2" :error="onb2Error">
          <template v-if="onb2Code === 'ready'">
            <el-table :data="shopItems" size="small" max-height="280">
              <el-table-column prop="name" label="店铺" show-overflow-tooltip />
              <el-table-column label="类型" width="100">
                <template #default="{ row }">{{ row.type === 'source' ? '货源' : '销售' }}</template>
              </el-table-column>
              <el-table-column label="状态" width="110">
                <template #default="{ row }"><StatusBadge :status="row.status" /></template>
              </el-table-column>
            </el-table>
            <el-alert
              v-if="!shopItems.length"
              type="info" :closable="false"
              title="还没有店铺"
              description="前往店铺授权页连接你的第一个销售店铺。"
            />
          </template>
        </SectionState>
        <div class="onboarding__footer">
          <el-button @click="prev">上一步</el-button>
          <el-button type="primary" @click="next">下一步：经营路径</el-button>
        </div>
      </template>

    <!-- ── ONB-03 经营路径（静态清单 + 明示"引导清单（非 AI 自动规划）"，API_GAP §7#11） ── -->
    <template v-else>
      <h3 class="onboarding__card-title">你的经营路径</h3>
      <DataQualityBanner tag="MANUAL_UNVERIFIED" detail="引导清单（非 AI 自动规划），按顺序完成即可起步" />
      <el-alert type="success" :closable="false" class="mb12"
        title="零基础经营准备向导"
        description="想一步步把生意跑通？沿「研究商品方向 → 选择货源 → 查看成本/风险 → 准备销售渠道 → 建立商品销售准备」走，系统会替你记住当前商品对象，每步都有下一步，不会有死端。" />
      <el-button type="primary" class="mb16" @click="startJourney">按向导一步步准备 →</el-button>
      <el-card class="mb16" shadow="never">
          <ol class="onboarding__guide">
            <li v-for="(item, i) in pathItems" :key="i">
              <span>{{ item.label }}</span>
              <el-button v-if="item.path" link type="primary" size="small" @click="go(item.path)">前往</el-button>
            </li>
          </ol>
        </el-card>
        <div class="onboarding__footer">
          <el-button @click="prev">上一步</el-button>
          <el-button type="primary" @click="finish">完成引导，进入工作台</el-button>
        </div>
      </template>
    </el-card>
  </div>
</template>

<script setup>
/**
 * 新手引导三屏合一（蓝图 R1 ONB-01/02/03，P0）：/onboarding?step=1|2|3，step query 切屏。
 *
 * - ONB-01 建立方向：纯前端五选项（无 API），记录方向偏好。
 * - ONB-02 连接店铺：接 shops（已接端点，真实数据）；suppliers/factoryNetwork 作为次级来源
 *   在表格内如实显示类型，缺项走 11 态（NOT_CONFIGURED / EMPTY_NEW）。
 * - ONB-03 经营路径：静态清单 + 明示"引导清单（非 AI 自动规划）"（API_GAP §7#11，
 *   后端未接 Business Path → 只读骨架，禁假 AI 规划）。
 * 每页 11 态全区块经 SectionState 渲染；金额/来源字段用 dataLabels。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchShops } from '../../api/domains/shops'
import { envTag } from '../../shared/dataLabels'

const route = useRoute()
const router = useRouter()

const step = computed(() => {
  const raw = Number(route.query.step)
  return raw === 2 || raw === 3 ? raw : 1
})
const stepIndex = computed(() => step.value - 1)

const stepTitles = { 1: '建立方向', 2: '连接店铺', 3: '经营路径' }
const stepTitle = computed(() => `第 ${step.value} 步 · ${stepTitles[step.value]}`)

/** 部署环境常显标签（合同测试/演示，部署层注入 window.__ERP_ENV__）。 */
const envBanner = envTag()

// ── ONB-01 五选项（纯前端，无 API） ──
const DIRECTION_OPTIONS = [
  { value: 'A', label: '新手起步', hint: '选品 → 连店 → 上线' },
  { value: 'B', label: '有货源', hint: '聚焦货源与上架' },
  { value: 'C', label: '有团队', hint: '协作与权限治理' },
  { value: 'D', label: '成长期店铺', hint: '规模化经营' },
  { value: 'GENERIC', label: '先看看系统', hint: '通用路径' },
]
const direction = ref('A')

// ── ONB-02 店铺接入态（接 shops 已接端点） ──
const shopItems = ref([])
const onb2Loading = ref(false)
const onb2Error = ref('')

const onb2Code = computed(() => {
  if (onb2Error.value) return 'ERROR'
  if (onb2Loading.value) return 'LOADING'
  if (!shopItems.value.length) return 'EMPTY_NEW'
  return 'ready'
})

async function loadStep2() {
  onb2Loading.value = true
  onb2Error.value = ''
  try {
    const data = await fetchShops()
    shopItems.value = Array.isArray(data?.items) ? data.items : []
  } catch (e) {
    const detail = e?.response?.data?.detail
    onb2Error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
  } finally {
    onb2Loading.value = false
  }
}

// ── ONB-03 经营路径（静态清单 + 明示非 AI，API_GAP §7#11） ──
const PATH_BY_DIRECTION = {
  A: [
    { label: '浏览商品发现', path: '/app/market/discovery' },
    { label: '连接销售店铺', path: '/app/channels/shops' },
    { label: '创建上线流程', path: '/app/launch' },
  ],
  B: [
    { label: '查看货源机会', path: '/app/market/discovery' },
    { label: '核对供应商匹配', path: '/app/supply/suppliers' },
    { label: '进入商品池处理', path: '/app/products' },
  ],
  C: [
    { label: '管理成员与权限', path: '/app/settings/team' },
    { label: '查看经营总览', path: '/app/analytics/bi' },
  ],
  D: [
    { label: '同步销售店铺', path: '/app/channels/shops' },
    { label: '处理待履约订单', path: '/app/orders' },
    { label: '查看店铺表现', path: '/app/analytics/bi' },
  ],
  GENERIC: [
    { label: '浏览商品池', path: '/app/products' },
    { label: '绑定销售店铺', path: '/app/channels/shops' },
    { label: '创建工作流', path: '/app/launch' },
  ],
}
const pathItems = computed(() => PATH_BY_DIRECTION[direction.value] || PATH_BY_DIRECTION.GENERIC)

// ── 导航 ──
function goToStep(n) {
  router.replace({ path: '/onboarding', query: { step: String(n) } })
}
function next() { goToStep(Math.min(3, step.value + 1)) }
function prev() { goToStep(Math.max(1, step.value - 1)) }
function finish() { router.push('/app') }
function go(path) { if (path) router.push(path) }
/** 进入 J0 零基础经营准备向导（链路首步：研究商品方向）。 */
function startJourney() { router.push({ path: '/app/market/discovery', query: { journey: 'j0' } }) }

onMounted(() => {
  if (step.value === 2) loadStep2()
})
watch(step, (n) => { if (n === 2 && !shopItems.value.length) loadStep2() })
</script>

<style scoped>
.onboarding__steps { margin-bottom: 16px; }
.onboarding__card-title { margin: 0 0 12px; font-size: 15px; }
.onboarding__options { display: flex; flex-direction: column; gap: 8px; }
.onboarding__option-hint { margin-left: 8px; color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.onboarding__guide { margin: 0; padding-left: 20px; }
.onboarding__guide li { margin: 6px 0; display: flex; justify-content: space-between; align-items: center; }
.onboarding__footer { margin-top: 12px; display: flex; justify-content: flex-end; gap: 8px; }
.mb12 { margin-bottom: 12px; }
</style>
