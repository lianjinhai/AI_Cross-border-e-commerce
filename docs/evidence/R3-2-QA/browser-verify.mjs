// R3-2 统一 QA 真实浏览器验收（Chrome CDP 直连；仅依赖 Node 内置 WebSocket）
// 隔离后端 8010（qa_r32.db）+ V9 dev 5175（代理到 8010）。
// 输出：docs/evidence/R3-2-QA/*.png + 控制台 JSON 结论。
// 用法：node docs/evidence/R3-2-QA/browser-verify.mjs
//
// 排坑：Chrome 必须 --no-proxy-server；dev 绑定 localhost，导航用 http://localhost:5175。

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
  '--headless=new', '--remote-debugging-port=9336', '--user-data-dir=C:/temp/r32qa-chrome',
  '--no-first-run', '--no-proxy-server', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const created = await fetch(`http://127.0.0.1:9336/json/new?${encodeURIComponent(startUrl)}`, { method: 'PUT' })
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
      async navigate(url, waitFor = null) {
        await client.send('Page.navigate', { url })
        const target = (waitFor || url).split('#')[0].replace(/\/$/, '')
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

async function formLogin(c, username, password) {
  await c.navigate(LOGIN)
  await c.evaluate(`(() => {
    const u = document.querySelector('input[data-test="login-username"]');
    const p = document.querySelector('input[type=password]');
    if (!u || !p) return false;
    u.value = ${JSON.stringify(username)}; u.dispatchEvent(new Event('input', { bubbles: true }));
    p.value = ${JSON.stringify(password)}; p.dispatchEvent(new Event('input', { bubbles: true }));
    const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('登'));
    btn && btn.click(); return true;
  })()`)
  for (let i = 0; i < 40; i++) {
    await sleep(300)
    const href = await c.evaluate('location.href')
    if (href && !href.includes('/console/login')) return href
  }
  return await c.evaluate('location.href')
}

const c = await connectCdp(await getWsUrl(LOGIN))
await c.send('Runtime.enable')
await c.send('Page.enable')

// ──────────────────────────────────────────────────────────────
// 场景 2：已有店铺卖家（STORE_OWNER）——真实表单登录 + 30 秒主线
// ──────────────────────────────────────────────────────────────
try {
  const t0 = Date.now()
  const landed = await formLogin(c, 'qa_owner', 'qa123456')
  await c.screenshot(`${OUT_DIR}/01-login-landed.png`)
  await c.navigate(`${DEV}/app`)
  const homeInfo = await c.evaluate(`(() => {
    const t = document.body.innerText
    const counters = [...document.querySelectorAll('.counter')].map((el) => ({
      label: el.querySelector('.counter__label')?.textContent.trim(),
      num: el.querySelector('.counter__num')?.textContent.trim(),
    }))
    const mt = document.querySelector('.main-task__title')
    return {
      url: location.href,
      hasLayer1: t.includes('今天最值得完成的一件事'),
      hasLayer2: t.includes('还需要处理'),
      hasLayer3: t.includes('当前经营状况'),
      hasLayer4: t.includes('AI 执行历史') && t.includes('完整经营数据'),
      counters,
      primaryTask: mt ? mt.textContent.trim() : null,
      hasGoBtn: !!document.querySelector('.main-task .el-button'),
      entryTag: document.querySelector('.page .el-tag')?.textContent.trim(),
      recommended: t.includes('唯一推荐入口'),
    }
  })()`)
  R.scenarios.storeowner_home = homeInfo
  await c.screenshot(`${OUT_DIR}/02-home-storeowner.png`)

  // 30 秒主线：点击主任务「去处理」→ 到达操作页
  const clickPath = []
  clickPath.push('打开 /app（经营首页）')
  const t1 = Date.now()
  const go = await c.evaluate(`(() => {
    const btn = [...document.querySelectorAll('.main-task button, .main-task .el-button')].find((b) => b.textContent.includes('去处理'))
    if (!btn) return { clicked: false }
    const txt = document.querySelector('.main-task__title')?.textContent.trim()
    btn.click(); return { clicked: true, primaryTask: txt }
  })()`)
  let targetHref = ''
  for (let i = 0; i < 40; i++) {
    await sleep(250)
    targetHref = await c.evaluate('location.href')
    if (targetHref && !targetHref.includes('/app?') && targetHref.replace(/\/$/, '').split('?')[0] !== `${DEV}/app`) break
  }
  await sleep(1200)
  targetHref = await c.evaluate('location.href')
  const elapsed = Date.now() - t1
  clickPath.push(`点击主任务「去处理」：${go.primaryTask}`)
  clickPath.push(`到达：${targetHref}`)
  const targetTitle = await c.evaluate(`document.querySelector('.page-header__title, h1, .el-card__header')?.textContent?.trim() || document.title`)
  R.scenarios.mainline_30s = { clicked: go, elapsedMs: elapsed, targetHref, targetTitle, clickPath }
  await c.screenshot(`${OUT_DIR}/03-mainline-target.png`)

  // 四层展开（AI 历史 + BI 明细）
  await c.navigate(`${DEV}/app`)
  await c.evaluate(`[...document.querySelectorAll('.el-collapse-item__header')].forEach((h) => h.click()); true`)
  await sleep(1500)
  const expanded = await c.evaluate(`(() => {
    const t = document.body.innerText
    return { hasAiTable: t.includes('运行') || t.includes('没有已完成的 AI 运行'),
      hasBi: t.includes('热销商品') || t.includes('经营明细需财务读权限') }
  })()`)
  R.scenarios.home_layers_expanded = expanded
  await c.screenshot(`${OUT_DIR}/04-home-layers-expanded.png`)
} catch (e) {
  R.notes.push('场景2 异常: ' + e.message)
}

// ──────────────────────────────────────────────────────────────
// 场景 4：TaskCenter 统一待办（默认/等待外部/受阻/已完成/筛选/返回闭环）
// ──────────────────────────────────────────────────────────────
try {
  await c.navigate(`${DEV}/app/tasks`)
  const tcDefault = await c.evaluate(`(() => {
    const t = document.body.innerText
    const rows = [...document.querySelectorAll('.el-table__body-wrapper tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].slice(0, 8).map((td) => td.innerText.trim()))
    const views = [...document.querySelectorAll('.el-radio-button__inner')].map((l) => l.textContent.trim())
    return { url: location.href, hasTable: !!document.querySelector('.el-table'), views,
      rowCount: rows.length, rows: rows.slice(0, 10), gapNote: (document.querySelector('.gap-note')?.innerText || '') }
  })()`)
  R.scenarios.tasks_default = tcDefault
  await c.screenshot(`${OUT_DIR}/05-tasks-default.png`)

  // 切「等待外部」→ URL query
  const switchView = async (label, shot) => {
    const res = await c.evaluate(`(() => {
      const el = [...document.querySelectorAll('.el-radio-button__inner')].find((l) => l.textContent.includes(${JSON.stringify(label)}))
      if (!el) return { clicked: false }
      el.click(); return { clicked: true }
    })()`)
    await sleep(1300)
    const after = await c.evaluate(`(() => {
      const rows = [...document.querySelectorAll('.el-table__body-wrapper tbody tr')].map((tr) =>
        [...tr.querySelectorAll('td')].slice(0, 8).map((td) => td.innerText.trim()))
      return { url: location.href, query: location.search, rowCount: rows.length, rows: rows.slice(0, 10) }
    })()`)
    if (shot) await c.screenshot(`${OUT_DIR}/${shot}`)
    return { switchView: res, after }
  }
  R.scenarios.tasks_waiting = await switchView('等待外部', '06-tasks-waiting-cross-store.png')
  R.scenarios.tasks_blocked = await switchView('受阻', '07-tasks-blocked.png')
  R.scenarios.tasks_done = await switchView('已完成', '08-tasks-done.png')

  // 回到等待外部，按 store 过滤（跨店不合并核验）
  await switchView('等待外部', null)
  const storeFilter = await c.evaluate(`(() => {
    const inputs = [...document.querySelectorAll('.filters input')]
    const si = inputs.find((i) => i.placeholder === '店铺')
    if (!si) return { typed: false }
    si.focus(); si.value = '美国站二号店'; si.dispatchEvent(new Event('input', { bubbles: true }));
    si.dispatchEvent(new Event('change', { bubbles: true })); si.blur(); return { typed: true }
  })()`)
  await sleep(1300)
  const afterStore = await c.evaluate(`(() => {
    const rows = [...document.querySelectorAll('.el-table__body-wrapper tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].slice(0, 8).map((td) => td.innerText.trim()))
    return { url: location.href, query: location.search, rowCount: rows.length, rows }
  })()`)
  R.scenarios.tasks_store_filter = { storeFilter, afterStore }
  await c.screenshot(`${OUT_DIR}/09-tasks-store-filter.png`)

  // 闭环：点击「处理」→ 目标页带 return_to → 返回恢复筛选
  const beforeClick = await c.evaluate('location.href')
  const openTask = await c.evaluate(`(() => {
    const btn = [...document.querySelectorAll('.el-table__body-wrapper tbody tr button')].find((b) => b.textContent.includes('处理'))
    if (!btn) return { clicked: false }
    btn.click(); return { clicked: true }
  })()`)
  await sleep(1600)
  const target = await c.evaluate('location.href')
  await c.screenshot(`${OUT_DIR}/10-task-open-target.png`)
  await c.evaluate('history.back(); true')
  await sleep(1600)
  const restored = await c.evaluate('location.href')
  R.scenarios.tasks_closed_loop = { beforeClick, openTask, target, restored }
} catch (e) {
  R.notes.push('场景4 异常: ' + e.message)
}

// ──────────────────────────────────────────────────────────────
// 场景 3/6：画像入口差异 NEW_USER vs STORE_OWNER（不同账号）
// ──────────────────────────────────────────────────────────────
try {
  const probe = async (user, pass, shot) => {
    const sess = await apiLogin(user, pass)
    await c.navigate(`${DEV}/console/login`)  // 先离开，避免残留
    await setToken(c, sess.token, sess.user)
    await c.navigate(`${DEV}/app`)
    const info = await c.evaluate(`(() => {
      const t = document.body.innerText
      const guide = [...document.querySelectorAll('.guide-steps li span')].map((s) => s.textContent.trim())
      return {
        url: location.href,
        entryTag: document.querySelector('.page .el-tag')?.textContent.trim(),
        recommendedBtn: document.querySelector('.el-card .block')?.textContent.trim(),
        guideSteps: guide,
        hint: document.querySelector('.el-card p.hint')?.textContent.trim(),
        stage: [...document.querySelectorAll('.stage-line .el-tag')].map((e) => e.textContent.trim())[0],
        primaryTask: document.querySelector('.main-task__title')?.textContent.trim()
          || document.querySelector('.main-task--empty .hint')?.textContent.trim(),
        counters: [...document.querySelectorAll('.counter')].map((el) => el.querySelector('.counter__num')?.textContent.trim()),
        partialBanner: !!document.querySelector('.partial-banner, .el-alert'),
        sidebar: [...document.querySelectorAll('.el-menu-item, .el-sub-menu__title')].map((e) => e.textContent.trim()).filter(Boolean).slice(0, 12),
      }
    })()`)
    if (shot) await c.screenshot(`${OUT_DIR}/${shot}`)
    return info
  }
  R.scenarios.profile_newuser = await probe('qa_newbie', 'qa123456', '11-home-newuser.png')
  R.scenarios.profile_noshop = await probe('qa_noshop', 'qa123456', '12-home-noshop.png')
  R.scenarios.profile_compliance = await probe('qa_compliance', 'qa123456', '13-home-compliance-partial.png')
  R.scenarios.profile_readonly = await probe('qa_viewer', 'qa123456', '14-home-readonly.png')
} catch (e) {
  R.notes.push('场景3/6 异常: ' + e.message)
}

// ──────────────────────────────────────────────────────────────
// 场景 10：全部工具入口展开（可到所有叶子，无死链）
// ──────────────────────────────────────────────────────────────
try {
  const sess = await apiLogin('qa_owner', 'qa123456')
  await c.navigate(`${DEV}/console/login`)
  await setToken(c, sess.token, sess.user)
  await c.navigate(`${DEV}/app`)
  const tools = await c.evaluate(`(() => {
    const titles = [...document.querySelectorAll('.el-sub-menu__title')]
    const toolsTitle = titles.find((t) => t.textContent.includes('全部工具'))
    if (!toolsTitle) return { found: false, titles: titles.map((t) => t.textContent.trim()) }
    toolsTitle.click(); return { found: true }
  })()`)
  await sleep(1000)
  const leaves = await c.evaluate(`(() => {
    const items = [...document.querySelectorAll('.el-menu-item')].map((e) => e.textContent.trim()).filter(Boolean)
    const hrefs = [...document.querySelectorAll('.el-menu-item')].length
    return { leafCount: hrefs, leaves: items }
  })()`)
  R.scenarios.tools_expanded = { tools, leaves }
  await c.screenshot(`${OUT_DIR}/15-tools-expanded.png`)
} catch (e) {
  R.notes.push('场景10 异常: ' + e.message)
}

// ──────────────────────────────────────────────────────────────
// 场景 9：移动端宽度（390 / 768）
// ──────────────────────────────────────────────────────────────
try {
  await c.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true })
  await c.navigate(`${DEV}/app`)
  const mob = await c.evaluate(`(() => ({ url: location.href, hasPrimary: !!document.querySelector('.main-task__title'),
    bodyScrollW: document.documentElement.scrollWidth, viewport: window.innerWidth }))()`)
  R.scenarios.mobile_390_home = mob
  await c.screenshot(`${OUT_DIR}/16-mobile-390-home.png`)
  await c.navigate(`${DEV}/app/tasks`)
  const mobTasks = await c.evaluate(`(() => ({ hasTable: !!document.querySelector('.el-table') || !!document.querySelector('.el-table__empty-text') }))()`)
  R.scenarios.mobile_390_tasks = mobTasks
  await c.screenshot(`${OUT_DIR}/17-mobile-390-tasks.png`)
  await c.send('Emulation.setDeviceMetricsOverride', { width: 768, height: 1024, deviceScaleFactor: 1, mobile: false })
  await c.navigate(`${DEV}/app`)
  await c.screenshot(`${OUT_DIR}/18-mobile-768-home.png`)
  R.scenarios.mobile_768_home = await c.evaluate(`(() => ({ viewport: window.innerWidth }))()`)
  await c.send('Emulation.clearDeviceMetricsOverride')
} catch (e) {
  R.notes.push('场景9 异常: ' + e.message)
}

// ──────────────────────────────────────────────────────────────
// 交叉核对：后端原始响应（跨店去重 / 计数口径 / partial 语义）
// ──────────────────────────────────────────────────────────────
try {
  const sess = await apiLogin('qa_owner', 'qa123456')
  const h = { Authorization: `Bearer ${sess.token}` }
  const todo = await (await fetch(`${API}/workbench/todo`, { headers: h })).json()
  const ov = await (await fetch(`${API}/workbench/overview`, { headers: h })).json()
  R.api_cross_check = {
    todoCounts: todo.counts, todoSources: todo.sources, todoPartial: todo.partial,
    inProgress: (ov.sections?.in_progress || []).map((r) => ({
      product: r.product?.title, store: r.store?.name, status: r.execution_status })),
    metrics: { gmv: ov.sections?.metrics?.gmv, orders: ov.sections?.metrics?.orders, profit: ov.sections?.metrics?.contribution_profit },
    signals: ov.signals, sources: ov.sources, partial: ov.partial,
  }
} catch (e) {
  R.notes.push('交叉核对异常: ' + e.message)
}

console.log('\n===== R3-2-QA RESULT =====')
console.log(JSON.stringify(R, null, 2))
await c.send('Target.closeTarget').catch(() => {})
chrome.kill()
console.log('DONE')
process.exit(0)
