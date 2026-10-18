// R3-3 排障探针 2：定位 J0 页面白屏根因（区分「页面本身坏」还是「journey=j0 触发」）。
import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const DEV = 'http://127.0.0.1:5193'
const API = 'http://127.0.0.1:8011/api'
const OUT = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-3-QA'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function apiLogin(u, p) {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: u, password: p }),
  })
  return r.json()
}

// 每次运行用唯一 profile：不删旧目录（safe-delete 守卫拒绝批量删除），也避免登录态串味。
const PROFILE = `C:/temp/r33qa-probe2-${Date.now()}`
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9339', `--user-data-dir=${PROFILE}`,
  '--no-first-run', '--no-proxy-server', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 25000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9339/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
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
        if (r.exceptionDetails) return { __error: JSON.stringify(r.exceptionDetails).slice(0, 600) }
        return r.result?.value
      },
      async navigate(url) { await client.send('Page.navigate', { url }); await sleep(3500) },
    }
    ws.onopen = () => resolve(client)
    ws.onerror = () => reject(new Error('ws error'))
  })
}

const c = await connectCdp(await getWsUrl(DEV))
await c.send('Runtime.enable')
await c.send('Page.enable')
await c.send('Network.enable')

// 在每次文档加载前安装错误收集器
await c.send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    window.__errs = [];
    window.addEventListener('error', (e) => {
      window.__errs.push('ERR: ' + String((e.error && e.error.stack) || e.message));
    });
    window.addEventListener('unhandledrejection', (e) => {
      window.__errs.push('REJ: ' + String((e.reason && e.reason.stack) || e.reason));
    });
    const _ce = console.error;
    console.error = function (...a) {
      window.__errs.push('CONSOLE: ' + a.map((x) => (x && x.stack) || String(x)).join(' ').slice(0, 800));
      return _ce.apply(console, a);
    };
  `,
})

const snap = async (label) => {
  const info = await c.evaluate(`(() => ({
    href: location.href,
    appHtml: (document.getElementById('app')?.innerHTML || '').slice(0, 120),
    appLen: (document.getElementById('app')?.innerHTML || '').length,
    textLen: (document.body.innerText || '').length,
    hasBar: !!document.querySelector('.j0-bar'),
    errs: window.__errs || [],
  }))()`)
  const failed = c.events
    .filter((e) => e.method === 'Network.responseReceived' && e.params?.response?.status >= 400)
    .map((e) => `${e.params.response.status} ${e.params.response.url}`)
    .slice(-8)
  return { label, ...info, httpErrors: failed }
}

const out = {}
const n = await apiLogin('qa_newbie', 'qa123456')
await c.navigate(`${DEV}/console/login`)
await c.evaluate(`localStorage.clear();
  localStorage.setItem('erp_token', ${JSON.stringify(n.token)});
  localStorage.setItem('erp_user', ${JSON.stringify(JSON.stringify(n.user))}); 'ok'`)

c.events.length = 0
await c.navigate(`${DEV}/app/market/discovery`)
out.newbie_discovery = await snap('newbie /app/market/discovery')
const s1 = await c.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
fs.writeFileSync(`${OUT}/91-probe-discovery-nojourney.png`, Buffer.from(s1.data, 'base64'))

c.events.length = 0
await c.navigate(`${DEV}/app/market/discovery?journey=j0`)
out.newbie_discovery_j0 = await snap('newbie discovery?journey=j0')
const s2 = await c.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
fs.writeFileSync(`${OUT}/92-probe-discovery-j0.png`, Buffer.from(s2.data, 'base64'))

const o = await apiLogin('qa_owner', 'qa123456')
await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(o.token)});
  localStorage.setItem('erp_user', ${JSON.stringify(JSON.stringify(o.user))}); 'ok'`)
c.events.length = 0
await c.navigate(`${DEV}/app/market/discovery?journey=j0`)
out.owner_discovery_j0 = await snap('owner discovery?journey=j0')

fs.writeFileSync(`${OUT}/probe2-result.json`, JSON.stringify(out, null, 2))
console.log(JSON.stringify(out, null, 2).slice(0, 8000))
chrome.kill()
process.exit(0)
