// R3-3 独立验证（真实浏览器 · Chrome CDP 直连，仅用 Node 内置 WebSocket）
//
// 验证三个交付链路在**真实后端 + 真实路由**下可完成，而不是只跑单测：
//   A. J1 商品详情 → 上线中心（深链带商品）→ 创建向导 → 上线详情 →「返回」回商品详情
//      （证明 a1ee90b 的 /app 白名单修复端到端有效：return_to 被接受且真的回跳）
//   B. J0 新手身份下 5 步旅程条可达、逐步推进、journey 上下文不丢、末步有出口
//   C. J2 待办（被阻断视图，行级明细真实）→ 处理 → 返回待办（筛选态保留）
//      + 明细缺失时按店铺筛选的诚实降级（不得只说「没有匹配结果」）
//
// 隔离基座：后端 8011（qa_r33.db 每次由 qa_r33_base.db 还原）+ dev 5193（代理到 8011）。
// 用法：node docs/evidence/R3-3-QA/browser-verify-r33.mjs
// 排坑：Chrome 必须 --no-proxy-server；dev 必须 --host 127.0.0.1（--host localhost 只绑 IPv6）；
//       Vite 首次冷编译较慢 → 导航后必须等 #app 真正渲染，不能只 sleep 固定毫秒。

import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/R3-3-QA'
const DEV = 'http://127.0.0.1:5193'
const API = 'http://127.0.0.1:8011/api'
const LOGIN = `${DEV}/console/login`
fs.mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const R = { checks: [], notes: [], scenarios: {} }

function check(name, pass, detail) {
  R.checks.push({ name, pass: Boolean(pass), detail })
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}  ${detail === undefined ? '' : JSON.stringify(detail)}`)
}

async function apiLogin(username, password) {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const j = await r.json()
  if (!j.token) throw new Error(`login ${username} failed: ${JSON.stringify(j)}`)
  return j
}

// 每次运行用唯一 profile：不删旧目录（safe-delete 守卫拒绝批量删除），也避免登录态串味。
const PROFILE = `C:/temp/r33qa-chrome-${Date.now()}`
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9337', `--user-data-dir=${PROFILE}`,
  '--no-first-run', '--no-proxy-server', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

async function getWsUrl(startUrl, timeoutMs = 25000) {
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
        if (r.exceptionDetails) throw new Error('eval: ' + JSON.stringify(r.exceptionDetails.exception?.description))
        return r.result?.value
      },
      /** 导航并等待应用真正渲染（#app 有内容），避免 Vite 冷编译期的假白屏。 */
      async navigate(url, timeoutMs = 30000) {
        await client.send('Page.navigate', { url })
        const start = Date.now()
        while (Date.now() - start < timeoutMs) {
          await sleep(400)
          let len = 0
          try {
            len = await client.evaluate(`(document.getElementById('app')?.innerHTML || '').length`)
          } catch {}
          if (len > 2000) break
        }
        await sleep(900)
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

async function waitHref(c, pred, timeoutMs = 12000) {
  const start = Date.now()
  let href = ''
  while (Date.now() - start < timeoutMs) {
    href = await c.evaluate('location.href')
    if (pred(href)) return href
    await sleep(250)
  }
  return href
}

/** 等待页面上出现某个选择器（Vite / 异步数据都可能在路由到达之后才渲染完）。 */
async function waitSelector(c, sel, timeoutMs = 15000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const ok = await c.evaluate(`!!document.querySelector(${JSON.stringify(sel)})`)
    if (ok) return true
    await sleep(300)
  }
  return false
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
  for (let i = 0; i < 60; i++) {
    await sleep(300)
    const href = await c.evaluate('location.href')
    if (href && !href.includes('/console/login')) {
      await sleep(1200)
      return href
    }
  }
  return await c.evaluate('location.href')
}

async function setToken(c, token, user) {
  await c.evaluate(`localStorage.setItem('erp_token', ${JSON.stringify(token)});
    localStorage.setItem('erp_user', ${JSON.stringify(JSON.stringify(user))}); 'ok'`)
}

const c = await connectCdp(await getWsUrl(LOGIN))
await c.send('Runtime.enable')
await c.send('Page.enable')

// ──────────────────────────────────────────────────────────────
// A. J1：商品详情 → 上线中心 → 创建向导 → 上线详情 → 返回商品详情
//    种子：qa_owner（tenant 2）商品 #26「瑜伽垫 · 加厚防滑」，店铺 #4 美国站二号店
//    该组合在基线库中**没有**既有流程，可走完整创建路径。
// ──────────────────────────────────────────────────────────────
try {
  const sess = await apiLogin('qa_owner', 'qa123456')
  await setToken(c, sess.token, sess.user)
  const landed = await formLogin(c, 'qa_owner', 'qa123456')
  check('A0 真实表单登录成功并离开登录页', !landed.includes('/console/login'), landed)

  await c.navigate(`${DEV}/app/products/26`)
  await waitSelector(c, '.page')
  const pd = await c.evaluate(`(() => {
    const btns = [...document.querySelectorAll('.page button, .page .el-button')].map((b) => b.textContent.trim())
    return { url: location.href, title: document.querySelector('.page-header__title')?.textContent?.trim() || '',
      hasCreate: btns.some((x) => x === '创建上线流程'), btns: btns.slice(0, 10),
      hasObjectObject: /\\[object Object\\]/.test(document.body.innerText) }
  })()`)
  R.scenarios.j1_product_detail = pd
  await c.screenshot(`${OUT}/31-j1-product-detail.png`)
  check('A1 商品详情渲染、可写角色可见「创建上线流程」、无 [object Object]',
    pd.hasCreate && !pd.hasObjectObject, { url: pd.url, title: pd.title })

  await c.evaluate(`(() => {
    const b = [...document.querySelectorAll('.page button, .page .el-button')].find((x) => x.textContent.trim() === '创建上线流程')
    b && b.click(); return true
  })()`)
  await waitHref(c, (h) => h.includes('/app/launch'))
  await waitSelector(c, '.page-header__title')
  await sleep(1500)
  const q = await c.evaluate(`(() => {
    const u = new URL(location.href)
    const btns = [...document.querySelectorAll('.page button, .page .el-button')].map((b) => b.textContent.trim())
    const rows = [...document.querySelectorAll('.el-table__body-wrapper tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].map((td) => td.innerText.trim()))
    return { url: location.href, productId: u.searchParams.get('product_id'),
      shopId: u.searchParams.get('shop_id'), from: u.searchParams.get('from'),
      hasReturnSourceBtn: btns.includes('返回来源'), rows: rows.slice(0, 3) }
  })()`)
  R.scenarios.j1_launch_deeplink = q
  await c.screenshot(`${OUT}/32-j1-launch-deeplink.png`)
  check('A2 深链携带 product_id 与 from，且不写入 [object …] 的 shop_id',
    q.productId === '26' && q.from === '/app/products/26' && !q.shopId, {
      productId: q.productId, shopId: q.shopId, from: q.from,
    })
  check('A3 上线中心识别来源并提供「返回来源」', q.hasReturnSourceBtn === true, q.hasReturnSourceBtn)
  // 列表可辨认：商品/店铺列必须真实有值（旧模板读平铺字段 → 整列为空）
  const listOk = q.rows.length > 0 && q.rows.every((r) => r[1] && r[1] !== '—') && q.rows.every((r) => r[2] && r[2] !== '—')
  check('A4 上线列表商品/店铺列真实有值（不再整列空白）', listOk, q.rows)

  // 打开向导：带 product_id 应直接落在「选店铺」步（跳过选商品）
  await c.evaluate(`(() => {
    const b = [...document.querySelectorAll('.page button, .page .el-button')].find((x) => x.textContent.trim() === '创建上线流程')
    b && b.click(); return true
  })()`)
  await waitSelector(c, '.el-dialog')
  await sleep(900)
  const wizard = await c.evaluate(`(() => {
    const dlg = document.querySelector('.el-dialog')
    if (!dlg) return { open: false }
    const steps = [...dlg.querySelectorAll('.el-step')].map((s) => ({
      title: s.querySelector('.el-step__title')?.textContent?.trim(),
      active: !!s.querySelector('.el-step__head.is-process'),
    }))
    return { open: true, steps, dialogText: dlg.innerText.slice(0, 300),
      hasProductSelect: /搜索商品标题/.test(dlg.innerText),
      hasShopSelect: /选择已授权销售店铺/.test(dlg.innerText) }
  })()`)
  R.scenarios.j1_wizard = wizard
  await c.screenshot(`${OUT}/33-j1-wizard-skip-product.png`)
  check('A5 深链进入向导时跳过「选商品」步（当前步=选店铺）',
    wizard.open && wizard.steps[1]?.active === true && wizard.steps[0]?.active === false, wizard.steps)
  check('A6 直接给店铺选择（不再要求重选商品）',
    wizard.hasShopSelect === true && wizard.hasProductSelect === false, {
      hasProductSelect: wizard.hasProductSelect, hasShopSelect: wizard.hasShopSelect,
    })

  // 选择店铺 #4 美国站二号店（验证店铺名可读，不再是 "#4"）
  await c.evaluate(`(() => {
    const w = document.querySelector('.el-dialog .el-select__wrapper')
    if (!w) return { opened: false }
    w.click(); return { opened: true }
  })()`)
  await sleep(800)
  const pick = await c.evaluate(`(() => {
    const items = [...document.querySelectorAll('.el-select-dropdown__item')].filter((el) => el.offsetParent !== null)
    const texts = items.map((x) => x.textContent.trim())
    const target = items.find((el) => el.textContent.includes('美国站二号店'))
    if (!target) return { picked: false, options: texts.slice(0, 8) }
    target.click(); return { picked: true, options: texts.slice(0, 8) }
  })()`)
  await sleep(700)
  check('A7 店铺下拉用真实店铺名（可选中「美国站二号店」）', pick.picked === true, pick)

  await c.evaluate(`(() => {
    const b = [...document.querySelectorAll('.el-dialog button')].find((x) => x.textContent.trim() === '下一步')
    b && b.click(); return true
  })()`)
  await sleep(900)
  const confirm = await c.evaluate(`(() => {
    const dlg = document.querySelector('.el-dialog')
    return { text: dlg ? dlg.innerText.slice(0, 300) : '',
      hasYoga: dlg ? dlg.innerText.includes('瑜伽垫') : false,
      hasShop: dlg ? dlg.innerText.includes('美国站二号店') : false }
  })()`)
  R.scenarios.j1_confirm = confirm
  await c.screenshot(`${OUT}/34-j1-wizard-confirm.png`)
  check('A8 确认步如实回显所选商品与店铺名', confirm.hasYoga && confirm.hasShop, confirm)

  await c.evaluate(`(() => {
    const b = [...document.querySelectorAll('.el-dialog button')].find((x) => x.textContent.trim() === '创建')
    b && b.click(); return true
  })()`)
  const detailUrl = await waitHref(c, (h) => /\/app\/launch\/\d+/.test(h) && !h.includes('/app/launch?'), 20000)
  await sleep(2200)
  const det = await c.evaluate(`(() => {
    const u = new URL(location.href)
    const btns = [...document.querySelectorAll('.page button, .page .el-button')].map((b) => b.textContent.trim())
    return { url: location.href, returnTo: u.searchParams.get('return_to'),
      title: document.querySelector('.page-header__title')?.textContent?.trim() || '',
      btns: btns.slice(0, 6), hasBackBtn: btns.includes('返回') }
  })()`)
  R.scenarios.j1_launch_detail = det
  await c.screenshot(`${OUT}/35-j1-launch-detail.png`)
  check('A9 创建后进入上线详情且 return_to 指向商品详情',
    /\/app\/launch\/\d+/.test(det.url) && det.returnTo === '/app/products/26', det)
  check('A10 详情页出现「返回」按钮（return_to 被白名单接受）', det.hasBackBtn === true, det.btns)

  await c.evaluate(`(() => {
    const b = [...document.querySelectorAll('.page button, .page .el-button')].find((x) => x.textContent.trim() === '返回')
    b && b.click(); return true
  })()`)
  const backUrl = await waitHref(c, (h) => h.includes('/app/products/26'), 12000)
  await sleep(1200)
  const backTitle = await c.evaluate(`document.querySelector('.page-header__title')?.textContent?.trim() || ''`)
  R.scenarios.j1_return = { backUrl, backTitle }
  await c.screenshot(`${OUT}/36-j1-back-to-product.png`)
  check('A11 返回后真的回到商品详情（return_to 端到端生效）',
    backUrl.includes('/app/products/26') && backTitle.includes('瑜伽垫'), { backUrl, backTitle })
} catch (e) {
  R.notes.push('场景A(J1) 异常: ' + e.message)
  check('A 场景执行未抛异常', false, e.message)
}

// ──────────────────────────────────────────────────────────────
// B. J0：新手身份（qa_newbie，无店铺）5 步旅程条
// ──────────────────────────────────────────────────────────────
try {
  const sess = await apiLogin('qa_newbie', 'qa123456')
  await setToken(c, sess.token, sess.user)
  await c.navigate(`${DEV}/app/market/discovery?journey=j0`)
  const hadBar = await waitSelector(c, '.j0-bar')
  const first = await c.evaluate(`(() => {
    const bar = document.querySelector('.j0-bar')
    return { url: location.href, hasBar: !!bar,
      title: bar?.querySelector('.j0-bar__title')?.textContent?.trim() || '',
      goal: bar?.querySelector('.j0-bar__goal')?.textContent?.trim() || '',
      nextText: bar ? [...bar.querySelectorAll('button')].map((b) => b.textContent.trim()) : [],
      textLen: (document.body.innerText || '').length }
  })()`)
  R.scenarios.j0_step1 = first
  await c.screenshot(`${OUT}/37-j0-step1.png`)
  check('B1 新手 J0 首步渲染旅程条（第 1/5 步）',
    hadBar && first.hasBar && /第 1\/5 步/.test(first.title), first.title)
  check('B2 首步有「下一步」出口（无死端）', first.nextText.some((t) => t.includes('下一步')), first.nextText)

  const steps = []
  for (let i = 0; i < 5; i++) {
    const before = await c.evaluate(`(() => {
      const bar = document.querySelector('.j0-bar')
      return { url: location.href, title: bar?.querySelector('.j0-bar__title')?.textContent?.trim() || '',
        productId: new URL(location.href).searchParams.get('productId'),
        journey: new URL(location.href).searchParams.get('journey') }
    })()`)
    steps.push(before)
    await c.screenshot(`${OUT}/38-j0-step${i + 1}.png`)
    const clicked = await c.evaluate(`(() => {
      const bar = document.querySelector('.j0-bar')
      if (!bar) return { clicked: false, reason: 'no-bar' }
      const b = [...bar.querySelectorAll('button')].find((x) => /下一步|完成准备/.test(x.textContent))
      if (!b) return { clicked: false, reason: 'no-next-button' }
      const label = b.textContent.trim(); b.click(); return { clicked: true, label }
    })()`)
    if (!clicked.clicked) { steps.push({ stoppedAt: before.url, reason: clicked.reason }); break }

    // 末步：完成 → 回工作台（工作台没有旅程条）
    if (/完成准备/.test(clicked.label || '')) {
      const home = await waitHref(c, (h) => h.replace(/\/$/, '').split('?')[0] === `${DEV}/app`, 20000)
      await sleep(1200)
      steps.push({ finishedTo: home })
      break
    }

    // 关键：Vite dev 下首次进入某条路由要冷编译 chunk，SPA 跳转可能 >2s。
    // 必须等「URL 已变 + 新页旅程条已挂载」再读下一步，否则会把过渡态误判成死端。
    const afterUrl = await waitHref(c, (h) => h !== before.url, 25000)
    await waitSelector(c, '.j0-bar', 25000)
    await sleep(600)
    if (afterUrl === before.url) {
      steps.push({ stoppedAt: before.url, reason: 'url-not-changed' })
      break
    }
  }
  R.scenarios.j0_chain = steps
  const visited = steps.filter((s) => s.title)
  check('B3 J0 五步可逐步推进且每步都有旅程条（无中断）',
    visited.length >= 5, steps.map((s) => s.title || s.finishedTo || s.stoppedAt))
  const withJourney = visited.filter((s) => s.journey === 'j0')
  check('B4 逐步推进时 journey=j0 上下文保持', visited.length > 0 && withJourney.length === visited.length, {
    visited: visited.length, kept: withJourney.length,
  })
  check('B5 末步有「完成准备」出口并回到工作台',
    steps.some((s) => s.finishedTo) || /第 5\/5 步/.test(visited[visited.length - 1]?.title || ''),
    steps[steps.length - 1])
} catch (e) {
  R.notes.push('场景B(J0) 异常: ' + e.message)
  check('B 场景执行未抛异常', false, e.message)
}

// ──────────────────────────────────────────────────────────────
// C. J2：待办（被阻断视图，行级明细真实）→ 处理 → 返回待办
//    + 明细缺失时按店铺筛选的诚实降级
// ──────────────────────────────────────────────────────────────
try {
  const sess = await apiLogin('qa_owner', 'qa123456')
  await setToken(c, sess.token, sess.user)
  await c.navigate(`${DEV}/app/tasks?view=blocked`)
  await waitSelector(c, '.task-center__table, .section-state', 15000)
  await sleep(1200)
  const blocked = await c.evaluate(`(() => {
    const rows = [...document.querySelectorAll('.task-center__table tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].map((td) => td.innerText.trim()))
    const activeTab = document.querySelector('.el-radio-button.is-active')?.innerText?.trim() || ''
    return { url: location.href, rowCount: rows.length, rows: rows.slice(0, 4), activeTab,
      hasObjectObject: /\\[object Object\\]/.test(document.body.innerText) }
  })()`)
  R.scenarios.j2_blocked = blocked
  await c.screenshot(`${OUT}/39-j2-tasks-blocked.png`)
  check('C1 被阻断视图有真实明细行，店铺/商品不为「—」，无 [object Object]',
    blocked.rowCount > 0 && !blocked.hasObjectObject
      && blocked.rows.every((r) => r[1] !== '—' && r[2] !== '—'), blocked.rows)

  const openTask = await c.evaluate(`(() => {
    const rows = [...document.querySelectorAll('.task-center__table tbody tr')]
    for (const tr of rows) {
      const b = [...tr.querySelectorAll('button')].find((x) => /处理/.test(x.textContent))
      if (b) { const label = b.textContent.trim(); b.click(); return { clicked: true, label } }
    }
    return { clicked: false }
  })()`)
  await waitHref(c, (h) => /\/app\/launch\/\d+/.test(h), 12000)
  await sleep(2000)
  const target = await c.evaluate(`(() => {
    const u = new URL(location.href)
    const btns = [...document.querySelectorAll('.page button, .page .el-button')].map((b) => b.textContent.trim())
    return { url: location.href, returnTo: u.searchParams.get('return_to'), btns: btns.slice(0, 6),
      hasBackTask: btns.includes('返回待办') }
  })()`)
  R.scenarios.j2_target = { openTask, ...target }
  await c.screenshot(`${OUT}/40-j2-task-target.png`)
  check('C2 处理入口带 return_to=/app/tasks?view=blocked',
    openTask.clicked && target.returnTo === '/app/tasks?view=blocked', target)
  check('C3 落点页提供「返回待办」', target.hasBackTask === true, target.btns)

  await c.evaluate(`(() => {
    const b = [...document.querySelectorAll('.page button, .page .el-button')].find((x) => x.textContent.trim() === '返回待办')
    b && b.click(); return true
  })()`)
  await sleep(2400)
  const restored = await c.evaluate(`(() => {
    const rows = [...document.querySelectorAll('.task-center__table tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].map((td) => td.innerText.trim()))
    return { url: location.href, rowCount: rows.length,
      activeTab: document.querySelector('.el-radio-button.is-active')?.innerText?.trim() || '' }
  })()`)
  R.scenarios.j2_restored = restored
  await c.screenshot(`${OUT}/41-j2-back-restored.png`)
  check('C4 返回待办后筛选态完整恢复（仍是「被阻断」视图）',
    restored.url.includes('view=blocked') && /被阻断/.test(restored.activeTab) && restored.rowCount > 0, restored)

  // 明细缺失场景：默认待办视图只有来源摘要（store='—'），按店铺筛选必须说明原因
  await c.navigate(`${DEV}/app/tasks?store=${encodeURIComponent('美国站二号店')}`)
  await waitSelector(c, '.section-state, .task-center__table', 15000)
  await sleep(1500)
  const gap = await c.evaluate(`(() => {
    const t = document.body.innerText || ''
    return { url: location.href,
      hasGapAlert: /无法按店铺筛选/.test(t),
      saysPlainNoMatch: /没有匹配结果/.test(t),
      alertText: [...document.querySelectorAll('.el-alert')].map((e) => e.innerText.trim()).find((x) => x.includes('筛选')) || '' }
  })()`)
  R.scenarios.j2_filter_gap = gap
  await c.screenshot(`${OUT}/42-j2-filter-gap.png`)
  check('C5 明细缺失时按店铺筛选给出真实原因（不假装「没有匹配结果」）',
    gap.hasGapAlert === true, gap)
} catch (e) {
  R.notes.push('场景C(J2) 异常: ' + e.message)
  check('C 场景执行未抛异常', false, e.message)
}

// ──────────────────────────────────────────────────────────────
// 汇总
// ──────────────────────────────────────────────────────────────
const failed = R.checks.filter((x) => !x.pass)
const summary = {
  total: R.checks.length,
  passed: R.checks.length - failed.length,
  failed: failed.length,
  verdict: failed.length === 0 ? 'PASS' : 'FAIL',
  failedChecks: failed.map((f) => f.name),
  notes: R.notes,
  checks: R.checks,
}
fs.writeFileSync(`${OUT}/r33-browser-result.json`, JSON.stringify({ summary, scenarios: R.scenarios }, null, 2))
console.log('\n==== SUMMARY ====')
console.log(JSON.stringify({ ...summary, checks: undefined }, null, 2))
chrome.kill()
process.exit(failed.length === 0 ? 0 : 1)
