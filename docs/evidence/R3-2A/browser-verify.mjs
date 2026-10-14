// R3-2A 真实浏览器验收脚本（CDP 直连系统 Chrome，仅依赖 Node 22 内置 WebSocket）
// 用途：验证 4+1 侧栏渲染（5 入口 + tools 可折叠）、顶栏上下文条（Workspace/店铺/计数）、
//       入口叶子可达、OWNER vs READ_ONLY 角色隔离。截图输出到本目录。
// 前提：5174 dev 服务器（V9）与 8000 后端已启动。
// 用法：node browser-verify.mjs
//
// 排坑记录（沿用 R3-1A）：Chrome 必须加 --no-proxy-server；dev 服务器绑定 [::1]，
// 页面导航用 http://localhost:5174；token 获取直连 8000（IPv4）。

import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT_DIR = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-2A'
fs.mkdirSync(OUT_DIR, { recursive: true })
const BASE = 'http://localhost:5174'
const LOGIN = `${BASE}/console/login`

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9334', '--user-data-dir=C:/temp/r32a-chrome-profile',
  '--no-first-run', '--no-proxy-server', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 15000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9334/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
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
        const target = url.split('#')[0].replace(/\/$/, '')
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 250))
          let href = null
          try { href = String(await client.evaluate('location.href')) } catch {}
          if (href && href.startsWith(target)) break
        }
        await new Promise((r) => setTimeout(r, 1200))
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

/** 等待侧栏外壳挂载（dev 首启/路由重定向可能滞后）。 */
async function waitShell(c, timeoutMs = 12000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const ok = await c.evaluate(`!!document.querySelector('.shell__aside')`).catch(() => false)
    if (ok) return true
    await new Promise((r) => setTimeout(r, 400))
  }
  const diag = await c.evaluate(`({ href: location.href, body: document.body.innerText.slice(0, 300) })`).catch(() => ({}))
  console.log('[waitShell timeout]', JSON.stringify(diag))
  return false
}

async function tokenFor(username, password) {
  const res = await fetch('http://127.0.0.1:8000/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  }).then((r) => r.json())
  if (!res.token) { console.error(`登录失败(${username})：`, JSON.stringify(res)); process.exit(1) }
  return res.token
}

const treeProbe = `(() => {
  const aside = document.querySelector('.shell__aside')
  const entries = [...aside.querySelectorAll('.menu-group')].map((e) => e.textContent.trim())
  const submenu = [...aside.querySelectorAll('.el-sub-menu__title')].map((e) => e.textContent.trim())
  const leaves = [...aside.querySelectorAll('.el-menu-item')].map((e) => e.textContent.trim())
  const ctx = document.querySelector('[data-testid="shell-context-bar"]')
  const sub = aside.querySelector('.el-sub-menu')
  const chips = [...document.querySelectorAll('[data-testid="shell-context-counts"] .shell-context__chip')]
    .map((c) => c.textContent.replace(/\\s+/g, ' ').trim())
  return {
    url: location.href,
    groupEntries: entries,
    submenuEntries: submenu,
    toolsOpened: sub ? sub.classList.contains('is-opened') : null,
    leafCount: leaves.length,
    leaves,
    hasContextBar: !!ctx,
    ctxScope: ctx ? ctx.querySelector('.shell-context__scope').textContent.replace(/\\s+/g, ' ').trim() : null,
    ctxChips: chips,
    readOnlyBanner: document.body.innerText.includes('只读模式'),
    hasAiFab: !!document.querySelector('.aicopilot, .ai-copilot'),
  }
})()`

const c = await connectCdp(await getWsUrl(LOGIN))
await c.send('Runtime.enable')
await c.send('Page.enable')

// ── A. OWNER（admin）──
const ownerToken = await tokenFor('admin', 'admin123')
await c.navigate(LOGIN)
await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(ownerToken)}); localStorage.setItem('erp_user', JSON.stringify({username:'admin',role:'admin'})); 'ok'`)
await c.navigate(`${BASE}/app`)
await waitShell(c)
const ownerHome = await c.evaluate(treeProbe)
console.log('[OWNER /app]', JSON.stringify(ownerHome))
console.log('[OWNER tools default-opened?]', ownerHome.toolsOpened)
await c.screenshot(`${OUT_DIR}/01-sidebar-owner.png`)

// 展开「全部工具」子菜单
const expanded = await c.evaluate(`(() => {
  const t = [...document.querySelectorAll('.shell__aside .el-sub-menu__title')].find((e) => e.textContent.includes('全部工具'))
  if (!t) return { clicked: false }
  t.click(); return { clicked: true }
})()`)
await new Promise((r) => setTimeout(r, 800))
const ownerTools = await c.evaluate(treeProbe)
console.log('[OWNER tools expanded]', JSON.stringify({ expanded, toolsOpened: ownerTools.toolsOpened, leafCount: ownerTools.leafCount, toolsLeafLabels: ownerTools.leaves }))
await c.screenshot(`${OUT_DIR}/02-tools-expanded-owner.png`)

// 点入口叶子：上线中心 -> /app/launch
await c.evaluate(`(() => {
  const item = [...document.querySelectorAll('.shell__aside .el-menu-item')].find((e) => e.textContent.includes('上线中心'))
  if (item) item.click(); return !!item
})()`)
await new Promise((r) => setTimeout(r, 2200))
const afterLeaf = await c.evaluate(`({ path: location.pathname, hasLaunchHeading: /上线中心|上线/.test(document.querySelector('.shell__main')?.innerText || '') })`)
console.log('[OWNER click leaf 上线中心]', JSON.stringify(afterLeaf))
await c.screenshot(`${OUT_DIR}/05-leaf-launch-owner.png`)

// 顶栏上下文条特写（回到 /app）
await c.navigate(`${BASE}/app`)
await waitShell(c)
await c.evaluate(`(() => { const el = document.querySelector('[data-testid="shell-context-bar"]'); if (el) el.style.outline='2px solid #f56c6c'; return true })()`)
await c.screenshot(`${OUT_DIR}/03-topbar-context-owner.png`)

// ── B. READ_ONLY（viewer）──
const viewerToken = await tokenFor('viewer', 'viewer123')
await c.evaluate(`localStorage.clear(); 'ok'`)
await c.navigate(LOGIN)
await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(viewerToken)}); localStorage.setItem('erp_user', JSON.stringify({username:'viewer',role:'viewer'})); 'ok'`)
await c.navigate(`${BASE}/app`)
await waitShell(c)
const viewerHome = await c.evaluate(treeProbe)
console.log('[READ_ONLY /app]', JSON.stringify(viewerHome))
await c.evaluate(`(() => {
  const t = [...document.querySelectorAll('.shell__aside .el-sub-menu__title')].find((e) => e.textContent.includes('全部工具'))
  if (t) t.click(); return true
})()`)
await new Promise((r) => setTimeout(r, 800))
const viewerTools = await c.evaluate(treeProbe)
console.log('[READ_ONLY tools expanded]', JSON.stringify({ leaves: viewerTools.leaves, leafCount: viewerTools.leafCount }))
await c.screenshot(`${OUT_DIR}/04-sidebar-readonly.png`)

await c.send('Target.closeTarget').catch(() => {})
chrome.kill()
console.log('DONE')
process.exit(0)
