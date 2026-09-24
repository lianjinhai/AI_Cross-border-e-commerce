<template>
  <div>
    <div class="assistant-fab" @click="open = !open" title="AI 经营助手">🤖</div>
    <el-drawer v-model="open" title="🤖 AI 经营助手" size="420px" :append-to-body="true">
      <div class="chat-list" ref="listRef">
        <div v-for="(m, i) in messages" :key="i" class="chat-msg" :class="m.role">
          <div class="chat-bubble">
            <div style="white-space:pre-wrap">{{ m.content }}</div>
            <div v-if="m.actions?.length" style="margin-top:6px">
              <el-tag v-for="a in m.actions" :key="a" size="small" type="warning" style="margin-right:4px">
                {{ a }}
              </el-tag>
            </div>
          </div>
        </div>
        <div v-if="loading" class="chat-msg ai"><div class="chat-bubble">思考中…</div></div>
      </div>
      <div class="suggest" v-if="messages.length <= 1">
        <el-tag v-for="s in suggestions" :key="s" size="small" class="mr8" style="cursor:pointer"
          @click="send(s)">{{ s }}</el-tag>
      </div>
      <div style="display:flex;gap:8px;margin-top:8px">
        <el-input v-model="text" placeholder="对我说：帮我选品 / 重新定价 / 经营情况" @keyup.enter="send()" />
        <el-button type="primary" :disabled="!text.trim() || loading" @click="send()">发送</el-button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import api from '../api'

const open = ref(false)
const text = ref('')
const loading = ref(false)
const listRef = ref(null)
const messages = ref([
  { role: 'ai', content: '您好！我是您的 AI 经营助手 🤖\n可以直接对我说：\n· 「帮我选品」— 输出机会商品 Top3\n· 「看看市场趋势」— 刷新趋势解读\n· 「有什么风险」— 跑一轮经营巡检（断货/亏损/退款/汇率等九项）\n· 「重新定价」— 全店动态定价\n· 「经营情况」— 近30天概况' },
])
const suggestions = ['帮我选品', '看看市场趋势', '有什么风险', '重新定价', '经营情况']

async function send(preset) {
  const msg = (preset || text.value).trim()
  if (!msg || loading.value) return
  text.value = ''
  messages.value.push({ role: 'user', content: msg })
  loading.value = true
  await nextTick()
  scrollBottom()
  try {
    const { data } = await api.post('/ai/chat', { message: msg })
    messages.value.push({ role: 'ai', content: data.reply, actions: data.actions })
  } finally {
    loading.value = false
    await nextTick()
    scrollBottom()
  }
}

function scrollBottom() {
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
}
</script>

<style scoped>
.assistant-fab { position: fixed; right: 28px; bottom: 32px; width: 52px; height: 52px;
  border-radius: 50%; background: #409EFF; color: #fff; display: flex; align-items: center;
  justify-content: center; font-size: 26px; cursor: pointer; box-shadow: 0 4px 16px rgba(64,158,255,.45);
  z-index: 2000; transition: transform .2s; }
.assistant-fab:hover { transform: scale(1.08); }
.chat-list { height: calc(100% - 90px); overflow: auto; padding: 4px; }
.chat-msg { display: flex; margin-bottom: 10px; }
.chat-msg.user { justify-content: flex-end; }
.chat-bubble { max-width: 85%; padding: 8px 12px; border-radius: 10px; background: #f4f4f5; font-size: 13px; line-height: 1.6; }
.chat-msg.user .chat-bubble { background: #d9ecff; }
.suggest { margin-top: 8px; }
</style>
