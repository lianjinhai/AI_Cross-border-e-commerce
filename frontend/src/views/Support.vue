<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card class="mb16">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>会话列表</span>
              <el-button v-if="can('order:write')" size="small" type="primary" @click="newDialog = true">新建会话</el-button>
            </div>
          </template>
          <div v-loading="loading">
            <div v-for="c in conversations" :key="c.id" class="conv-item" :class="{ active: current.id === c.id }"
              @click="open(c)">
              <div style="display:flex;justify-content:space-between">
                <b>{{ c.buyer_name }}</b>
                <el-tag size="small">{{ c.platform }}</el-tag>
              </div>
              <div style="color:#909399;font-size:12px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                {{ c.last_message || '（无消息）' }}
              </div>
              <div style="color:#c0c4cc;font-size:11px;margin-top:2px">{{ c.last_message_at }}</div>
            </div>
            <el-empty v-if="!conversations.length" description="暂无会话" :image-size="60" />
          </div>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>{{ current.buyer_name ? `${current.buyer_name}（${current.platform}）` : '消息' }}</span>
              <div>
                <el-button v-if="can('order:write')" size="small" type="success" :disabled="!current.id" :loading="aiLoading" @click="autoReply">
                  AI 自动回复
                </el-button>
                <el-button size="small" :disabled="!current.id" @click="closeConv">关闭会话</el-button>
              </div>
            </div>
          </template>
          <div class="msg-list" ref="msgList">
            <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
              <div class="msg-bubble">
                {{ m.content }}
                <div class="msg-meta">
                  <el-tag v-if="m.intent && m.intent !== 'other'" size="small" type="info">{{ m.intent }}</el-tag>
                  <span v-if="m.auto"> · AI自动</span> · {{ m.created_at }}
                </div>
              </div>
            </div>
            <el-empty v-if="!messages.length && current.id" description="暂无消息" :image-size="60" />
            <el-empty v-if="!current.id" description="左侧选择一个会话" :image-size="80" />
          </div>
          <div style="display:flex;gap:8px;margin-top:12px">
            <el-input v-model="replyText" placeholder="输入回复内容…" :disabled="!current.id" @keyup.enter="send" />
            <el-button type="primary" :disabled="!current.id || !replyText" @click="send">发送</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="newDialog" title="新建客服会话" width="480px">
      <el-form label-width="90px">
        <el-form-item label="平台">
          <el-select v-model="form.platform">
            <el-option v-for="p in ['tiktok','shopee','amazon','ebay','walmart','lazada','aliexpress','temu','shopify','mercadolibre','shein']" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="买家名"><el-input v-model="form.buyer_name" /></el-form-item>
        <el-form-item label="首条消息"><el-input v-model="form.content" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newDialog = false">取消</el-button>
        <el-button type="primary" @click="createConv">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
import { can } from '../permissions'

const conversations = ref([])
const messages = ref([])
const current = ref({})
const loading = ref(false)
const aiLoading = ref(false)
const replyText = ref('')
const msgList = ref(null)
const newDialog = ref(false)
const form = reactive({ platform: 'shopee', buyer_name: '', content: '' })

async function loadConv() {
  loading.value = true
  try {
    const { data } = await api.get('/support/conversations', { params: { page_size: 30 } })
    conversations.value = data.items
  } finally { loading.value = false }
}

async function open(c) {
  current.value = c
  const { data } = await api.get(`/support/conversations/${c.id}`)
  messages.value = data.messages
  await nextTick()
  if (msgList.value) msgList.value.scrollTop = msgList.value.scrollHeight
}

async function send() {
  if (!replyText.value.trim()) return
  await api.post(`/support/conversations/${current.value.id}/reply`, { content: replyText.value })
  replyText.value = ''
  open(current.value)
  loadConv()
}

async function autoReply() {
  aiLoading.value = true
  try {
    const { data } = await api.post(`/support/conversations/${current.value.id}/auto_reply`)
    ElMessage.success(`AI 已按意图「${data.intent}」回复`)
    open(current.value)
  } finally { aiLoading.value = false }
}

async function closeConv() {
  await api.post(`/support/conversations/${current.value.id}/close`)
  ElMessage.success('会话已关闭')
  loadConv()
}

async function createConv() {
  await api.post('/support/conversations', form)
  ElMessage.success('会话已创建')
  newDialog.value = false
  form.buyer_name = ''
  form.content = ''
  loadConv()
}

onMounted(loadConv)
</script>

<style scoped>
.conv-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 6px; border: 1px solid transparent; }
.conv-item:hover { background: #f5f7fa; }
.conv-item.active { background: #ecf5ff; border-color: #d9ecff; }
.msg-list { height: 420px; overflow: auto; padding: 8px; }
.msg { display: flex; margin-bottom: 10px; }
.msg.buyer { justify-content: flex-start; }
.msg.agent, .msg.operator { justify-content: flex-end; }
.msg-bubble { max-width: 70%; padding: 8px 12px; border-radius: 10px; background: #f4f4f5; font-size: 13px; }
.msg.agent .msg-bubble, .msg.operator .msg-bubble { background: #d9ecff; }
.msg-meta { color: #a8abb2; font-size: 11px; margin-top: 4px; }
</style>
