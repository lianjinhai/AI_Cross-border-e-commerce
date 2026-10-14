// R3-1A 真实浏览器验收脚本（CDP 直连系统 Chrome，仅依赖 Node 22 内置 WebSocket）
// 用途：QA/后续批次可重复执行，验证 /app/products/:id 渠道+素材分区 与 /app/channels 命中真实页。
// 前提：5174 dev 服务器（V9）与 8000 后端已启动；截图输出到本目录。
// 用法：node browser-verify.mjs
//
// 实现说明（排坑记录）：
// - Chrome 必须加 --no-proxy-server：环境存在 ambient http_proxy（127.0.0.1:2866），
//   会把 127.0.0.1 页面请求也走代理导致 chrome-error:// 打不开。
// - dev 服务器绑定 [::1]，页面导航用 http://localhost:5174（走 ::1），
//   token 获取仍直连 8000（IPv4）。
// - /json/new?URL 建页后仍需确认 location 已落到 http 源，about:blank 上 localStorage 抛 SecurityError。

import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT_DIR = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-1A'
fs.mkdirSync(OUT_DIR, { recursive: true })
const LOGIN = 'http://localhost:5174/console/login'

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9333', '--user-data-dir=C:/temp/r3-chrome-profile',
  '--no-first-run', '--no-proxy-server', 'about:blank',
], { stdio: 'ignore' })

/** 新建 CDP 页标签（直接落在 http 源上，避免 about:blank 的 localStorage 限制）。 */
async function getWsUrl(startUrl, timeoutMs = 15000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9333/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
      if (created.ok) return (await created.json()).webSocketDebuggerUrl
    } catch {}
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error('Chrome CDP 未就绪')
}

/** 极简 CDP 客户端（只读场景：evaluate / navigate / screenshot）。 */
function connectCdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl) // Node 22 内置
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
        // about:blank 的 readyState 恒为 complete，须以 location 落到目标源为准（探针容错）
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 250))
          let href = null
          try { href = String(await client.evaluate('location.href')) } catch {}
          if (href && href.startsWith(url.split('#')[0].replace(/\/$/, ''))) break
        }
        await new Promise((r) => setTimeout(r, 1000))
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

// token（8000 IPv4 直连；若环境有 proxy 拦截请设 NO_PROXY=127.0.0.1 运行）
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
console.log('[diag] 落点：', startHref)
await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(token)}); 'ok'`)

// ── 1. 商品详情 /app/products/1（E01 渠道分区 / E02 店铺上下文 / E05 素材字段 / E06 独立错误态） ──
await c.navigate('http://localhost:5174/app/products/1')
const p1 = await c.evaluate(`(() => {
  const t = document.body.innerText
  return { url: location.href, hasChannelSection: t.includes('渠道信息'), hasAssetSection: t.includes('素材与核验'),
    shopGuide: t.includes('请先在上方选择目标店铺') || t.includes('请先选择目标店铺'),
    channelEmptyHint: t.includes('该商品尚未在可访问的店铺中上线'),
    basicInfo: t.includes('健身弹力带'), hasShopSelect: !!document.querySelector('.asset-tools .el-select') }
})()`)
console.log('[product-detail]', JSON.stringify(p1))
await c.screenshot(`${OUT_DIR}/01-product-detail.png`)

// 选择目标店铺（素材区按 shop_id 隔离；演示数据店铺均非 sales 角色时会显示 404 错误态而非空列表）
const pickResult = await c.evaluate(`(() => {
  const sel = document.querySelector('.asset-tools .el-select')
  if (!sel) return { picked: false, reason: 'no selector on page' }
  sel.click()
  return { picked: true }
})()`)
await new Promise((r) => setTimeout(r, 1200))
const pick2 = await c.evaluate(`(() => {
  const items = [...document.querySelectorAll('.el-select-dropdown__item')]
  if (!items.length) return { optionCount: 0 }
  items[0].click()
  return { optionCount: items.length, pickedLabel: items[0].textContent.trim() }
})()`)
await new Promise((r) => setTimeout(r, 1500))
const p1b = await c.evaluate(`(() => {
  const t = document.body.innerText
  return { assetEmpty: t.includes('该店铺还没有素材记录'), assetError: t.includes('素材加载失败'),
    notFound: t.includes('商品或目标店铺不存在'), hasTable: !!document.querySelector('.el-card table') }
})()`)
console.log('[asset-after-pick]', JSON.stringify({ pickResult, pick2, p1b }))
await c.screenshot(`${OUT_DIR}/01b-product-detail-asset-shop.png`)

// ── 2. 渠道推荐 /app/channels（E09：必须命中 Channels.vue 真实页，非 StubPage） ──
await c.navigate('http://localhost:5174/app/channels')
const p2 = await c.evaluate(`(() => {
  const t = document.body.innerText
  return { url: location.href, isRealChannelsPage: t.includes('平台能力墙'), targetMarket: t.includes('目标市场'),
    isStub: t.includes('占位页') || /stub/i.test(t), cardCount: document.querySelectorAll('.channel-card').length }
})()`)
console.log('[channels]', JSON.stringify(p2))
await c.screenshot(`${OUT_DIR}/02-channels.png`)

// ── 3. hidden 参数路由 /app/channels/shops/2（ShopDetail.vue） ──
await c.navigate('http://localhost:5174/app/channels/shops/2')
console.log('[shop-detail-route]', await c.evaluate('location.pathname'))
await c.screenshot(`${OUT_DIR}/03-channels-shops-detail.png`)

await c.send('Target.closeTarget').catch(() => {})
chrome.kill()
console.log('DONE')
process.exit(0)
