import api from '../../shared/api/client'

/**
 * business-profile 域（D63 经营画像，V9.1 原型 02）。
 * 后端：backend/app/routers/business_profiles.py（契约卡见 docs/CONTRACT.md）。
 * 服务端是权威事实；前端会话画像（shared/onboardingProfile.js）仅作草稿/缓存。
 */

/** 读取当前用户 + 工作区的合并画像：缺失字段为 null，绝不臆造。 */
export async function fetchBusinessProfile() {
  return (await api.get('/business-profile')).data
}

/**
 * 幂等 upsert：body 为任意子集（snake_case），仅显式提供的键被写入，
 * 显式 null = 清除。保存成功后重新登录仍可读回。
 */
export async function saveBusinessProfile(data = {}) {
  return (await api.put('/business-profile', data)).data
}
