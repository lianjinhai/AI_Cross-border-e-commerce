const token = await (await fetch('http://127.0.0.1:8000/api/auth/login', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'admin', password: 'admin123' }),
}).then((r) => r.json())).token

const j = async (p) => (await fetch(`http://127.0.0.1:8000/api${p}`, { headers: { Authorization: `Bearer ${token}` } })).json()

const launch = await j('/launch?page_num=1&page_size=5')
console.log('launch keys:', Object.keys(launch))
console.log('launch.items?.length:', launch.items?.length, 'total:', launch.total)
console.log('first item id:', launch.items?.[0]?.id, 'keys:', launch.items?.[0] ? Object.keys(launch.items[0]).slice(0, 12) : null)

const launchId = launch.items?.[0]?.id
if (launchId) {
  const d = await j(`/launch/${launchId}`)
  console.log('detail keys:', Object.keys(d))
  console.log('available_actions:', (d.available_actions || []).length, 'disabled_actions:', (d.disabled_actions || []).length)
  console.log('next_best_action:', JSON.stringify(d.next_best_action))
  console.log('steps[0].available_actions:', JSON.stringify((d.steps?.[0]?.available_actions || []).slice(0, 3)))
}

// product with assets: find one that has assets for a sales shop
const products = await j('/products?page_num=1&page_size=20')
let found = null
for (const p of products.items || []) {
  // try channels to find a sales shop with market
  const ch = await j(`/products/${p.id}/channels`).catch(() => null)
  const shops = (ch?.channels || []).map((c) => c.shop).filter((s) => s.market)
  if (shops.length) { found = { productId: p.id, shops: shops.slice(0, 3) }; break }
}
console.log('product with sales-shop market:', JSON.stringify(found))
if (found) {
  const assets = await j(`/products/${found.productId}/assets?shop_id=${found.shops[0].id}`)
  console.log('assets status items:', assets.items?.length ?? assets.detail)
}
