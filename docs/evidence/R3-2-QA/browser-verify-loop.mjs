// R3-2 定向验证：筛选上下文在「处理→返回」闭环中不丢失。
// 从带 query 的过滤视图（?view=blocked，有真实行）出发，点「处理」→ 目标页 → 返回，
// 断言返回后 query 仍为 ?view=blocked（不丢筛选上下文），且 return_to 单一无嵌套。
import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT_DIR = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-2-QA'
const DEV = 'http://127.0.0.1:5191'
const API = 'http://127.0.0.1:8010/api'
const LOGIN = `${DEV}/console/login`
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function apiLogin(username, password) {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const j = await r.json()
  if (!j.token) throw new Error(`login failed: ${JSON.stringify(j)}`)
  return j
}

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9338', '--user-data-dir=C:/temp/r32qa-chrome-loop',
  '--no-first-run', '--no-proxy-server', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9338/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
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
        if (r.exceptionDetails) throw new Error('eval: ' + JSON.stringify(r.exceptionDetails.exception?.description))
        return r.result?.value
      },
      async navigate(url) {
        await client.send('Page.navigate', { url })
        const target = url.split('#')[0].replace(/\/$/, '')
        for (let i = 0; i < 80; i++) {
          await sleep(200)
          let href = null
          try { href = await client.evaluate('location.href') } catch {}
          if (href && href.split('#')[0].replace(/\/$/, '').startsWith(target)) break
        }
        await sleep(1400)
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

async function setToken(c, token, user) {
  await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(token)});
    localStorage.setItem('erp_user', ${JSON.stringify(JSON.stringify(user))}); 'ok'`)
}

const R = {}
const c = await connectCdp(await getWsUrl(LOGIN))
await c.send('Runtime.enable')
await c.send('Page.enable')
const sess = await apiLogin('qa_owner', 'qa123456')
await setToken(c, sess.token, sess.user)

await c.navigate(`${DEV}/app/tasks`)
// 切到「被阻断」（有 1 行真实明细）
await c.evaluate(`(() => { const el = [...document.querySelectorAll('.el-radio-button__inner')]
  .find((l) => l.textContent.includes('被阻断')); el && el.click(); return !!el })()`)
await sleep(1300)
R.filteredUrl = await c.evaluate('location.href')
R.rowCount = await c.evaluate(`document.querySelectorAll('.el-table__body-wrapper tbody tr').length`)

// 点「处理」
R.openTask = await c.evaluate(`(() => {
  const btn = [...document.querySelectorAll('.el-table__body-wrapper tbody tr button')].find((b) => b.textContent.includes('处理'))
  if (!btn) return { clicked: false }
  btn.click(); return { clicked: true }
})()`)
await sleep(1800)
R.targetUrl = await c.evaluate('location.href')
R.returnToCount = (R.targetUrl.split('return_to=').length - 1)
R.returnToNested = /return_to=.*return_to=/.test(R.targetUrl)
await c.screenshot(`${OUT_DIR}/26-loop-filter-target.png`)

// 返回
await c.evaluate('history.back(); true')
await sleep(2000)
R.restoredUrl = await c.evaluate('location.href')
R.restoredQuery = await c.evaluate('location.search')
R.queryPreserved = R.restoredQuery === '?view=blocked'
R.rowCountAfterBack = await c.evaluate(`document.querySelectorAll('.el-table__body-wrapper tbody tr').length`)
await c.screenshot(`${OUT_DIR}/27-loop-filter-restored.png`)

console.log('===== R3-2-QA LOOP RESULT =====')
console.log(JSON.stringify(R, null, 2))
console.log('DONE')
chrome.kill()
process.exit(0)
