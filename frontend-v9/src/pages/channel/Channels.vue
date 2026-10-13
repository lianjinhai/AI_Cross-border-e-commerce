<template>
  <div class="page">
    <PageHeader
      title="渠道推荐"
      subtitle="平台能力墙 · 目标市场 / 真实能力 / 验证等级 / 接入前提"
    >
      <template #actions>
        <el-button @click="router.push('/app/channels/shops')">店铺管理</el-button>
      </template>
    </PageHeader>

    <DataQualityBanner
      tag="API_UNVERIFIED"
      detail="平台能力目录为静态快照（Adapter Registry 读端点未核）：验证等级一律「协议未验证」，仅 shops 端点证实的授权状态可显示。不会显示「已连接官方实时数据」。"
    />

    <el-row :gutter="16" class="mb16">
      <el-col v-for="card in cards" :key="card.platform" :span="8">
        <el-card shadow="never" class="channel-card">
          <div class="channel-card__head">
            <span class="channel-card__title">{{ card.label }}</span>
            <BusinessStatus
              :standard="card.restricted ? 'BLOCKED' : 'PENDING'"
              :raw="card.level"
              :note="`${card.levelLabel}：Adapter Registry 读端点未核（§7#8），能力字段未验收`"
            />
          </div>

          <div class="channel-card__meta">
            <div class="channel-card__row">
              <span class="channel-card__label">目标市场</span>
              <span>{{ card.markets.length ? card.markets.join('、') : '—' }}</span>
            </div>
            <div class="channel-card__row">
              <span class="channel-card__label">验证等级</span>
              <span>{{ card.levelLabel }}</span>
            </div>
          </div>

          <div class="channel-card__caps">
            <div v-for="cap in card.capabilities" :key="cap.code" class="channel-card__cap">
              <span>{{ cap.label }}</span>
              <el-tag
                size="small" effect="plain"
                :type="cap.verified ? 'info' : 'warning'"
              >{{ cap.verified ? '协议已验证' : '协议未验证' }}</el-tag>
            </div>
          </div>

          <div v-if="card.prerequisites.length" class="channel-card__prereq">
            <div class="channel-card__label">接入前提</div>
            <ul>
              <li v-for="(p, i) in card.prerequisites" :key="i">{{ p }}</li>
            </ul>
          </div>

          <div class="channel-card__foot">
            <el-button v-if="!card.restricted" size="small" type="primary" @click="goShops">
              开始连接
            </el-button>
            <el-button v-else size="small" @click="viewPrerequisites(card)">
              查看接入前提与材料
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 受限渠道接入前提抽屉（只读；不出现"连接"按钮） -->
    <el-drawer v-model="prereqDrawer" :title="prereqCard ? `${prereqCard.label} · 接入前提与材料` : '接入前提'" size="480px">
      <template v-if="prereqCard">
        <el-alert
          type="warning" :closable="false" class="mb12"
          title="受限渠道：当前仅提供只读前提与材料清单，连接入口不可用"
        />
        <el-table :data="prereqCard.capabilities" size="small">
          <el-table-column prop="label" label="能力" />
          <el-table-column label="验证" width="120">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="row.verified ? 'info' : 'warning'">
                {{ row.verified ? '协议已验证' : '协议未验证' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <h4 class="drawer-h">前提清单</h4>
        <ul class="prereq-list">
          <li v-for="(p, i) in prereqCard.prerequisites" :key="i">{{ p }}</li>
        </ul>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
/**
 * 渠道推荐（蓝图 R1 CH-01，包 2）：/app/channels。
 *
 * 数据源：Adapter Registry / Platform Capabilities 未核（§7#8）→
 * 静态平台目录（api/domains/platformCapabilities.js）+ shops 端点证实的授权状态；
 * 验证等级一律"协议未验收/协议未验证"，禁止"已连接官方实时数据"误导。
 * 11 态：所有区块经 SectionState（本页为内容态；无数据异常时不渲染自写空态）。
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import BusinessStatus from '../../components/BusinessStatus.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { allPlatformCards } from '../../api/domains/platformCapabilities'

const router = useRouter()
const cards = allPlatformCards()

const prereqDrawer = ref(false)
const prereqCard = ref(null)

function goShops() {
  router.push('/app/channels/shops')
}

function viewPrerequisites(card) {
  prereqCard.value = card
  prereqDrawer.value = true
}
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.mb12 { margin-bottom: 12px; }
.channel-card { margin-bottom: 16px; }
.channel-card__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.channel-card__title { font-size: 15px; font-weight: 600; }
.channel-card__meta, .channel-card__caps {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}
.channel-card__row { display: flex; gap: 8px; font-size: var(--font-size-sm); }
.channel-card__label { color: var(--color-text-secondary); min-width: 64px; }
.channel-card__cap {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--font-size-sm);
}
.channel-card__prereq { margin-bottom: 8px; font-size: var(--font-size-sm); }
.channel-card__prereq ul { margin: 4px 0 0; padding-left: 18px; color: var(--color-text-regular); }
.channel-card__foot { display: flex; justify-content: flex-end; }
.drawer-h { margin: 12px 0 6px; }
.prereq-list { padding-left: 18px; font-size: var(--font-size-sm); }
</style>
