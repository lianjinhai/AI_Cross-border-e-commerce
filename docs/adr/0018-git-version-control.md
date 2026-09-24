# ADR-0018：仓库纳入 Git 与 LF 行尾锁定

- **状态**：Accepted
- **决策编号**：[`DECISIONS.md` D18](../DECISIONS.md#L806)
- **日期**：2026-09-24

## Context

自项目启动以来仓库**无 `.git`**（DEBT-01，当时唯一 P0）。后果：

- `.gitignore` / `.dockerignore` / `.github/workflows/ci.yml` **全部未生效**；
- **唯一回滚手段是手工冷备**，代码本身无任何版本历史；
- 并行工具（zcode）与主代理反复发生「文件同改、迁移编号撞车」，无冲突检测能力。

`git init` 按规范须由项目负责人确认。本次获得明确授权后执行。

## Decision

**执行 `git init -b main` 并完成首次提交**，且**提交前必须做安全体检**：

1. `git add --dry-run .` 逐项核对危险文件清单；
2. 正则扫描密钥泄漏（`AKIA*` / `sk-*` / PEM 私钥 / `secret=` 赋值）；
3. `git check-ignore -v` 逐项实测忽略规则是否覆盖冷备目录；
4. 扫描行尾一致性，新增 `.gitattributes` 锁定 `eol=lf`。

## Consequences

**收益**

- 代码获得**版本历史与回滚能力**；
- `.gitignore` / `.dockerignore` / CI **真正开始生效**；
- 并行协作具备冲突检测能力。

**代价 / 硬约束**

- 提交前必须 `git add --dry-run` 核对清单（V-4）；
- 行尾由 `.gitattributes` 锁定 LF：`docker-entrypoint.sh` 等一旦变成 CRLF，
  容器会报 `bad interpreter: /bin/sh^M`——**属「本地一切正常、部署就崩」的典型缺陷**（V-3）；
- 新增「子目录下的产物」时必须实测 `git check-ignore -v <路径>`：
  **通配符不跨目录**，`backend/*.db` 挡不住 `backend/backups/x.db`（V-2）。

**体检实际挖出的 3 个隐患**（若不体检就会踩）

| # | 隐患 | 后果 |
|---|---|---|
| 1 | 冷备目录完全未覆盖忽略规则 | 会一次性灌入约 25 MB 数据库文件 |
| 2 | 临时脚本与变异残留（`_*.py` / `*.orig`）会被入库 | 污染仓库 |
| 3 | `docker-entrypoint.sh` 会被写成 CRLF | 容器启动即失败 |

## Alternatives considered

| 方案 | 否决理由 |
|---|---|
| **继续用手工冷备做版本管理** | 无法定位「哪次改动引入缺陷」；并行协作必然冲突 |
| **直接 `git add .` 后提交** | 会灌入数据库文件与临时脚本；实测确认这些确实未被忽略 |
| **先提交、后补 `.gitattributes`** | 首次提交就会把 CRLF 写进历史，后续需要改写历史才能修正 |

## References

- 权威源：[`DECISIONS.md` D18](../DECISIONS.md#L806)（含完整体检数据与结果）
- 规范：`docs/CODE_AND_DIRECTORY_STANDARD.md` §7（V-1~V-4）、DEBT-01
- 相关决策：D21（Docker 实测，依赖 LF 行尾）