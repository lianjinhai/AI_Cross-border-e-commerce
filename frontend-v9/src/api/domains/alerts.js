/**
 * alerts（风险巡检/告警） 域（占位）：对应 backend/app/routers/alerts.py。
 *
 * UX-B 仅建文件锁定模块清单（契约 §4.1）；实现于 UX-C/D/E 按契约 §4.2
 * 签名模式补齐：fetchXxx(参数) → Promise<DTO>；actionXxx(参数) → Promise<结果DTO>；
 * 只封装本 router 真实存在的端点，DTO 转换走 api/dto.js 纯函数。
 */
