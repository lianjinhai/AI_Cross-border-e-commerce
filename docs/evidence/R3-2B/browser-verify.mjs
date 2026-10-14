// R3-2B 真实浏览器验收脚本（CDP 直连系统 Chrome；仅依赖 Node 22 内置 WebSocket）
// 验证：工作台四层首屏 + 计数条 + AI 活动流展开；待办统一列表 + 视图切换 + 筛选写 URL + 返回恢复。
// 前提：5174 dev（V9）+ 8000 后端已启动；截图输出到本目录。
// 用法：node browser-verify.mjs
//
// 排坑：Chrome 必须 --no-proxy-server；dev 绑定 [::1]，导航用 http://localhost:5174。

import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT_DIR = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-2B'
fs.mkdirSync(OUT_DIR, { recursive: true })
const LOGIN = 'http://localhost:5174/console/login'

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9335', '--user-data-dir=C:/temp/r32b-chrome-profile',
  '--no-first-run', '--no-proxy-server', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 15000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9335/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
      if (created.ok) return (await created.json()).webSocketDebuggerUrl
    } catch {}
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error('Chrome CDP 未就绪')
}

function connectCdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl)
    let seq = 0
    const pending = new Map()
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg.result, msg.error)
        pending.delete(msg.id)
      }
    }
    const client = {
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const id = ++seq
          pending.set(id, (result, error) => (error ? rej(new Error(JSON.stringify(error))) : res(result)))
          ws.send(JSON.stringify({ id, method, params }))
        })
      },
      async evaluate(expression) {
        const r = await client.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
        if (r.exceptionDetails) throw new Error('eval error: ' + JSON.stringify(r.exceptionDetails.exception?.description))
        return r.result?.value
      },
      async navigate(url) {
        await client.send('Page.navigate', { url })
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 250))
          let href = null
          try { href = await client.evaluate('location.href') } catch {}
          if (href && href.startsWith(url.split('#')[0].replace(/\/$/, ''))) break
        }
        await new Promise((r) => setTimeout(r, 1500))
      },
      async screenshot(file) {
        const r = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
        fs.writeFileSync(file, Buffer.from(r.data, 'base64'))
        console.log(`[shot] ${file}`)
      },
    }
    ws.onopen = () => resolve(client)
    ws.onerror = () => reject(new Error('ws error'))
  })
}

const loginRes = await fetch('http://127.0.0.1:8000/api/auth/login', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'admin', password: 'admin123' }),
}).then((r) => r.json())
const token = loginRes.token
if (!token) { console.error('登录失败：', JSON.stringify(loginRes)); process.exit(1) }

const c = await connectCdp(await getWsUrl(LOGIN))
await c.send('Runtime.enable')
await c.send('Page.enable')
let startHref = ''
try { startHref = String(await c.evaluate('location.href')) } catch { startHref = 'about:blank' }
if (startHref.startsWith('about')) await c.navigate(LOGIN)
await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(token)}); 'ok'`)

// ── 1. 工作台首屏（四层 + 计数条） ──
await c.navigate('http://localhost:5174/app')
const home = await c.evaluate(`(() => {
  const t = document.body.innerText
  const counters = [...document.querySelectorAll('.counter')].map((el) => ({
    label: el.querySelector('.counter__label')?.textContent.trim(),
    num: el.querySelector('.counter__num')?.textContent.trim(),
  }))
  return {
    url: location.href,
    hasLayer1: t.includes('今天最值得完成的一件事'),
    hasLayer2: t.includes('还需要处理'),
    hasLayer3: t.includes('当前经营状况'),
    hasLayer4: t.includes('AI 执行历史') && t.includes('完整经营数据'),
    counters,
    hasRecommended: t.includes('唯一推荐入口'),
    entryTag: document.querySelector('.el-tag')?.textContent.trim(),
  }
})()`)
console.log('[E-home]', JSON.stringify(home))
await c.screenshot(`${OUT_DIR}/01-workspace-home.png`)

// AI 活动流展开 + BI 明细展开
const expand = await c.evaluate(`(() => {
  const heads = [...document.querySelectorAll('.el-collapse-item__header')]
  heads.forEach((h) => h.click())
  return { collapseCount: heads.length }
})()`)
await new Promise((r) => setTimeout(r, 1200))
const expanded = await c.evaluate(`(() => {
  const t = document.body.innerText
  return { hasAiTable: t.includes('AI 运行') || t.includes('近 24 小时没有已完成的 AI 运行'),
    hasBi: t.includes('热销商品') || t.includes('经营明细需财务读权限') }
})()`)
console.log('[E-home expand]', JSON.stringify({ expand, expanded }))
await c.screenshot(`${OUT_DIR}/02-workspace-home-expanded.png`)

// ── 2. 待办中心：统一列表 + 视图切换 + 筛选写 URL ──
await c.navigate('http://localhost:5174/app/tasks')
const tc = await c.evaluate(`(() => {
  const t = document.body.innerText
  return {
    url: location.href,
    hasUnifiedTable: !!document.querySelector('.el-table'),
    hasViews: t.includes('需要我处理') && t.includes('等待外部') && t.includes('受阻') && t.includes('已完成'),
    hasFilters: !!document.querySelector('.filters'),
    emptyNew: t.includes('还没有') || t.includes('没有待办') || t.includes('EMPTY') || document.querySelector('.el-table__empty-text') !== null,
  }
})()`)
console.log('[E-tasks]', JSON.stringify(tc))
await c.screenshot(`${OUT_DIR}/03-task-center.png`)

// 切到「等待外部」视图 → URL query 应更新
const viewSwitch = await c.evaluate(`(() => {
  const labels = [...document.querySelectorAll('.el-radio-button__inner')]
  const target = labels.find((l) => l.textContent.includes('等待外部'))
  if (!target) return { clicked: false, labels: labels.map((l) => l.textContent.trim()) }
  target.click(); return { clicked: true, labels: labels.map((l) => l.textContent.trim()) }
})()`)
await new Promise((r) => setTimeout(r, 1200))
const afterView = await c.evaluate(`(() => ({ url: location.href, query: location.search }))()`)
console.log('[E-tasks view-switch]', JSON.stringify({ viewSwitch, afterView }))
await c.screenshot(`${OUT_DIR}/04-task-center-waiting-view.png`)

// 输入「店铺」筛选 → URL query 应含 store（el-input @change 在 blur/enter 触发）
const storeFilter = await c.evaluate(`(() => {
  const inputs = [...document.querySelectorAll('.filters input')]
  const storeInput = inputs.find((i) => i.placeholder === '店铺')
  if (!storeInput) return { typed: false, placeholders: inputs.map((i) => i.placeholder) }
  storeInput.focus()
  storeInput.value = '美国站'
  storeInput.dispatchEvent(new Event('input', { bubbles: true }))
  storeInput.dispatchEvent(new Event('change', { bubbles: true }))
  storeInput.blur()
  return { typed: true }
})()`)
await new Promise((r) => setTimeout(r, 1200))
const afterFilter = await c.evaluate(`(() => ({ url: location.href, query: location.search }))()`)
console.log('[E-tasks store-filter]', JSON.stringify({ storeFilter, afterFilter }))
await c.screenshot(`${OUT_DIR}/05-task-center-store-filter.png`)

// 浏览器返回 → query 应恢复（回到 view=waiting 无 store）
await c.evaluate(`(() => { history.back(); return true })()`)
await new Promise((r) => setTimeout(r, 1500))
const afterBack = await c.evaluate(`(() => ({ url: location.href, query: location.search }))()`)
console.log('[E-tasks back]', JSON.stringify(afterBack))

// ── 3. 不误导：缺失显示 — 而非 0（拉取后端原始响应交叉验证） ──
const api = async (p) => (await fetch(`http://127.0.0.1:8000/api${p}`, { headers: { Authorization: `Bearer ${token}` } })).json()
const todoApi = await api('/workbench/todo')
const ovApi = await api('/workbench/overview')
console.log('[api-cross-check]', JSON.stringify({
  todoSources: todoApi.sources, todoCounts: todoApi.counts, todoPartial: todoApi.partial,
  ovSources: ovApi.sources, ovPartial: ovApi.partial,
  signals: ovApi.signals,
  inProgressLen: (ovApi.sections?.in_progress || []).length,
  aiDoneLen: (ovApi.sections?.ai_done?.items || []).length,
}))

await c.send('Target.closeTarget').catch(() => {})
chrome.kill()
console.log('DONE')
process.exit(0)
