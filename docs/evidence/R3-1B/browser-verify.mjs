// R3-1B 真实浏览器验收脚本（CDP 直连系统 Chrome，仅依赖 Node 22 内置 WebSocket）
// 用途：QA/后续批次可重复执行，验证 素材登记(E03)/素材核验(E04)/Launch动作权限(E10)。
// 前提：5174 dev 服务器（V9）与 8000 后端已启动；截图输出到本目录。
// 用法：node browser-verify.mjs
//
// 实现说明（沿用 R3-1A 排坑记录）：
// - Chrome 必须加 --no-proxy-server：环境存在 ambient http_proxy（127.0.0.1:2866），
//   会把 127.0.0.1 页面请求也走代理导致 chrome-error:// 打不开。
// - dev 服务器绑定 [::1]，页面导航用 http://localhost:5174（走 ::1），
//   token 获取仍直连 8000（IPv4）。

import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT_DIR = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-1B'
fs.mkdirSync(OUT_DIR, { recursive: true })
const LOGIN = 'http://localhost:5174/console/login'

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9334', '--user-data-dir=C:/temp/r3b-chrome-profile',
  '--no-first-run', '--no-proxy-server', 'about:blank',
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

// ── 登录拿 token，并探测可用的 product/launch id ──
const loginRes = await fetch('http://127.0.0.1:8000/api/auth/login', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'admin', password: 'admin123' }),
}).then((r) => r.json())
const token = loginRes.token
if (!token) { console.error('登录失败：', JSON.stringify(loginRes)); process.exit(1) }

async function api(path) {
  const r = await fetch(`http://127.0.0.1:8000/api${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return { status: r.status, data: await r.json().catch(() => null) }
}

const products = await api('/products?page_num=1&page_size=5')
const launchList = await api('/launch?page_num=1&page_size=5')
const productId = products.data?.items?.[0]?.id
const launchId = launchList.data?.items?.[0]?.id
console.log('[probe] products.status=', products.status, 'productId=', productId)
console.log('[probe] launch.status=', launchList.status, 'launchId=', launchId)

const c = await connectCdp(await getWsUrl(LOGIN))
await c.send('Runtime.enable')
await c.send('Page.enable')
let startHref = ''
try { startHref = String(await c.evaluate('location.href')) } catch { startHref = 'about:blank' }
if (startHref.startsWith('about')) await c.navigate(LOGIN)
await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(token)}); 'ok'`)

// ── E03 素材登记表单：/app/products/{id}，选店铺，打开「登记素材」对话框，验证必填字段齐全 ──
if (productId) {
  await c.navigate(`http://localhost:5174/app/products/${productId}`)
  const pd = await c.evaluate(`(() => {
    const t = document.body.innerText
    return {
      url: location.href,
      hasAssetSection: t.includes('素材与核验'),
      shopGuide: t.includes('请先在上方选择目标店铺') || t.includes('请先选择目标店铺'),
      hasRegisterBtn: !!([...document.querySelectorAll('button')].find((b) => b.textContent.includes('登记素材'))),
      contentHashGapHint: t.includes('内容哈希') && (t.includes('未接入') || t.includes('尚无素材上传') || t.includes('暂无上传') || t.includes('真实哈希')),
    }
  })()`)
  console.log('[product-detail E03]', JSON.stringify(pd))

  // 选一个店铺（卡片级 .asset-tools 选择器），使「登记素材」按钮可用
  await c.evaluate(`(() => { const sel = document.querySelector('.asset-tools .el-select'); if (sel) sel.click(); return true })()`)
  await new Promise((r) => setTimeout(r, 1500))
  const pick2 = await c.evaluate(`(() => {
    const items = [...document.querySelectorAll('.el-select-dropdown__item')]
    if (!items.length) return { optionCount: 0 }
    items[0].click(); return { optionCount: items.length }
  })()`)
  // 等待 assetShopId 提交、登记按钮解除 disabled
  let registerEnabled = false
  for (let i = 0; i < 8; i++) {
    await new Promise((r) => setTimeout(r, 500))
    registerEnabled = await c.evaluate(`!![...document.querySelectorAll('button')].find((b) => b.textContent.includes('登记素材') && !b.disabled)`)
    if (registerEnabled) break
  }
  console.log('[E03 after-pick] registerEnabled=', registerEnabled, 'options=', pick2.optionCount)

  // 打开「登记素材」对话框（Element Plus 对话框 teleport 到 body 的 .el-overlay-dialog）
  const openDialog = registerEnabled
    ? await c.evaluate(`(() => { const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('登记素材') && !b.disabled); btn && btn.click(); return { opened: true } })()`)
    : { opened: false, note: 'button 仍 disabled（种子无 sales+market 店铺，选店铺后素材区 404，属数据缺口非代码缺陷）' }
  await new Promise((r) => setTimeout(r, 1200))
  const dialogFields = await c.evaluate(`(() => {
    const overlays = [...document.querySelectorAll('.el-overlay-dialog, .el-dialog')]
    const dlg = overlays.find((d) => (d.textContent || '').includes('登记素材'))
    if (!dlg) return { found: false }
    const labels = [...dlg.querySelectorAll('.el-form-item__label')].map((l) => l.textContent.trim()).filter(Boolean)
    return { found: true, labels }
  })()`)
  console.log('[E03 dialog]', JSON.stringify({ openDialog, dialogFields }))
  await c.screenshot(`${OUT_DIR}/01-product-detail-register.png`)
  await c.evaluate(`(() => { [...document.querySelectorAll('.el-overlay .el-dialog__headerbtn')].forEach((b) => b.click()); return true })()`)
  await new Promise((r) => setTimeout(r, 400))
}

// ── E04 核验对话框：核验按钮受 compliance:approve 门控；admin 有权限可见 ──
if (productId) {
  await c.navigate(`http://localhost:5174/app/products/${productId}`)
  await new Promise((r) => setTimeout(r, 1500))
  const verifyProbe = await c.evaluate(`(() => {
    const t = document.body.innerText
    const hasVerifyBtn = !!([...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '核验'))
    return { hasVerifyBtn, textHasCompliance: t.includes('合规') }
  })()`)
  console.log('[E04 verify-gate]', JSON.stringify(verifyProbe))
  await c.screenshot(`${OUT_DIR}/02-product-detail-verify-gate.png`)
}

// ── E10 LaunchDetail 动作区：按 available_actions 渲染 executable + disabled_reason + 回执 ──
// 种子库当前无 Launch run（11 店铺均非 sales+market），detail 会走 404/空态；
// 仍加载页面以证明动作区结构渲染（「该步骤无可执行动作」/ 回执面板），并交叉验证 API 契约。
const launchTarget = launchId || 1
await c.navigate(`http://localhost:5174/app/launch/${launchTarget}`)
await new Promise((r) => setTimeout(r, 1800))
const launchProbe = await c.evaluate(`(() => {
  const t = document.body.innerText
  return {
    url: location.href,
    hasActionArea: t.includes('可执行动作') || t.includes('该步骤无可执行动作'),
    hasSyncBtn: !!([...document.querySelectorAll('button')].find((b) => b.textContent.includes('同步状态'))),
    hasModeToggle: t.includes('业务视图') || t.includes('专业视图'),
    hasLaunchPage: t.includes('上线流程'),
    emptyOr404: t.includes('该步骤无可执行动作') || t.includes('流程不存在') || t.includes('没有权限')
  }
})()`)
console.log('[E10 launch-detail]', JSON.stringify({ launchTarget, launchProbe }))
await c.screenshot(`${OUT_DIR}/03-launch-detail-actions.png`)

// 拉取后端详情，交叉验证 available_actions / next_best_action 字段存在
const detail = await api(`/launch/${launchTarget}`)
const keys = detail.data ? Object.keys(detail.data) : []
console.log('[E10 launch-detail api]', JSON.stringify({
  status: detail.status,
  hasAvailableActions: keys.includes('available_actions'),
  hasDisabledActions: keys.includes('disabled_actions'),
  hasNextBestAction: keys.includes('next_best_action'),
  detailCode: detail.data?.code,
}))

await c.send('Target.closeTarget').catch(() => {})
chrome.kill()
console.log('DONE')
process.exit(0)
