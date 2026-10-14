const token = await (await fetch('http://127.0.0.1:8000/api/auth/login', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'admin', password: 'admin123' }),
}).then((r) => r.json())).token

const req = async (p, opt = {}) => {
  const r = await fetch(`http://127.0.0.1:8000/api${p}`, {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...opt.headers },
    method: opt.method, body: opt.body,
  })
  return { status: r.status, data: await r.json().catch(() => null) }
}

const shops = await req('/shops')
const salesWithMarket = (shops.data?.items || []).filter((s) => s.role === 'sales' && s.market)
console.log('shops total:', shops.data?.items?.length, 'sales with market:', salesWithMarket.map((s) => ({ id: s.id, market: s.market, platform: s.platform })))

const products = await req('/products?page_num=1&page_size=5')
const pid = products.data?.items?.[0]?.id
console.log('productId:', pid)

if (salesWithMarket.length && pid) {
  const create = await req('/launch', { method: 'POST', body: JSON.stringify({ product_id: pid, shop_id: salesWithMarket[0].id }), headers: { 'Idempotency-Key': `probe-${Date.now()}` } })
  console.log('create launch status:', create.status, 'id:', create.data?.id)
  if (create.data?.id) {
    const d = await req(`/launch/${create.data.id}`)
    console.log('detail keys:', Object.keys(d.data || {}))
    console.log('available_actions:', (d.data?.available_actions || []).length, 'disabled:', JSON.stringify((d.data?.disabled_actions || []).slice(0, 3)))
  }
}
