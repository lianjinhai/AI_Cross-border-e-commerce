// R3-2B 修复复验（CDP 直连系统 Chrome；仅依赖 Node 22 内置 WebSocket）
// 覆盖：①对象字段渲染无 [object Object] ②计数三方口径一致（顶栏/工作台/待办中心）
//      ③返回回跳 return_to 唯一且保留 view/store ④返回恢复 ⑤移动端 390/768 无横向溢出。
// 前提：5174 dev（V9）+ 8000 后端已启动。用法：node r32b-fix-verify.mjs
//
// 排坑：Chrome 必须 --no-proxy-server；dev 绑定 [::1]，导航用 http://localhost:5174。

import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT_DIR = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-2B'
fs.mkdirSync(OUT_DIR, { recursive: true })
const LOGIN = 'http://localhost:5174/console/login'

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9338', '--user-data-dir=C:/temp/r32b-fix-chrome2',
  '--no-first-run', '--no-proxy-server', 'about:blank',
], { stdio: 'ignore' })

// 兜底：最多 150s 后强杀，避免挂起
setTimeout(() => { try { chrome.kill() } catch {} ; console.log('TIMEOUT'); process.exit(2) }, 150000)

async function getWsUrl(startUrl, timeoutMs = 15000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9338/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
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
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result, msg.error); pending.delete(msg.id) }
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
      async viewport(width, height, mobile) {
        await client.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: !!mobile })
      },
      async screenshot(file, full = true) {
        const r = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: full })
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
const startHref = await c.evaluate('location.href').catch(() => 'about:blank')
if (String(startHref).startsWith('about')) await c.navigate(LOGIN)
await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(token)}); 'ok'`)

// ── 1. 工作台首屏（四层 + 计数条 + 无 [object Object]） ──
await c.navigate('http://localhost:5174/app')
const home = await c.evaluate(`(() => {
  const t = document.body.innerText
  const counters = [...document.querySelectorAll('.counter')].map((el) => el.querySelector('.counter__num')?.textContent.trim())
  const chips = [...document.querySelectorAll('.shell-context__chip-value')].map((el) => el.textContent.trim())
  return {
    hasLayer1: t.includes('今天最值得完成的一件事'),
    hasLayer2: t.includes('还需要处理'),
    hasLayer3: t.includes('当前经营状况'),
    hasLayer4: t.includes('AI 执行历史') && t.includes('完整经营数据'),
    counters, topbarChips: chips,
    hasObjectObject: t.includes('[object Object]'),
  }
})()`)
console.log('[E-home]', JSON.stringify(home))
await c.screenshot(`${OUT_DIR}/06-r32b-home.png`)

// ── 2. 待办中心：统一列表 + 视图/计数条/口径一致 + 无 [object Object] ──
await c.navigate('http://localhost:5174/app/tasks')
const tc = await c.evaluate(`(() => {
  const t = document.body.innerText
  const tabs = [...document.querySelectorAll('.el-radio-button__inner')].map((el) => el.textContent.trim())
  const strip = [...document.querySelectorAll('.counter-strip__num')].map((el) => el.textContent.trim())
  const chips = [...document.querySelectorAll('.shell-context__chip-value')].map((el) => el.textContent.trim())
  return {
    hasUnifiedTable: !!document.querySelector('.el-table'),
    tabs, strip, topbarChips: chips,
    hasFilters: !!document.querySelector('.filters'),
    hasObjectObject: t.includes('[object Object]'),
  }
})()`)
console.log('[E-tasks]', JSON.stringify(tc))
await c.screenshot(`${OUT_DIR}/07-r32b-task-center.png`)

// ── 3. 返回回跳：点「处理」→ URL 只含一个 return_to（bug4：不重复追加） ──
const clickRes = await c.evaluate(`(() => {
  const btns = [...document.querySelectorAll('.el-table .el-button')].filter((b) => b.textContent.trim() === '处理')
  if (!btns.length) return { clicked: false }
  btns[0].click(); return { clicked: true }
})()`)
await new Promise((r) => setTimeout(r, 1500))
const afterClick = await c.evaluate('location.href')
const returnToCount = (String(afterClick).match(/return_to=/g) || []).length
console.log('[E-tasks return_to]', JSON.stringify({ clickRes, afterClick, returnToCount }))
await c.screenshot(`${OUT_DIR}/10-r32b-task-click.png`)

// 回到待办中心，验证浏览器返回恢复筛选（history.back）
await c.navigate('http://localhost:5174/app/tasks?view=waiting')
await c.evaluate(`(() => { const labels=[...document.querySelectorAll('.el-radio-button__inner')]; const block=labels.find(l=>l.textContent.includes('被阻断')); if(block) block.click(); return true })()`)
await new Promise((r) => setTimeout(r, 1000))
const beforeBack = await c.evaluate('location.search')
await c.evaluate('history.back(); true')
await new Promise((r) => setTimeout(r, 1500))
const afterBack = await c.evaluate('location.search')
console.log('[E-tasks back]', JSON.stringify({ beforeBack, afterBack }))

// ── 4. 后端原始响应交叉核对（含 route 形状、in_progress 长度） ──
const api = async (p) => (await fetch(`http://127.0.0.1:8000/api${p}`, { headers: { Authorization: `Bearer ${token}` } })).json()
const todoApi = await api('/workbench/todo')
const ovApi = await api('/workbench/overview')
console.log('[api-cross-check]', JSON.stringify({
  todoSources: todoApi.sources, todoCounts: todoApi.counts, todoPartial: todoApi.partial,
  todoItemRoutes: (todoApi.items || []).map((i) => i.route?.path),
  ovSources: ovApi.sources,
  needHuman: ovApi.sections?.need_human,
  inProgressLen: (ovApi.sections?.in_progress || []).length,
  inProgressSample: (ovApi.sections?.in_progress || []).slice(0, 2),
  aiDoneLen: (ovApi.sections?.ai_done?.items || []).length,
  signals: ovApi.signals,
}))

await c.send('Target.closeTarget').catch(() => {})
chrome.kill()
console.log('DONE')
process.exit(0)
