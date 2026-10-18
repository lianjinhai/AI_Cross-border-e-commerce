// R3-3 排障探针 3：J0 五步路由逐个直连（区分「路由不可达」与「点击失效」）。
import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const DEV = 'http://127.0.0.1:5193'
const API = 'http://127.0.0.1:8011/api'
const OUT = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-3-QA'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const PROFILE = `C:/temp/r33qa-probe3-${Date.now()}`
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9340', `--user-data-dir=${PROFILE}`,
  '--no-first-run', '--no-proxy-server', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 25000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9340/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
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
        if (r.exceptionDetails) return { __error: JSON.stringify(r.exceptionDetails).slice(0, 500) }
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
await c.send('Page.addScriptToEvaluateOnNewDocument', {
  source: `window.__errs=[];
    window.addEventListener('error',(e)=>window.__errs.push('ERR: '+String((e.error&&e.error.stack)||e.message)));
    window.addEventListener('unhandledrejection',(e)=>window.__errs.push('REJ: '+String((e.reason&&e.reason.stack)||e.reason)));
    const _ce=console.error; console.error=function(...a){window.__errs.push('CONSOLE: '+a.map(x=>(x&&x.stack)||String(x)).join(' ').slice(0,600)); return _ce.apply(console,a)};`,
})

const login = await (await fetch(`${API}/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'qa_newbie', password: 'qa123456' }),
})).json()

await c.navigate(`${DEV}/console/login`)
await c.evaluate(`localStorage.clear();
  localStorage.setItem('erp_token', ${JSON.stringify(login.token)});
  localStorage.setItem('erp_user', ${JSON.stringify(JSON.stringify(login.user))}); 'ok'`)

const routes = [
  '/app/market/discovery',
  '/app/supply/sourcing',
  '/app/analytics/landed-cost',
  '/app/channels',
  '/app/market/candidates',
]
const out = {}
for (const r of routes) {
  await c.navigate(`${DEV}${r}?journey=j0`)
  out[r] = await c.evaluate(`(() => {
    const bar = document.querySelector('.j0-bar')
    return {
      href: location.href,
      appLen: (document.getElementById('app')?.innerHTML || '').length,
      textLen: (document.body.innerText || '').length,
      title: document.querySelector('.page-header__title')?.textContent?.trim() || '',
      bar: bar ? bar.querySelector('.j0-bar__title')?.textContent?.trim() : null,
      btns: bar ? [...bar.querySelectorAll('button')].map((b) => b.textContent.trim()) : [],
      bodyHead: (document.body.innerText || '').slice(0, 120),
      errs: (window.__errs || []).slice(0, 3),
    }
  })()`)
  // 再点一次「下一步」，看是否会留在原地
  out[r].afterNext = await c.evaluate(`(() => {
    const bar = document.querySelector('.j0-bar')
    if (!bar) return 'no-bar'
    const b = [...bar.querySelectorAll('button')].find((x) => /下一步|完成准备/.test(x.textContent))
    if (!b) return 'no-button'
    const label = b.textContent.trim(); b.click(); return label
  })()`)
  await sleep(2500)
  out[r].afterNextHref = await c.evaluate('location.href')
  out[r].afterNextBar = await c.evaluate(`document.querySelector('.j0-bar__title')?.textContent?.trim() || ''`)
}

fs.writeFileSync(`${OUT}/probe3-result.json`, JSON.stringify(out, null, 2))
console.log(JSON.stringify(out, null, 2).slice(0, 9000))
chrome.kill()
process.exit(0)
