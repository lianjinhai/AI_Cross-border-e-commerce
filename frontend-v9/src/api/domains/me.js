import {
  ensureWorkspaceContext,
  loadWorkspaces,
  switchWorkspace,
} from '../../shared/workspace'

/**
 * me 域（契约 §4.2）：对应 backend/app/routers/me.py（前缀 /me）。
 *
 * Context 获取/切换逻辑全部经 shared/workspace.js（响应式 Context 唯一来源），
 * 本模块**不在重复实现**，只做命名对齐（fetchXxx 形态）后转发。
 */

/** 当前 Workspace Context（经 shared/workspace.js；读取即建立响应式依赖）。 */
export { ensureWorkspaceContext as fetchContext } from '../../shared/workspace'

/** 可访问 Workspace 列表：GET /me/workspaces → {items[]}。 */
export { loadWorkspaces as fetchWorkspaces } from '../../shared/workspace'

/** 切换活动 Workspace：POST /me/workspaces/{id}/switch → bool。 */
export { switchWorkspace } from '../../shared/workspace'
