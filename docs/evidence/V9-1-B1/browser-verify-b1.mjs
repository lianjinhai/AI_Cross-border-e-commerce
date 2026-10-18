// B1 独立验证（真实浏览器 · Chrome CDP 直连，仅用 Node 内置 WebSocket）
// 验证 commit 2391b90 的视觉/导航 claim（真实后端 + 真实路由，不读源码判定）：
//   A. 侧栏恰好 5 个一级入口，标签 = 我的生意/我的商品/我的订单/我的收益/全部工具
//   B. 默认仅当前路由所在组展开；首屏可见 5 行（一级条目）
//   C. 点击「我的商品」展开其子集；子集「商品库」导航到 /app/products
//   D. 侧栏背景 = rgb(12,38,84)；激活项白字 + rgb(36,90,156) 底
//   E. 主按钮 = rgb(35,107,189)，hover 为同色相更浅的 tint（非 #409EFF 系）
//   F. 旧深链 /products /orders /finance /launch → /app/...（非 404）
//   G. 390px 宽侧栏收起（测 aside 宽度），主操作不被裁切
// 隔离基座：后端 8011（qa_b1.db）+ dev 5193（代理 8011）。
// 用法：node docs/evidence/V9-1-B1/browser-verify-b1.mjs

import { spawn } from 'node:child_process'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT = 'F:/Desktop/个人文件/软件开发计划/AI-电商ERP/docs/evidence/V9-1-B1'
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

const PROFILE = `C:/temp/b1qa-chrome-${Date.now()}`
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
        if (r.exceptionDetails) throw new Error('eval: ' + JSON.stringify(r.exceptionDetails.exception?.description))
        return r.result?.value
      },
      async navigate(url, timeoutMs = 30000) {
        await client.send('Page.navigate', { url })
        const start = Date.now()
        while (Date.now() - start < timeoutMs) {
          await sleep(400)
          let len = 0
          try { len = await client.evaluate(`(document.getElementById('app')?.innerHTML || '').length`) } catch {}
          if (len > 2000) break
        }
        await sleep(900)
      },
      async screenshot(file) {
        const r = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
        fs.writeFileSync(file, Buffer.from(r.data, 'base64'))
        console.log(`[shot] ${file}`)
      },
      async setViewport(w, h) {
        await client.send('Emulation.setDeviceMetricsOverride',
          { width: w, height: h, deviceScaleFactor: 1, mobile: false, screenWidth: w, screenHeight: h })
        await sleep(700)
      },
      async hover(x, y) {
        await client.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y })
        await sleep(500)
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
    const u = document.querySelector('input[data-test="login-username"]') || document.querySelector('input[type=text],input[type=email]');
    const p = document.querySelector('input[type=password]');
    if (!u || !p) return false;
    u.value = ${JSON.stringify(username)}; u.dispatchEvent(new Event('input', { bubbles: true }));
    p.value = ${JSON.stringify(password)}; p.dispatchEvent(new Event('input', { bubbles: true }));
    const btn = [...document.querySelectorAll('button')].find((b) => /登|录|进/.test(b.textContent));
    btn && btn.click(); return true;
  })()`)
  for (let i = 0; i < 60; i++) {
    await sleep(300)
    const href = await c.evaluate('location.href')
    if (href && !href.includes('/console/login')) { await sleep(1200); return href }
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
await c.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

// ──────────────────────────────────────────────────────────────
// 登录（复用 R3-3 的 demo 凭据 qa_owner）
// ──────────────────────────────────────────────────────────────
try {
  const sess = await apiLogin('qa_owner', 'qa123456')
  await setToken(c, sess.token, sess.user)
  const landed = await formLogin(c, 'qa_owner', 'qa123456')
  check('Z0 真实表单登录成功并进入 /app 空间', landed.includes('/app'), landed)
  await c.navigate(`${DEV}/app`)
  await waitSelector(c, '.shell-menu', 15000)
  await sleep(800)
} catch (e) {
  R.notes.push('登录异常: ' + e.message)
  check('Z0 登录未抛异常', false, e.message)
}

// ──────────────────────────────────────────────────────────────
// A + B + D（默认 1440 首屏，未点击任何菜单）
// ──────────────────────────────────────────────────────────────
try {
  const a = await c.evaluate(`(() => {
    const titles = [...document.querySelectorAll('.shell-menu .el-sub-menu__title')];
    const visibleTitles = titles.filter(t => t.offsetParent !== null);
    const labels = visibleTitles.map(t => (t.querySelector('span')?.textContent || '').trim()).filter(Boolean);
    const leaves = [...document.querySelectorAll('.shell-menu .el-menu-item')];
    const visibleLeaves = leaves.filter(l => l.offsetParent !== null);
    const openGroups = [...document.querySelectorAll('.shell-menu .el-sub-menu.is-opened')].map(g => g.querySelector('.el-sub-menu__title span')?.textContent?.trim());
    const openedTitles = [...document.querySelectorAll('.shell-menu .el-sub-menu')]
      .filter(g => { const title = g.querySelector('.el-sub-menu__title'); const box = title?.getBoundingClientRect(); return box && box.height > 0; })
      .length;
    return {
      topLevelCount: titles.length,
      visibleTopLevelCount: visibleTitles.length,
      labels,
      visibleLeafCount: visibleLeaves.length,
      visibleLeafLabels: visibleLeaves.map(l => (l.querySelector('.el-tooltip__trigger span, span')?.textContent || l.textContent || '').trim()),
      openGroupCount: openGroups.length,
      openGroups,
    }
  })()`)
  R.scenarios.sidebar_firstpaint = a
  check('A 侧栏恰好 5 个一级入口', a.topLevelCount === 5 && a.visibleTopLevelCount === 5,
    { topLevelCount: a.topLevelCount, visibleTopLevelCount: a.visibleTopLevelCount })
  const expectedLabels = ['我的生意', '我的商品', '我的订单', '我的收益', '全部工具']
  const labelsMatch = JSON.stringify(a.labels) === JSON.stringify(expectedLabels)
  check('A 标签精确 = 我的生意/我的商品/我的订单/我的收益/全部工具',
    labelsMatch, { observed: a.labels })
  R.scenarios.sidebar_labels = a.labels
  // B：首屏可见行数 = 一级条目数（5）。展开组仅当前路由所在组。
  check('B 首屏可见一级行数 = 5', a.visibleTopLevelCount === 5, { visibleTopLevelCount: a.visibleTopLevelCount })
  // 默认 /app → 仅 mybiz 组展开；其它组收起 → 可见叶子应仅 mybiz 的 2 个
  check('B 默认仅当前路由所在组展开（openGroup 数=1）', a.openGroupCount === 1,
    { openGroupCount: a.openGroupCount, openGroups: a.openGroups })
  check('B 过期叶子（商品库等）默认不可见（visible 叶子=2）', a.visibleLeafCount === 2,
    { visibleLeafCount: a.visibleLeafCount, visibleLeafLabels: a.visibleLeafLabels })

  // D：侧栏背景 + 激活项（/app 下「经营首页」激活）
  const d = await c.evaluate(`(() => {
    const aside = document.querySelector('.shell__aside');
    const active = document.querySelector('.shell-menu .el-menu-item.is-active');
    const cs = (el, p) => el ? getComputedStyle(el)[p] : null;
    return {
      sidebarBg: cs(aside, 'backgroundColor'),
      activeText: cs(active, 'color'),
      activeBg: cs(active, 'backgroundColor'),
      activeLabel: active?.textContent?.trim() || null,
      // 直接解析令牌变量，便于交叉核对
      tokenNavy: getComputedStyle(document.documentElement).getPropertyValue('--v91-navy-900').trim(),
      tokenActiveBg: getComputedStyle(document.documentElement).getPropertyValue('--v91-sidebar-active-bg').trim(),
      tokenActiveText: getComputedStyle(document.documentElement).getPropertyValue('--v91-sidebar-active-text').trim(),
    }
  })()`)
  R.scenarios.colors_sidebar = d
  check('D 侧栏背景 = rgb(12, 38, 84)', d.sidebarBg === 'rgb(12, 38, 84)',
    { observed: d.sidebarBg, token: d.tokenNavy })
  check('D 激活项文字 = rgb(255, 255, 255) 白', d.activeText === 'rgb(255, 255, 255)',
    { observed: d.activeText, token: d.tokenActiveText })
  check('D 激活项背景 = rgb(36, 90, 156)', d.activeBg === 'rgb(36, 90, 156)',
    { observed: d.activeBg, token: d.tokenActiveBg, activeLabel: d.activeLabel })
} catch (e) {
  R.notes.push('场景A/B/D 异常: ' + e.message)
  check('A/B/D 场景未抛异常', false, e.message)
}

// ──────────────────────────────────────────────────────────────
// 截图四视口（1440/1366/768/390），其中 390 同时做 G 测量
// ──────────────────────────────────────────────────────────────
try {
  await c.navigate(`${DEV}/app`); await waitSelector(c, '.shell-menu', 10000); await sleep(600)
  await c.setViewport(1440, 900); await c.screenshot(`${OUT}/v1-app-1440x900.png`)
  await c.setViewport(1366, 768); await c.screenshot(`${OUT}/v2-app-1366x768.png`)
  await c.setViewport(768, 1024); await c.screenshot(`${OUT}/v3-app-768x1024.png`)
  await c.setViewport(390, 844)
  await c.screenshot(`${OUT}/v4-app-390x844.png`)
  // G：390px 测量侧栏宽度 + 主内容宽度（验证未裁切）
  const g = await c.evaluate(`(() => {
    const aside = document.querySelector('.shell__aside')
    const asideW = aside ? Math.round(aside.getBoundingClientRect().width) : null
    const menu = document.querySelector('.shell-menu')
    const collapsed = menu ? menu.className.includes('el-menu--collapse') : null
    const main = document.querySelector('.shell__main')
    const mainW = main ? Math.round(main.getBoundingClientRect().width) : null
    const win = window.innerWidth
    return { win, asideW, collapsed, mainW,
      sidebarCollapsedExpected: asideW <= 80 }
  })()`)
  R.scenarios.g_390 = g
  check('G 390px 侧栏已收起（aside 宽度 ≤80px）', g.asideW !== null && g.asideW <= 80,
    { asideW: g.asideW, collapsed: g.collapsed })
  check('G 390px 主内容区未被裁切（mainW>0 且占满视口）',
    g.mainW !== null && g.mainW > 0 && g.mainW >= g.win - 90,
    { win: g.win, mainW: g.mainW, asideW: g.asideW })
} catch (e) {
  R.notes.push('截图/G 异常: ' + e.message)
  check('截图/G 未抛异常', false, e.message)
}

// ──────────────────────────────────────────────────────────────
// C：点击「我的商品」展开子集 → 「商品库」导航 /app/products
// ──────────────────────────────────────────────────────────────
try {
  await c.setViewport(1440, 900)
  await c.navigate(`${DEV}/app`); await waitSelector(c, '.shell-menu', 10000); await sleep(600)
  const beforeLeaves = await c.evaluate(`[...document.querySelectorAll('.shell-menu .el-menu-item')].filter(l => l.offsetParent !== null).length`)
  // 点击「我的商品」标题
  const clicked = await c.evaluate(`(() => {
    const t = [...document.querySelectorAll('.shell-menu .el-sub-menu__title')]
      .find(el => (el.querySelector('span')?.textContent || '').trim() === '我的商品')
    if (!t) return { ok: false }
    t.click(); return { ok: true }
  })()`)
  await sleep(1200)
  const after = await c.evaluate(`(() => {
    const leaves = [...document.querySelectorAll('.shell-menu .el-menu-item')].filter(l => l.offsetParent !== null)
    const goodsVisible = leaves.some(l => (l.textContent || '').includes('商品库'))
    const goodsCount = leaves.filter(l => {
      const grp = l.closest('.el-sub-menu')
      return grp && (grp.querySelector('.el-sub-menu__title span')?.textContent || '').trim() === '我的商品'
    }).length
    return { leafCount: leaves.length, goodsVisible, goodsCount }
  })()`)
  R.scenarios.c_expand = { beforeLeaves, clicked, after }
  check('C 点击前「商品库」不可见（过期叶子隐藏）', beforeLeaves === 2, { beforeLeaves })
  check('C 点击「我的商品」后其 4 个子集可见（含商品库）',
    clicked.ok && after.goodsVisible && after.goodsCount === 4, after)
  // 点击「商品库」导航
  await c.evaluate(`(() => {
    const l = [...document.querySelectorAll('.shell-menu .el-menu-item')]
      .find(el => (el.textContent || '').includes('商品库'))
    l && l.click(); return true
  })()`)
  const goodsUrl = await waitHref(c, (h) => h.includes('/app/products'), 12000)
  await sleep(1000)
  const onProducts = await c.evaluate(`location.href.includes('/app/products') && !!document.querySelector('.shell-menu')`)
  R.scenarios.c_nav = { goodsUrl, onProducts }
  check('C 「商品库」导航到 /app/products', onProducts === true, { goodsUrl })
} catch (e) {
  R.notes.push('场景C 异常: ' + e.message)
  check('C 场景未抛异常', false, e.message)
}

// ──────────────────────────────────────────────────────────────
// E：主按钮颜色 + hover（同色相更浅 tint，非 #409EFF 系）
// ──────────────────────────────────────────────────────────────
try {
  // 找一个主按钮（优先 /app/products 的「新增」，否则当前页）
  let primaryPath = null
  for (const p of ['/app/products', '/app/orders', '/app']) {
    await c.navigate(`${DEV}${p}`); await waitSelector(c, '.el-button--primary', 8000).catch(() => {})
    const has = await c.evaluate(`!!document.querySelector('.el-button--primary')`)
    if (has) { primaryPath = p; break }
  }
  const e = await c.evaluate(`(() => {
    const b = document.querySelector('.el-button--primary')
    if (!b) return { found: false }
    const cs = getComputedStyle(b)
    const rect = b.getBoundingClientRect()
    return { found: true, label: b.textContent.trim(),
      bg: cs.backgroundColor, color: cs.color,
      cx: Math.round(rect.left + rect.width / 2), cy: Math.round(rect.top + rect.height / 2),
      tokenPrimary: getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim(),
      tokenElPrimary: getComputedStyle(document.documentElement).getPropertyValue('--el-color-primary').trim() }
  })()`)
  if (!e.found) {
    check('E 找到主按钮', false, { primaryPath })
  } else {
    await c.hover(e.cx, e.cy)
    const cmp = await c.evaluate(`(() => {
      const rgbToHsl = (r,g,b)=>{r/=255;g/=255;b/=255;const mx=Math.max(r,g,b),mn=Math.min(r,g,b);let h,s,l=(mx+mn)/2;if(mx===mn){h=0;s=0}else{const d=mx-mn;s=l>0.5?d/(2-mx-mn):d/(mx+mn);switch(mx){case r:h=(g-b)/d+(g<b?6:0);break;case g:h=(b-r)/d+2;break;default:h=(r-g)/d+4}h/=6}return{h:h*360,s:s*100,l:l*100}}
      const parse = (str) => { const m = str.match(/\\d+/g); return m ? m.slice(0,3).map(Number) : null }
      const base = parse(${JSON.stringify(e.bg)})
      const hoverBg = getComputedStyle(document.querySelector('.el-button--primary')).backgroundColor
      const hov = parse(hoverBg)
      if (!base || !hov) return { ok: false, hoverBg }
      const bH = rgbToHsl(...base), hH = rgbToHsl(...hov)
      const hueDelta = Math.abs(bH.h - hH.h)
      const lighter = hH.l > bH.l
      return { ok: true, baseRGB: base, hoverRGB: hov, hoverBg, baseHue: Math.round(bH.h), hoverHue: Math.round(hH.h),
        hueDelta: Math.round(hueDelta), baseLight: Math.round(bH.l), hoverLight: Math.round(hH.l), lighter,
        sameHueFamily: hueDelta < 18 && lighter }
    })()`)
    R.scenarios.e_primary = { ...e, cmp }
    check('E 主按钮 = rgb(35, 107, 189)', e.bg === 'rgb(35, 107, 189)',
      { observed: e.bg, token: e.tokenElPrimary })
    check('E hover 为同色相更浅 tint（非 #409EFF 系）',
      cmp.ok && cmp.sameHueFamily === true, cmp)
  }
} catch (e2) {
  R.notes.push('场景E 异常: ' + e2.message)
  check('E 场景未抛异常', false, e2.message)
}

// ──────────────────────────────────────────────────────────────
// F：旧深链重定向（非 404）
// ──────────────────────────────────────────────────────────────
try {
  const legacy = [
    { from: '/products', expect: '/app/products' },
    { from: '/orders', expect: '/app/orders' },
    { from: '/finance', expect: '/app/analytics/finance' },
    { from: '/launch', expect: '/app/launch' },
  ]
  const results = []
  for (const rule of legacy) {
    await c.navigate(`${DEV}${rule.from}`)
    const landed = await waitHref(c, (h) => h.includes(rule.expect), 12000)
    const is404 = await c.evaluate(`/404|页面不存在|Not Found/.test(document.body.innerText) && !location.href.includes(${JSON.stringify(rule.expect)})`)
    const ok = landed.includes(rule.expect) && !is404
    results.push({ from: rule.from, landed, expect: rule.expect, ok })
    check(`F 旧深链 ${rule.from} → ${rule.expect}`, ok, { landed })
  }
  R.scenarios.deep_links = results
} catch (e) {
  R.notes.push('场景F 异常: ' + e.message)
  check('F 场景未抛异常', false, e.message)
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
fs.writeFileSync(`${OUT}/b1-browser-result.json`, JSON.stringify({ summary, scenarios: R.scenarios }, null, 2))
console.log('\n==== SUMMARY ====')
console.log(JSON.stringify({ ...summary, checks: undefined }, null, 2))
chrome.kill()
process.exit(failed.length === 0 ? 0 : 1)
