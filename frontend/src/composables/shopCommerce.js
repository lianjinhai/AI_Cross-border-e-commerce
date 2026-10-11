export function shopCommerceFields(shop = {}) {
  return Object.fromEntries(['market', 'store_type', 'account_type', 'business_mode', 'fulfillment_mode']
    .map(key => [key, shop[key] || '']))
}
