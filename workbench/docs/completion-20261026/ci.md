# 扩展恢复与提交前复核的持续集成

## 交付目的

把当前实现的整包原件复核、扩展数据库恢复和独立对象绑定纳入每次候选代码检查，并修复实际 GitHub runner 暴露的文字修订浏览器等待时序。检查入口是 `.github/workflows/workbench-ci.yml`，仍通过 PR #2 面向 `fusion/bid-workbench`，不自动合并主分支。

## 八个独立任务

| 任务 | 核验范围 |
| --- | --- |
| Backend quality and default tests | 锁定依赖一致性、Python 格式/类型/安全门、默认测试；外部条件跳过单独记录 |
| PostgreSQL 17 non-owner API tests | 实际非 owner API 专项，包含新的 `test_package_submission_preflight_pg.py`；跳过、失败或空报告均不能通过 |
| Material request preflight and execution ledger | 实际原生完整材料请求、预算和一次发送账本；合成模型端口 |
| Material outbox dispatch | PostgreSQL 17 与独立 Kafka 4.1.2 的真实运输、重放和发送权交错 |
| Fixed-source editing and Word export | 独立 PG/S3 的 B1–B5 编制、人工文字修订和实际 Word 构建 |
| Fresh authoring schema and independent SCRAM role permissions | 全新候选安装与独立口令角色的权限正反例 |
| Extended-schema backup and quarantine restore | 74 SQL、非空编制及材料派发数据、真实 dump/restore、独立目标桶读取和只读隔离；自行创建与回收 PG/S3 |
| Frontend quality, tests and build | 格式、lint、TypeScript、组件回归、生产构建，以及概览/文字修订/提交前复核各四种真实 Chromium 组合 |

恢复任务使用固定官方 PostgreSQL 17.11、pgvector 0.8.7 和配套客户端/libpq 包，下载后逐个核对 SHA-256。安装前明确禁止创建系统默认集群，实际测试集群由恢复入口独立创建。SeaweedFS 4.48 使用与既有原生编制任务相同的固定下载摘要。恢复报告仅上传脱敏的 JUnit、证明、汇总、服务清理和日志；私有口令、数据库 dump 与原件档案不进入报告目录。

前端使用既有固定 Playwright 1.51.1 / Chromium 134.0.6998.35。三个浏览器脚本各覆盖 1280px 桌面、390px 手机的明暗两种主题，共 12 个组合。提交前复核脚本核对键盘 Enter、原请求与 ETag、输入绑定、刷新/失败/会话过期清除、旧回复丢弃和横向溢出。它使用显式合成 HTTP fixture；这不等于浏览器连接实时 PG/S3 的完整业务端到端。

## 实际 CI 失败的修正

阶段 11 的 [GitHub Actions 40250113281](https://github.com/zys743551828-art/tender-app/actions/runs/40250113281) 中六个后端任务成功，前端任务在 `check-exact-text-edit-browser.mjs` 的首次 POST 次数断言失败，实际观察为 `0 !== 1`。失败发生在前端组件测试、构建和项目概览浏览器检查已经通过之后；该次运行不能记为全部通过。

文字修订组件先持久化原请求、显示待恢复界面，再异步核验完整请求摘要并发起 POST。原浏览器脚本只等待恢复按钮出现，因此可能在正常的发送前中间态读取请求次数。修正后等待“首次 POST 已出现，且首次发送结束后恢复按钮已启用”，再执行原有的严格一次断言。没有固定 sleep，没有修改业务组件，也没有删除完整请求、If-Match、幂等键、刷新不自动发送、恢复请求相同和一次保存回调等检查。

修正后的真实 Chromium 四组合全部通过，脚本 SHA-256 为 `2731091b83bb8bb888f050d8808953cb30b4ca6c665d50e9db9d983edcb0619b`；每个组合都保留 `original_request_preserved=true` 和 `automatic_posts_after_reload=0`。

## 本地验证与结果读取

- CI 汇总及隔离边界回归：`28 passed / 0.22s`；该组也包含在恢复阶段的 64 项组合中，不能重复相加。
- `ci_checks.py` 的 Ruff、格式、mypy 和 Bandit 通过。
- workflow 成功解析为 8 个 job，39 个 shell 步骤通过 `bash -n`。
- 文字修订浏览器脚本的 Prettier、ESLint 和实际 Chromium 四组合通过。
- 新原件复核浏览器脚本分别以非 owner PG 产出的合成回执和默认 CI 合成回执运行，各四组合通过；详见 [提交前复核](submission.md)。
- 新恢复入口最终 6 项原生测试通过，零跳过、退出码 0；源数据和清理证据详见 [扩展恢复](recovery.md)。

本文件记录实现及本地证据。GitHub runner 的最终结果按 [PR #2](https://github.com/zys743551828-art/tender-app/pull/2) 对应 head 的 [Actions 运行](https://github.com/zys743551828-art/tender-app/actions/workflows/workbench-ci.yml)读取，并核对实际测试的合并树。配置了检查不等于检查成功；后续提交触发而取消的运行不能沿用之前的成功。各任务测试存在重叠，默认跳过不算通过，合成输入也不授予真实业务效果、正式评分或生产灾备资格。
