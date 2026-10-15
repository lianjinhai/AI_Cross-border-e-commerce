// R3-2 定向补充验证（Round2 supplement）：
//  A. 顶栏计数条 ↔ 首页计数 ↔ TaskCenter 计数条 三方同口径
//  B. 「被阻断」视图切换 + 行（驱动补：正确标签为「被阻断」）
//  C. 闭环：全部待办点「处理」→ 目标页带单个 return_to → 返回后筛选恢复
// 隔离后端 8010 + V9 dev 5191（--host 127.0.0.1）。Chrome 必须 --no-proxy-server。
import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT_DIR = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-2-QA'
const DEV = 'http://127.0.0.1:5191'
const API = 'http://127.0.0.1:8010/api'
const LOGIN = `${DEV}/console/login`
fs.mkdirSync(OUT_DIR, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const R = { scenarios: {}, notes: [] }

async function apiLogin(username, password) {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const j = await r.json()
  if (!j.token) throw new Error(`login ${username} failed: ${JSON.stringify(j)}`)
  return j
}

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9337', '--user-data-dir=C:/temp/r32qa-chrome-supp',
  '--no-first-run', '--no-proxy-server', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9337/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
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

const READ_TOPBAR = `(() => [...document.querySelectorAll('[data-testid="shell-context-counts"] .shell-context__chip')]
  .map((el) => ({ label: el.querySelector('.shell-context__chip-label')?.textContent.trim(),
                  value: el.querySelector('.shell-context__chip-value')?.textContent.trim() })))()`

const READ_ROWS = `(() => {
  const rows = [...document.querySelectorAll('.el-table__body-wrapper tbody tr')].map((tr) =>
    [...tr.querySelectorAll('td')].slice(0, 8).map((td) => td.innerText.trim()))
  return { rowCount: rows.length, rows: rows.slice(0, 10) }
})()`

const c = await connectCdp(await getWsUrl(LOGIN))
await c.send('Runtime.enable')
await c.send('Page.enable')

const sess = await apiLogin('qa_owner', 'qa123456')
await setToken(c, sess.token, sess.user)

// ── A. 顶栏计数条：首页 vs TaskCenter ─────────────────────────────
await c.navigate(`${DEV}/app`)
R.scenarios.topbar_home = await c.evaluate(READ_TOPBAR)
R.scenarios.home_counters = await c.evaluate(`(() => [...document.querySelectorAll('.counter')]
  .map((el) => ({ label: el.querySelector('.counter__label')?.textContent.trim(),
                  value: el.querySelector('.counter__num')?.textContent.trim() })))()`)
await c.screenshot(`${OUT_DIR}/21-supp-topbar-home.png`)

await c.navigate(`${DEV}/app/tasks`)
R.scenarios.topbar_tasks = await c.evaluate(READ_TOPBAR)
R.scenarios.tc_counter_strip = await c.evaluate(`(() => [...document.querySelectorAll('.counter-strip__num')]
  .map((el) => el.textContent.trim()))()`)
R.scenarios.tc_views = await c.evaluate(`(() => [...document.querySelectorAll('.el-radio-button__inner')]
  .map((el) => el.textContent.trim()))()`)
await c.screenshot(`${OUT_DIR}/22-supp-topbar-tasks.png`)

// ── B. 「被阻断」视图（正确标签）─────────────────────────────────
const switchView = async (label, shot) => {
  const res = await c.evaluate(`(() => {
    const el = [...document.querySelectorAll('.el-radio-button__inner')].find((l) => l.textContent.includes(${JSON.stringify(label)}))
    if (!el) return { clicked: false }
    el.click(); return { clicked: true }
  })()`)
  await sleep(1300)
  const after = await c.evaluate(`(() => ({ url: location.href, query: location.search, ...(${READ_ROWS}) }))()`)
  if (shot) await c.screenshot(`${OUT_DIR}/${shot}`)
  return { switchView: res, after }
}
R.scenarios.tasks_blocked = await switchView('被阻断', '23-supp-tasks-blocked.png')
R.scenarios.tasks_waiting = await switchView('等待外部', null)
R.scenarios.tasks_todo = await switchView('全部待办', '24-supp-tasks-todo.png')

// ── C. 闭环：全部待办 → 点「处理」→ 目标页 return_to → 返回恢复 ──
const beforeClick = await c.evaluate('location.href')
const openTask = await c.evaluate(`(() => {
  const rows = [...document.querySelectorAll('.el-table__body-wrapper tbody tr')]
  for (let i = 0; i < rows.length; i++) {
    const btn = [...rows[i].querySelectorAll('button')].find((b) => b.textContent.includes('处理'))
    if (btn) { btn.click(); return { clicked: true, row: i, rowText: rows[i].innerText.replace(/\\s+/g, ' ').slice(0, 60) } }
  }
  return { clicked: false }
})()`)
await sleep(1800)
const target = await c.evaluate('location.href')
R.scenarios.loop_target = {
  openTask, target,
  returnToCount: (target.split('return_to=').length - 1),
  returnToNested: /return_to=.*return_to=/.test(target),
}
await c.screenshot(`${OUT_DIR}/25-supp-loop-target.png`)
await c.evaluate('history.back(); true')
await sleep(1800)
const restored = await c.evaluate('location.href')
R.scenarios.loop_restored = { beforeClick, restored, queryRestored: new URL(restored).search }

console.log('===== R3-2-QA SUPPLEMENT RESULT =====')
console.log(JSON.stringify(R, null, 2))
console.log('DONE')
chrome.kill()
process.exit(0)
