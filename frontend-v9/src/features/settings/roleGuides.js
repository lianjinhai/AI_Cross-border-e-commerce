/**
 * 角色枚举与权限说明卡（UX-E #26，纯数据 + 纯函数）。
 *
 * 提交值必须是后端唯一接受的 legacy 小写（backend/app/routers/auth.py 第 96/119 行
 * 校验），展示层映射为 Context 权威大写枚举（与 workspace_context 下发口径一致）。
 * 权限说明只做「角色 → 能力范围」的人读文案，**不重新定义角色-权限矩阵**
 * （权威事实源是后端 ROLE_PERMISSIONS，此处禁止双事实源）。
 */

export const ROLE_ENUM = {
  admin: 'OWNER',
  compliance_approver: 'COMPLIANCE',
  operator: 'OPERATOR',
  viewer: 'READ_ONLY',
}

export function roleEnumLabel(value) {
  return ROLE_ENUM[value] || value
}

/** 角色下拉选项（value=legacy 提交值，label=大写枚举展示）。 */
export const ROLE_OPTIONS = [
  { value: 'admin', label: 'OWNER（管理员）' },
  { value: 'compliance_approver', label: 'COMPLIANCE（合规审批员）' },
  { value: 'operator', label: 'OPERATOR（运营）' },
  { value: 'viewer', label: 'READ_ONLY（只读）' },
]

/** 权限说明卡数据（矩阵 #26：按角色枚举给权限说明卡，与工作区切换器语义对齐）。 */
export const ROLE_GUIDES = [
  {
    key: 'OWNER',
    title: 'OWNER · 所有者',
    points: [
      '全部经营域读写：订单履约、货源采购、售后、经营优化、数据分析',
      'AI 运营：工作流运行/调度、知识库维护、AI 与集成设置',
      '成员管理：新增/编辑/停用成员与分配角色（本页）',
    ],
  },
  {
    key: 'OPERATOR',
    title: 'OPERATOR · 运营',
    points: [
      '日常经营写操作：商品/Listing/订单/采购/客服回复/广告',
      'AI 运营：运行工作流、维护调度与知识库候选',
      '不可见：AI 与集成设置、用户与角色（OWNER 专属）',
    ],
  },
  {
    key: 'COMPLIANCE',
    title: 'COMPLIANCE · 合规审批员',
    points: [
      '仅上架合规审批（compliance:approve）',
      '菜单收敛至审批相关页面，其余经营域不可写',
    ],
  },
  {
    key: 'READ_ONLY',
    title: 'READ_ONLY · 只读',
    points: [
      '全站只读查看，不出现任何写操作按钮（fail-closed）',
      'AI 副驾驶对话可用，但建议动作执行会被后端 403 拒绝',
    ],
  },
]

/** 角色变更是否会影响菜单可见性的提示（角色修改即时反映菜单，验收 ②）。 */
export const ROLE_CHANGE_NOTE =
  '角色修改保存后即时生效：菜单可见性与按钮权限将按新角色收敛（前端 fail-closed，后端仍独立鉴权）。'
