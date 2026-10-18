// R3-3 排障探针 4：/app/channels 的 J0「下一步」点击为何不生效。
import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const DEV = 'http://127.0.0.1:5193'
const API = 'http://127.0.0.1:8011/api'
const OUT = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-3-QA'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const PROFILE = `C:/temp/r33qa-probe4-${Date.now()}`
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9341', `--user-data-dir=${PROFILE}`,
  '--no-first-run', '--no-proxy-server', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 25000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9341/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
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
        if (r.exceptionDetails) return { __error: JSON.stringify(r.exceptionDetails).slice(0, 700) }
        return r.result?.value
      },
      async navigate(url) { await client.send('Page.navigate', { url }); await sleep(4000) },
    }
    ws.onopen = () => resolve(client)
    ws.onerror = () => reject(new Error('ws error'))
  })
}

const c = await connectCdp(await getWsUrl(DEV))
await c.send('Runtime.enable')
await c.send('Page.enable')

const login = await (await fetch(`${API}/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'qa_newbie', password: 'qa123456' }),
})).json()

await c.navigate(`${DEV}/console/login`)
await c.evaluate(`localStorage.clear();
  localStorage.setItem('erp_token', ${JSON.stringify(login.token)});
  localStorage.setItem('erp_user', ${JSON.stringify(JSON.stringify(login.user))}); 'ok'`)

await c.navigate(`${DEV}/app/channels?journey=j0`)
const out = {}
out.before = await c.evaluate(`(() => {
  const bar = document.querySelector('.j0-bar')
  const btn = [...bar.querySelectorAll('button')].find((b) => /下一步/.test(b.textContent))
  return {
    href: location.href,
    barCount: document.querySelectorAll('.j0-bar').length,
    btnCount: bar.querySelectorAll('button').length,
    btnText: btn?.textContent.trim(),
    btnDisabled: btn?.disabled,
    btnClass: btn?.className,
    hasVueApp: !!document.querySelector('#app').__vue_app__,
  }
})()`)

// 直接调用 router.push（绕过 DOM 点击），看是否被守卫挡住
out.routerPush = await c.evaluate(`(async () => {
  const app = document.querySelector('#app').__vue_app__
  const router = app.config.globalProperties.$router
  const from = router.currentRoute.value.fullPath
  try {
    await router.push({ path: '/app/market/candidates', query: { journey: 'j0' } })
  } catch (e) {
    return { from, error: String(e && (e.message || e)) }
  }
  await new Promise((r) => setTimeout(r, 800))
  return { from, to: location.href, route: router.currentRoute.value.fullPath }
})()`)

// 再回渠道页，用真实 DOM 点击，并观察 pushState 调用
await c.navigate(`${DEV}/app/channels?journey=j0`)
out.domClick = await c.evaluate(`(async () => {
  const log = []
  const orig = history.pushState.bind(history)
  history.pushState = function (...a) { log.push(String(a[2])); return orig(...a) }
  const bar = document.querySelector('.j0-bar')
  const btn = [...bar.querySelectorAll('button')].find((b) => /下一步/.test(b.textContent))
  btn && btn.click()
  await new Promise((r) => setTimeout(r, 2000))
  history.pushState = orig
  return { href: location.href, pushStateCalls: log, barTitle: document.querySelector('.j0-bar__title')?.textContent?.trim() || '' }
})()`)

// 该页是否有浮层/遮罩覆盖（pointer-events 层面）
out.overlay = await c.evaluate(`(() => {
  const bar = document.querySelector('.j0-bar')
  if (!bar) return 'no-bar'
  const r = bar.getBoundingClientRect()
  const el = document.elementFromPoint(r.left + r.width / 2, r.top + 20)
  return { topEl: el ? el.className || el.tagName : null, insideBar: !!(el && bar.contains(el)) }
})()`)

fs.writeFileSync(`${OUT}/probe4-result.json`, JSON.stringify(out, null, 2))
console.log(JSON.stringify(out, null, 2).slice(0, 6000))
chrome.kill()
process.exit(0)
