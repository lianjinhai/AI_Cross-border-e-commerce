// R3-3 验证排障探针：只读，用于区分「产品缺陷」与「驱动脚本缺陷」。
// 用法：node docs/evidence/R3-3-QA/debug-probe.mjs
import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const DEV = 'http://127.0.0.1:5193'
const API = 'http://127.0.0.1:8011/api'
const LOGIN = `${DEV}/console/login`
const OUT = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-3-QA'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function apiLogin(username, password) {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return r.json()
}

// 每次运行用唯一 profile：不删旧目录（safe-delete 守卫拒绝批量删除），也避免登录态串味。
const PROFILE = `C:/temp/r33qa-probe-${Date.now()}`
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9338', `--user-data-dir=${PROFILE}`,
  '--no-first-run', '--no-proxy-server', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 25000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9338/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
      if (created.ok) return (await created.json()).webSocketDebuggerUrl
    } catch {}
    await sleep(500)
  }
  throw new Error('CDP 未就绪')
}

function connectCdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl)
    let seq = 0
    const pending = new Map()
    const events = []
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result, msg.error); pending.delete(msg.id) }
      else if (msg.method) events.push(msg)
    }
    const client = {
      events,
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const id = ++seq
          pending.set(id, (result, error) => (error ? rej(new Error(JSON.stringify(error))) : res(result)))
          ws.send(JSON.stringify({ id, method, params }))
        })
      },
      async evaluate(expression) {
        const r = await client.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
        if (r.exceptionDetails) return { __error: JSON.stringify(r.exceptionDetails) }
        return r.result?.value
      },
      async navigate(url) { await client.send('Page.navigate', { url }); await sleep(3000) },
    }
    ws.onopen = () => resolve(client)
    ws.onerror = () => reject(new Error('ws error'))
  })
}

const c = await connectCdp(await getWsUrl(LOGIN))
await c.send('Runtime.enable')
await c.send('Page.enable')
await c.send('Log.enable')
const report = { api: {}, pages: {}, errors: [] }

// ── API 探针：qa_owner 的真实任务 DTO（store/product 字段形状）
try {
  const s = await apiLogin('qa_owner', 'qa123456')
  report.api.login = { role: s.user?.role, tenant: s.user?.tenant_id, hasToken: Boolean(s.token) }
  for (const [name, path] of [['overview', '/workbench/overview'], ['todo', '/workbench/todo']]) {
    const r = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${s.token}` } })
    const j = await r.json()
    report.api[name] = { status: r.status, keys: Object.keys(j), body: j }
  }
  // 新用户身份
  const n = await apiLogin('qa_newbie', 'qa123456')
  report.api.newbie = { role: n.user?.role, tenant: n.user?.tenant_id, user: n.user }
  const r2 = await fetch(`${API}/workspaces/current`, { headers: { Authorization: `Bearer ${n.token}` } })
  report.api.newbieContext = { status: r2.status, body: await r2.json().catch(() => null) }
} catch (e) { report.errors.push('api probe: ' + e.message) }

// ── 页面探针：新用户 /app 与 J0 页
try {
  const n = await apiLogin('qa_newbie', 'qa123456')
  await c.navigate(LOGIN)
  await c.evaluate(`localStorage.clear();
    localStorage.setItem('erp_token', ${JSON.stringify(n.token)});
    localStorage.setItem('erp_user', ${JSON.stringify(JSON.stringify(n.user))}); 'ok'`)
  await c.navigate(`${DEV}/app`)
  report.pages.newbie_home = await c.evaluate(`(() => ({
    href: location.href,
    appHtmlLen: (document.getElementById('app')?.innerHTML || '').length,
    bodyText: (document.body.innerText || '').slice(0, 300),
    title: document.title,
  }))()`)
  const shot = await c.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
  fs.writeFileSync(`${OUT}/90-probe-newbie-home.png`, Buffer.from(shot.data, 'base64'))

  await c.navigate(`${DEV}/app/market/discovery?journey=j0`)
  report.pages.newbie_j0 = await c.evaluate(`(() => ({
    href: location.href,
    appHtmlLen: (document.getElementById('app')?.innerHTML || '').length,
    bodyText: (document.body.innerText || '').slice(0, 400),
    hasBar: !!document.querySelector('.j0-bar'),
  }))()`)
} catch (e) { report.errors.push('page probe newbie: ' + e.message) }

// ── 页面探针：qa_owner 待办（默认 vs 店铺筛选）
try {
  const s = await apiLogin('qa_owner', 'qa123456')
  await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(s.token)});
    localStorage.setItem('erp_user', ${JSON.stringify(JSON.stringify(s.user))}); 'ok'`)
  await c.navigate(`${DEV}/app/tasks`)
  report.pages.tasks_default = await c.evaluate(`(() => ({
    href: location.href,
    rows: [...document.querySelectorAll('.task-center__table tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].map((td) => td.innerText.trim())).slice(0, 8),
  }))()`)
  await c.navigate(`${DEV}/app/tasks?store=${encodeURIComponent('美国站二号店')}`)
  report.pages.tasks_store = await c.evaluate(`(() => ({
    href: location.href,
    rows: [...document.querySelectorAll('.task-center__table tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].map((td) => td.innerText.trim())).slice(0, 8),
    emptyText: (document.body.innerText || '').slice(0, 400),
  }))()`)
} catch (e) { report.errors.push('page probe tasks: ' + e.message) }

// ── 控制台 / 未捕获异常
for (const ev of c.events) {
  if (ev.method === 'Runtime.exceptionThrown') {
    report.errors.push('EXCEPTION: ' + (ev.params?.exceptionDetails?.exception?.description || ev.params?.exceptionDetails?.text))
  }
  if (ev.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(ev.params?.type)) {
    report.errors.push(`CONSOLE_${ev.params.type}: ` + ev.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 400))
  }
  if (ev.method === 'Log.entryAdded' && ev.params?.entry?.level === 'error') {
    report.errors.push('LOG: ' + ev.params.entry.text?.slice(0, 300))
  }
}

fs.writeFileSync(`${OUT}/probe-result.json`, JSON.stringify(report, null, 2))
console.log(JSON.stringify({
  api: {
    login: report.api.login, newbie: report.api.newbie, newbieContext: report.api.newbieContext,
    overviewKeys: report.api.overview?.keys, todoKeys: report.api.todo?.keys,
    overview: report.api.overview?.body, todo: report.api.todo?.body,
  },
  pages: report.pages,
  errors: report.errors.slice(0, 20),
}, null, 2).slice(0, 12000))
chrome.kill()
process.exit(0)
