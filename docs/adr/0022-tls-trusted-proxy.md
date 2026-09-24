# ADR-0022：TLS 落地与可信代理边界

- **状态**：Accepted
- **决策编号**：[`DECISIONS.md` D22](../DECISIONS.md#L1129)
- **日期**：2026-09-24
- **补全关系**：D8 曾显式留白「TLS 未纳入本次范围」，本决策补全该留白

## Context

DEBT-23（无 HTTPS / 反向代理）曾是唯一未清的 **P0**。上一轮已加了配置开关、
Caddyfile 与 TLS compose 覆盖层，但**一行都没验证过**。

本轮先跑验证，结果：**改动本身带来 3 个真实缺陷**，其中 1 个是 P0 级「比不改更糟」。

| # | 缺陷 | 后果 |
|---|---|---|
| 1 | `main.py` 直接 `from starlette.middleware.proxy_headers import ...` | **开关一打开就崩**（该模块在 starlette 1.x 已被移除） |
| 2 | `ERP_TLS_TERMINATED_ELSEWHERE` 用「非空即真」判断 | 写 `=0`（本意关闭）被当成「已声明 TLS」→ 门禁放行 |
| 3 | 门禁要求声明 TLS 位置，但基础 `docker-compose.yml` 没声明 | README 的「Docker 一键部署」**实际不可用** |

第 1 条的性质值得单独说明：**它不是「功能没做完」，而是负向交付**——
缺陷只在开关打开时出现，而开关默认关闭，因此**本地测试全绿、CI 全绿**，
直到有人在生产上启用它。

## Decision

1. **转发头实现换成 uvicorn 的**（`uvicorn.middleware.proxy_headers`），抽到
   `app/proxy_headers.py` 集中管理，**并写明为什么不能用 starlette 的**——
   否则后来者很容易「顺手改回去」；
2. **门禁严格比对 `== "1"`**（抽出 `_env_flag()`），`0/false/no/空` 一律视为未声明；
3. **两个 compose 形态各自显式声明**：
   - 基础层：`ERP_TLS_TERMINATED_ELSEWHERE=1`，并把端口绑定从 `8000:8000`
     收紧为 **`127.0.0.1:8000:8000`**——否则「TLS 在别处」这条声明就是橡皮图章：
     谁都能用 http 直连，而应用还以为前面有 TLS；
   - TLS 层：`ERP_TRUST_PROXY_HEADERS=1` + `ERP_TRUSTED_PROXY_HOSTS=<代理网段>`，
     并用 `!reset` **清空**继承来的「TLS 在别处」声明（两层同时声明是语义矛盾）；
4. **新增第二道闸：可信代理来源**。`ERP_TRUST_PROXY_HEADERS=1` 单独**不足以**安全，
   实测证据：

```
FORWARDED_ALLOW_IPS=* 时，直连应用发送 X-Forwarded-For: 203.0.113.77
→ uvicorn 日志记录 `203.0.113.77:0 - "GET /api/health"`（客户端 IP 被完全伪造）
```

   因此新增 `ERP_TRUSTED_PROXY_HOSTS`（默认 `127.0.0.1`），只有来自可信地址的
   转发头才被采信。Docker 下代理源地址是容器网段，故 TLS 覆盖层**固定了专用网段**
   （`172.31.240.0/24`，可用 `ERP_PROXY_NETWORK_PREFIX` 覆盖）——不固定时 Docker
   从地址池动态分配，应用侧无法预先写死可信来源，只能退化成「信任所有来源」，
   **等于没有防护**。

## Consequences

**收益**

- TLS 链路**真的跑通**并断言了链路效果（应用侧真的看到了 https 与真实客户端 IP）；
- 「外部无法绕过 TLS」变成**可执行证据**（应用容器未映射任何端口 + 宿主机 8000 不可直连）；
- 伪造客户端 IP 被阻断，审计日志与回调地址正确。

**代价 / 硬约束**

- 两个 compose 形态**必须各自显式声明** TLS 位置，漏声明会直接启动失败（这是刻意的）；
- 可信代理网段固定后，若调整网段需同步改环境变量；
- 新增 `scripts/tls_feasibility.py`（8 项检查）为改动 TLS / 代理 / 端口的**强制验证**（DP-7）。

**关键验证设计**：第 7 项「应用真的采信转发头」是关键——只证明「HTTPS 能通」**不够**。
Caddy 无条件转发，即使应用**没开**信任开关也能返回 200，那样应用仍以为自己在 http 之后，
生成的回调地址与审计日志全是错的。回退法实测：仅第 7 项 FAIL 时精确命中该缺陷
（其他 7 项全 PASS）——**若只写「HTTPS 能通」这一条断言，该缺陷会完整漏过去**。

## Alternatives considered

| 方案 | 否决理由 |
|---|---|
| **继续用 starlette 的 proxy_headers** | 模块在 starlette 1.x 已被移除，开关一打开就 `ModuleNotFoundError` |
| **只加 `ERP_TRUST_PROXY_HEADERS` 布尔开关** | 实测可被任意伪造客户端 IP，实际退化成信任所有来源（DP-8） |
| **TLS 由应用自身终止** | 证书续期与 ACME 需额外实现；Caddy 终止是成熟做法 |
| **应用容器同时映射 8000 到宿主机（便于调试）** | 使「TLS 在别处」声明变成橡皮图章，任何人可绕过 TLS 直连 |

## References

- 权威源：[`DECISIONS.md` D22](../DECISIONS.md#L1129)（含 8 项实测表与 6 项回退法验证）
- 相关决策：D8（生产部署基线，TLS 留白由本决策补全）、D21（Docker 实测）
- 规范：DEBT-23；DP-6 / DP-7 / DP-8
- 验证脚本：`backend/scripts/tls_feasibility.py`