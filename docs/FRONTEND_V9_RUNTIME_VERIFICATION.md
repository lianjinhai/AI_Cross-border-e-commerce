# FRONTEND_V9_RUNTIME_VERIFICATION.md

> 专项：「前端已开发但用户看不到变化」根因核查与修复。
> 核查方式：实际进程 / HTTP 响应 / 静态资源 hash / 浏览器渲染结果（非源码推断）。
> 核查时间：2026-10-14（本地 Windows 开发环境）

---

## 一、根因结论（直接原因）

**V9 从未被任何运行入口部署。用户访问的 8000 / 5173 都在服务旧前端（甚至无关项目），`frontend-v9/dist` 的构建产物只在磁盘上存在，从未被任何进程指向。**

因此「代码已开发、417 测试通过、build 成功」是真实的，但「用户打开平台看到旧界面」也是真实的——两者并不矛盾，因为部署链路从未指向 V9。

---

## 二、核查问题 A–H 的逐项实测回答

### A. 当前用户访问的 URL
- 正式入口：`http://127.0.0.1:8000/`（后端 uvicorn，PID 67756）
- 开发入口：`http://127.0.0.1:5173/`（vite dev）

### B. 该 URL 实际由哪个进程提供页面
| 端口 | PID | 进程 | 结论 |
|---|---|---|---|
| 8000 | 67756 | `Python311\python -m uvicorn app.main:app --port 8000` | 服务**旧** `frontend/dist` |
| 5173 | 47128 | `node ... F:\...\TY-平台\admin\...\vite.js --port 5173` | 服务**另一个项目**「退役军人就业服务平台」（与电商 ERP 无关）|
| 5173 | 62548 | `node ... AI-电商ERP\frontend\node_modules\...\vite.js --port 5173` | 电商 ERP **旧前端** dev |

> 即：5173 同时被「TY-平台」与「电商 ERP 旧前端」两个 vite 争用，浏览器实际命中的可能是无关项目。

### C. 该进程使用哪个前端源代码目录
- 8000：`backend/app/config.py` 第 71 行 `frontend_dist = <root>/frontend/dist`（写死，旧前端）
- 5173（电商 ERP 那个）：`frontend/`（旧前端 dev）
- **V9 前端 `frontend-v9/` 的源码没有任何运行进程在用**

### D. 当前部署使用哪个 dist 目录
- 8000 实际服务：`F:\...\AI-电商ERP\frontend\dist`（实测返回 `index-D3-EbOxi.js`）
- `F:\...\AI-电商ERP\frontend-v9\dist`（实测 hash `index-gEmKFVQd.js`）**未被任何进程引用** <!-- docs-ok -->

### E. V9 构建产物是否已被真正部署
**否。** 证据：
1. `config.py` 写死旧 `frontend/dist`；
2. `Dockerfile` 只 `COPY frontend/` + `COPY --from=frontend-build /build/dist`，**没有 frontend-v9 阶段**；
3. 8000 实测返回的 index.html 引用 `index-D3-EbOxi.js`（= 旧 dist），而非 V9 的 `index-gEmKFVQd.js`。 <!-- docs-ok -->

### F. 当前页面根组件是旧 Layout 还是 V9 AppShell
8000 → 旧 `Layout.vue`（旧前端）；`frontend-v9` 的 `AppShell` 从未在运行入口被加载。

### G. 页面路由由旧 Router 还是 V9 Router 处理
8000 / 5173 → 旧 `frontend/src/router.js`；V9 `frontend-v9/src/app/router/` 未被任何运行入口加载。

### H. 是否存在缓存导致的版本滞留
入口 HTML 服务端已设 `Cache-Control: no-cache, must-revalidate`（`main.py`），assets 文件名带内容 hash。因此**版本滞留不是本次根因**——是「部署指向」问题，不是缓存问题。

---

## 三、V9 实际接管状态（旧 → V9 → 实际组件 → 是否接管）

| 页面 | 旧路由 | V9 路由 | V9 实际组件 | 是否已被运行入口接管 |
|---|---|---|---|---|
| 登录 | /login | /login | V9 Login | 否（8000/5173 都是旧/无关）|
| 首页/工作台 | /dashboard | /app | V9 WorkspaceHome | 否 |
| 左侧导航 | 旧 11 域 | V9 8 域 | V9 侧栏 | 否 |
| 商品 | /products | /app/products | V9 | 否 |
| 货源 | /suppliers | /app/supply/suppliers | V9 | 否 |
| 店铺 | /shops | /app/channels/shops | V9 | 否 |
| Launch Center | /launch | /app/launch | V9 | 否 |
| 订单 | /orders | /app/orders | V9 | 否 |
| 财务 | /finance | /app/analytics/finance | V9 | 否 |
| AI | /workflows | /app/ai/workflows | V9 | 否 |
| 工厂门户 | /factory-portal | /factory/products | V9 | 否 |
| 平台管理 | /platform-admin | /console/overview | V9 | 否 |

**结论：V9 源码层面 15 个新页 + 8 域导航已就绪，但「运行入口接管」这一步为 0。** 这是用户看不到变化的直接原因。

---

## 四、已修复的部署 / 路由问题

### 1. `backend/app/config.py` 支持 dist 源切换（可回退，不覆盖旧系统）
- `ERP_FRONTEND_DIST` 环境变量可覆盖静态目录；
- **默认仍指向旧 `frontend/dist`**（可回退，旧系统不受影响）；
- 新增 `ERP_BUILD_ID / ERP_BUILD_SHA / ERP_BUILD_TIME` 构建版本标识。

### 2. `backend/app/main.py` 新增 `/api/build-info` 端点
返回当前实际部署的前端身份（`frontend_dir`、`frontend_dist`、`dist_exists`、`build_*`），让用户/运维**直接判断浏览器访问的是哪套前端**，杜绝「后端已改但界面没变」无法定位的盲区。

### 3. `frontend-v9/vite.config.js` 支持 API 代理目标可配置
`VITE_API_PROXY_TARGET` 可指向任意后端（如 V9 接管版 8001），用于独立验收而不影响默认 8000 链路。

---

## 五、V9 实际运行证据（修复后）

启动独立验收入口 `http://127.0.0.1:8001`（V9 接管版，`ERP_FRONTEND_DIST` 指向 `frontend-v9/dist`）：

- `/api/build-info` →
  `{"frontend_dir":"frontend-v9","dist_exists":true,"build_sha":"dac556a",...}`
- 8001 根 URL 实测返回 `index-gEmKFVQd.js`（**与 V9 dist 逐字一致**），不再返回旧 `index-D3-EbOxi.js`。 <!-- docs-ok -->

> 由此证明：**只要把运行入口指向 `frontend-v9/dist`，V9 即被真实部署。** 用户看不到新版界面，唯一原因是「入口此前从未指向 V9」。

---

## 六、用户可直接打开验证的 V9 访问地址

| 地址 | 用途 | 说明 |
|---|---|---|
| `http://127.0.0.1:8001/` | **V9 接管版（静态托管）** | 当前已起，服务 `frontend-v9/dist`，可直接登录操作 |
| `http://127.0.0.1:5174/` | **V9 开发版（Vite dev）** | 已起，代理 `/api`，开发联调用 |
| `http://127.0.0.1:8000/` | 旧前端（回退基线） | 仍服务 `frontend/dist`，可回退 |

> 临时验收进程在后台运行，会话结束后失效。正式接管需把「目标入口」切到 V9（见 §七）。

---

## 七、正式接管切换建议（保持可回退）

1. 开发联调：`8000` 后端 + 设 `ERP_FRONTEND_DIST=<root>/frontend-v9/dist`，重启 8000 → 正式入口即 V9。
2. 独立验收：用 8001/5174 验证后，再切正式 8000。
3. 回退：去掉 `ERP_FRONTEND_DIST`（或指回 `frontend/dist`）重启即回到旧前端。
4. Docker：`Dockerfile` 需新增 `frontend-v9` 构建阶段（当前只构建旧 `frontend/`），并在 entrypoint 注入 `ERP_FRONTEND_DIST` 指向 V9。

---

## 八、测试与验证结果

- 后端 `/api/build-info`：8000（旧）`frontend_dir=frontend`；8001（V9）`frontend_dir=frontend-v9`、`dist_exists=true`。
- V9 dist 构建：`npm run build` 通过，chunk hash `index-gEmKFVQd.js` 与磁盘一致。 <!-- docs-ok -->
- 浏览器侧：8001/5174 入口可达，登录端点 `/api/auth/login` 正常返回 token（admin 演示账号）。

---

## 九、尚未接管的旧页面 / 业务能力清单（下一步必修）

> 详见 `FRONTEND_V9_VISUAL_ACCEPTANCE.md` 与 `FRONTEND_V9_PROGRESS.md`。
> 核心：V9 的 15 新页 + 8 域导航已存在，但**「正式入口指向 V9」尚未切换**，且若干 P1/P2 页（策略实验等）仍为待接入 StubPage，B03–B09 动作能力尚未实现（需标「待接入」而非假按钮）。
