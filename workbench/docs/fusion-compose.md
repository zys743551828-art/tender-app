# 融合独立 Compose 组

项目固定为 `tender-fusion`。默认只启 PostgreSQL、一次性初始化、API、Web；Web 地址为 `http://127.0.0.1:5188`，由 nginx 同源代理 `/api/`。PostgreSQL 无宿主端口。core 为独立 internal 网络；仅 Web 同时连接 preview bridge 供 loopback 端口发布，API、init、数据库和 checks 均不接 preview。数据库、初始化资料、API 配置和检查证据分别使用本组命名卷。所有服务关闭自动重启。

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

要求/覆盖 DDL 经评审加入共享计划后，本预览显式改为 `fusion_v2`：新库 `tender_checks_fusion_v2`，init 使用 `init_state_v2`，init/API 共用独立 `api_profile_v2`。固定项目名、5188、PostgreSQL 数据卷及本地秘密文件不变；原 `tender_checks_fusion` 与 `init_state` / `api_profile` 卷保留，不挂载到新 API，不覆盖或隐式升级。配置更改本身不启动服务；由主代理显式执行默认组 `up`，首次创建新代际。

这是一次明确的新鲜预览切换，没有自动推算代际、迁移旧库或清空卷的机制。若 v2 已有不完整状态或 SQL 指纹不匹配，仍按下面规则拒绝修复，不自动另建 v3。

新库由实际 `bootstrap_fresh` 按共享 `schema_plan.BASE_SQL` 和冻结字节创建；不启用归档或可选扩展。初始化凭证只保留在 init 专有卷，业务账户使用非 owner LOGIN。初始管理员仅在全新创建成功后写入。

成功重启必须同时匹配初始化收据的库名与有序 SQL SHA，并验证 API 私有配置和管理员记录。存在库但没有成功收据、SQL 变更或不完整状态均拒绝自动修复，不能把重启当作前进迁移入口。修改共享计划需要独立评审，不能通过删除卷绕过失败原因。

`initialize_database` 与 `bootstrap_fresh` 已共用无副作用的共享 tuple，初始化器在连接前按 UTF-8 冻结全部输入，保留已有库拒绝与 CLI 边界；该收敛不表示 F02-01 全部扩展和前进部署已完成。

## 当前验证状态（2026-10-19）

静态 ruff、format、Linux 平台 mypy、bandit、离线 Compose config 与 diff 检查通过；共享初始化 14 项已由主代理独立复跑通过。经授权在宿主仅运行两个不涉及 POSIX 权限的 Compose 配置节点，最初 2 passed in 0.44s；加入仅 Web 可接 preview 的约束后，2 passed in 0.49s，收据 `.local/fusion-preview-config.xml`，独立 basetemp 为 `.local/fusion-preview-config-pytest`。

Docker 恢复后，本组 checks pure 在既有 Python3.12 镜像实际完成 70 passed in 0.87s，含 Linux 私有配置权限与 helper 纯回归，服务退出0、真实供应商尝试0；证据 `.local/fusion-pure-evidence/`。默认组由主代理启动，init成功退出、API健康。Docker29 中 Web 只接 internal 网时实际端口映射为空，因此仅为 Web 增加 preview bridge 并单独重建该服务；宿主 `/` 200，真实 `/api/v1/auth/session` 未登录返回401，证据 `.local/fusion-preview-http.json`。该修复未重启 init、API 或 checks。

角色/库存在查询从无返回列的 `SELECT FROM` 改成 `SELECT 1`：默认 tuple row factory 下存在行原为假值空 tuple，会错误重复建组或漏过入口已有库检测。修复后检查服务重复运行成功。

要求/覆盖已独立静态审查并加入共享12项计划：worker-functions之后装新DDL，roles之后撤销四张冻结历史表UPDATE。明确新代际fusion_v2已实际全新初始化，原fusion库和旧配置卷保留；主代理通过5188入口实测登录200、会话200、异源403、缺CSRF403、退出204及退出后401。内置浏览器控制连接仍不可用，无本次视觉截图。

编排支持 `checks -Suite requirements-pure` 与 `checks -Suite requirements-api`；后者仅向子测试进程注入独立 checks-PG 的 `FUSION_REQUIREMENTS_ADMIN_DSN`。执行者最终20项通过，主代理从整合12项计划独立再验20项通过22.28秒；测试库和账号在fixture结束清理，容器和卷保留。最终Linux pure再次70项通过0.80秒。要求页面、完整抽取身份与正式评审资格仍未覆盖。
