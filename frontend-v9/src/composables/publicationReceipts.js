import api from '../shared/api/client'

export async function queryPublicationReceipt(receipt) {
  if (!receipt?.can_query_submission || !receipt.shop_id || !receipt.external_id) {
    throw new Error('请选择具有状态查询能力的店铺回执')
  }
  return (await api.get(`/shops/${receipt.shop_id}/submissions/${encodeURIComponent(receipt.external_id)}`)).data
}
