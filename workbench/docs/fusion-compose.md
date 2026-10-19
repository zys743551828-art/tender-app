# 融合独立 Compose 组

项目固定为 `tender-fusion`。默认只启 PostgreSQL、一次性初始化、API、Web；Web 地址为 `http://127.0.0.1:5188`，由 nginx 同源代理 `/api/`。PostgreSQL 无宿主端口。网络为独立 internal 网络，数据库、初始化资料、API 配置和检查证据分别使用本组命名卷。所有服务关闭自动重启。

不会启动 Kafka、Worker、评分、研究或供应商消费者。该组是本地开发预览与机制检查入口，不代表正式模型、OCR、转换能力或完整一期验收通过。原 dev/Claude 组不属于此编排。

## 前提与私密配置

复用本机已有 `tender-fusion-checks:py312`、固定 digest 的 PG17 pgvector 镜像及 `bidwb-web:0.1.0`；`pull_policy: never`，脚本不安装镜像。Web 仅复用 nginx 服务器，实际页面来自当前构建的 `apps/web/dist` 只读挂载。

忽略目录 `.local/fusion/` 保存 `owner-password`、`checks-owner-password`、`admin-password`。启动脚本仅为缺失的前两个文件生成独立随机值，保留已有值；管理员口令由本地私密文件提供，未提供时拒绝启动，不自动重设已有账号。不要把这些文件或口令加入 Git、日志或启动参数。

数据库 owner secret 只挂载到本组 PostgreSQL 与 init；检查 owner secret 只挂载到 checks-postgres 与 checks。API 只获得单独卷中的私有四项配置（API DSN、同源地址及会话/CSRF 密钥），不挂载 owner、Worker、核清管理员配置或宿主业务 `.env`。

## 操作

在 workbench 目录使用 PowerShell 7：

```powershell
./deploy/fusion.ps1 config
./deploy/fusion.ps1 up
./deploy/fusion.ps1 status
./deploy/fusion.ps1 logs
./deploy/fusion.ps1 checks -Suite pure
./deploy/fusion.ps1 checks -Suite budget
./deploy/fusion.ps1 stop
```

`stop` 停止整个项目，包括 checks profile，保留容器和卷；检查也用本组固定服务 `up` / `wait`，不用零散 `docker run`、一次性 `compose run --rm` 或自动删卷。检查输出在 `checks_evidence` 卷，JUnit 为 `pure.xml` / `budget.xml`，预算机制收据为 `budget-receipt.jsonl`。预算套件连接独立 checks-postgres，使用硬 Mock 阻断真实供应商请求。

`up` 在忽略目录写 `runtime-inputs.json`，记录当时公开后端源码、当前前端 dist、部署文件 SHA256 与实际三个镜像 ID。此记录用于区分复用的服务器镜像和当前页面；开发源码仍为只读挂载，记录不是不可变部署证明。

## 初始化与重启边界

新库由实际 `bootstrap_fresh` 按共享 `schema_plan.BASE_SQL` 和冻结字节创建；不启用归档或可选扩展。初始化凭证只保留在 init 专有卷，业务账户使用非 owner LOGIN。初始管理员仅在全新创建成功后写入。

成功重启必须同时匹配初始化收据的库名与有序 SQL SHA，并验证 API 私有配置和管理员记录。存在库但没有成功收据、SQL 变更或不完整状态均拒绝自动修复，不能把重启当作前进迁移入口。修改共享计划需要独立评审，不能通过删除卷绕过失败原因。

`initialize_database` 与 `bootstrap_fresh` 已共用无副作用的共享 tuple，初始化器在连接前按 UTF-8 冻结全部输入，保留已有库拒绝与 CLI 边界；该收敛不表示 F02-01 全部扩展和前进部署已完成。

## 当前验证状态（2026-10-19）

静态 ruff、format、Linux 平台 mypy、bandit、离线 Compose config 与 diff 检查通过；共享初始化 14 项已由主代理独立复跑通过。经授权在宿主仅运行两个不涉及 POSIX 权限的 Compose 配置节点，2 passed in 0.44s，收据 `.local/fusion-host-config.xml`，独立 basetemp 为 `.local/fusion-host-config-pytest`。Docker 引擎/socket 修复尚待完成，因此本次新增 Compose profile 完整纯测试、完整 helper Linux 回归、真实组初始化、API 登录与 Web 交互均待运行验证。本次未启动任何新容器，不把离线配置检查记录为运行验收。

要求/覆盖投影的新 DDL 与 API 仍由其他代理审查，不在本切片默认初始化中，相关检查尚未运行；须获独立批准后由主代理更新共享依赖计划。

编排已预留 `checks -Suite requirements-pure` 与 `checks -Suite requirements-api`；后者仅向子测试进程注入独立 checks-PG 的 `FUSION_REQUIREMENTS_ADMIN_DSN`。这两项必须等要求切片静态评审批准才运行，默认仍为 `pure`，预留入口不表示新 DDL 已获执行或默认初始化授权。
