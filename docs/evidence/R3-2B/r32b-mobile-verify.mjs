// R3-2B 移动端响应式复验（390 / 768）：截图 + 横向溢出检查。CDP 直连系统 Chrome。
// 前提：5174 dev（V9）+ 8000 后端已启动。用法：node r32b-mobile-verify.mjs
import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT_DIR = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-2B'
const LOGIN = 'http://localhost:5174/console/login'
const PORT = 9337

const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--user-data-dir=C:/temp/r32b-mobile-chrome',
  '--no-first-run', '--no-proxy-server', 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
// 兜底：最多 120s 后强杀，避免挂起
const guard = setTimeout(() => { try { chrome.kill() } catch {} ; console.log('TIMEOUT'); process.exit(2) }, 120000)

async function getWsUrl(startUrl, timeoutMs = 15000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
      if (created.ok) return (await created.json()).webSocketDebuggerUrl
    } catch {}
    await sleep(500)
  }
  throw new Error('Chrome CDP 未就绪')
}

function connectCdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl)
    let seq = 0
    const pending = new Map()
    ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result, msg.error); pending.delete(msg.id) } }
    const client = {
      send(method, params = {}) { return new Promise((res, rej) => { const id = ++seq; pending.set(id, (r, e) => (e ? rej(new Error(JSON.stringify(e))) : res(r))); ws.send(JSON.stringify({ id, method, params })) }) },
      async evaluate(expression) { const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error('eval: ' + JSON.stringify(r.exceptionDetails.exception?.description)); return r.result?.value },
      async navigate(url) { await this.send('Page.navigate', { url }); for (let i = 0; i < 40; i++) { await sleep(250); let h = null; try { h = await this.evaluate('location.href') } catch {} if (h && h.startsWith(url)) break } await sleep(1200) },
      async viewport(w, h, mobile) { await this.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: !!mobile }) },
      async screenshot(file) { const r = await this.send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(file, Buffer.from(r.data, 'base64')); console.log('[shot]', file) },
    }
    ws.onopen = () => resolve(client)
    ws.onerror = () => reject(new Error('ws error'))
  })
}

const token = (await fetch('http://127.0.0.1:8000/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'admin', password: 'admin123' }) }).then((r) => r.json())).token
if (!token) { console.error('登录失败'); process.exit(1) }

const c = await connectCdp(await getWsUrl(LOGIN))
await c.send('Runtime.enable')
await c.send('Page.enable')
await c.navigate(LOGIN)
await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(token)}); 'ok'`)

for (const [w, h, name] of [[390, 844, '390'], [768, 1024, '768']]) {
  await c.viewport(w, h, w < 768)
  await c.navigate('http://localhost:5174/app')
  const home = await c.evaluate(`(() => ({ inner: window.innerWidth, scroll: document.documentElement.scrollWidth, body: document.body.scrollWidth }))()`)
  await c.screenshot(`${OUT_DIR}/08-r32b-home-${name}.png`)
  await c.navigate('http://localhost:5174/app/tasks')
  const tasks = await c.evaluate(`(() => ({ inner: window.innerWidth, scroll: document.documentElement.scrollWidth, body: document.body.scrollWidth }))()`)
  await c.screenshot(`${OUT_DIR}/09-r32b-tasks-${name}.png`)
  console.log(`[E-mobile ${name}]`, JSON.stringify({ home, tasks, homeOverflow: home.scroll > home.inner + 2, tasksOverflow: tasks.scroll > tasks.inner + 2 }))
}

await c.evaluate('true').catch(() => {})
try { await c.send('Target.closeTarget') } catch {}
clearTimeout(guard)
chrome.kill()
console.log('DONE')
process.exit(0)
