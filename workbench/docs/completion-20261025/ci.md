# 阶段：持续集成与可复现检查入口

## 实现

新增 `.github/workflows/workbench-ci.yml`，对 `main`、`fusion/bid-workbench` 的相关 push，以及面向这两个分支的 PR 运行，草稿 PR 同样检查；也支持手动触发。初版还监听 `work/**` push，后续去掉该重复入口：工作分支已有 PR 时，每次阶段提交由 PR synchronize 执行完整检查，避免同一提交同时排队两套重型任务。工作流只申请 `contents: read`，checkout 不保留凭据；所有第三方 Actions 均使用核对过官方引用的提交 SHA。

七个独立检查项：

| 检查项 | 内容 | 覆盖边界 |
| --- | --- | --- |
| 后端质量与默认测试 | Python 3.12、原锁依赖一致性、Ruff、格式、mypy、Bandit、全目录 pytest | 外部环境测试沿用显式开关，逐项记录跳过及原因 |
| PostgreSQL 17 非 owner API | 临时 pgvector/PG17 服务，运行既有要求、范围核查、项目摘要、主要动作套件 | 必须有真实测试并且零跳过；仅合成数据，无业务库、供应商或模型调用 |
| 评分请求与费用账本 | 独立 PG17 串行执行正式请求预检、执行尝试与费用结算原生套件 | 保持实际非 owner 权限、5 秒 statement 限制及 120 秒 lease；零跳过 |
| 评分消息分发 | 独立 PG17 与 Kafka 4.1.2，验证原始 outbox、专属 relay／consumer、lease 与真实消息重复交付 | 必须实际启用 Kafka 用例且零跳过；模型响应为合成夹具，生产资格门禁保持拒绝未验收用途 |
| 全新候选装配 | 独立空 PG17，通过真实 SCRAM 密码登录验证全新建库、DDL 和 API／Worker 权限 | 不预建能力组；验证独立服务身份的实际权限，零跳过；无需对象存储 |
| 固定来源编辑与 Word 导出 | 独立 PG17 与临时 S3，执行固定来源版本、构建和人工文本编辑三个原生套件 | 真实数据库／对象存储与进程内原生 API／Worker 路径；模型响应和业务内容为显式合成夹具，零跳过 |
| 前端 | Node 24、npm ci、格式、lint、TypeScript、完整 Vitest、生产构建和真实 Chromium 检查 | 概览与固定来源编辑各测桌面／手机与明暗主题四组合；浏览器业务响应为显式合成数据，不冒充真实业务或用户验收 |

默认后端部署测试需要真实前端构建产物，后端 job 因此也按同一 npm 锁构建 Web，不在缺少 `dist` 的新检出上直接运行冻结部署测试。

解析测试使用真实 Tesseract 和中文字体；工作流安装 `tesseract-ocr`、`fonts-noto-cjk`，再通过已有 `packages.parsing.fetch_assets` 下载并验证仓库 manifest 锁定的英文／简体中文词典。缺少这些公开运行依赖会导致测试失败，不会把实际 OCR 检查转为跳过。

`deploy/ci_checks.py` 是本地与 Actions 共用的测试入口。它隔离业务环境和模型凭据，移除同一报告位置的旧 JUnit、统计和服务日志后再启动本轮测试，独立统计通过、失败、错误、跳过及原因。无测试、缺报告、pytest 错误或原生套件出现跳过均不产生通过结论。JUnit、JSON 和 Markdown 作为对应提交的 Actions artifact 保留 14 天。

PostgreSQL 检查仅接受明确指定的本地 TCP／Unix socket、端口、用户、`postgres` 管理库及 PG17，且必须传 `--disposable-postgres`。libpq 的 `hostaddr`／`service` 参数或对应环境覆盖会被拒绝，不能绕过显式本地目标。常规原生检查只创建所需 NOLOGIN 能力组；已有组的权限异常会拒绝。候选装配检查要求显式 `127.0.0.1` TCP 密码连接与独立空集群，保留能力组尚未存在的前置条件；对应 Actions 服务强制 SCRAM 验证。候选 DSN 只接受五个身份字段，不注入或丢弃额外 libpq 参数，保持全新引导的精确身份 URI 校验。原生 fixture 自行创建临时数据库与非 owner 服务登录，测试结束清理。管理连接不会被用于替代业务身份。其余原生套件的 JIT 只通过检查 DSN 的会话参数关闭。

作者检查使用 `deploy/ci_object_store.py` 启动 SeaweedFS 4.48。下载归档须通过固定 SHA-256 校验：`4a7d108384d044d95212d1342cdda9533fa55842c1c9b41f606ca3c8a9561124`。所有端口只绑定 `127.0.0.1`；每次创建临时目录、随机凭据和专用存储桶。测试的应用凭据仅能读写该桶，创建桶用的管理凭据不会交给测试进程。正常退出和异常退出都会停止服务并删除临时数据；留存服务日志前移除本次凭据。原生测试使用简短 traceback，避免展开包含测试 DSN 的完整 fixture。

分发检查使用 `deploy/ci_kafka.py` 和 Java 17 启动全新 KRaft 单节点。工作流下载 [Apache 官方 Kafka 4.1.2 归档](https://archive.apache.org/dist/kafka/4.1.2/kafka_2.13-4.1.2.tgz)，在解压前验证官方固定 SHA-512：`78ac6e488b1071122f9608dfdb363f6fe50e1dbbc492347002c0398dfbf77e0d8caa5bf794c5937379721004dfe92025937d238b0faf4eb715529417fd43b491`。helper 进一步检查预期版本文件和非符号链接启动程序；每轮使用独立 700 目录、新 cluster ID、600 配置与两个随机 loopback 端口。broker／controller 均只监听并宣告 `127.0.0.1`，禁用远程 JMX 与自动建 topic，启动后再次核对真实 broker metadata。正常返回、启动失败或测试异常均只停止本轮进程，必要时在有限等待后强制结束；保存服务日志后删除临时数据，不调用全局按进程名停止服务的脚本。专属 suite 自行创建固定测试 topic 与随机消费组，整个专用 broker 的销毁清除其测试消息。

浏览器检查将 Playwright 1.51.1 安装到 runner 临时目录，与应用的 npm 锁依赖分开，并使用对应的 Chromium。`check-project-review-summary-browser.mjs` 记录源码 SHA-256、1280／390 像素宽度下的明暗主题结果和截图；校验显式选择、精确导航、失效后禁用旧动作、只读请求及无横向溢出。`check-exact-text-edit-browser.mjs` 使用同样四组合，验证填写文本与理由、明确确认、丢失 ACK 后整页重载保持原请求且不自动 POST、显式重试保留原请求体／If-Match／幂等键，以及导航保护。两组证据都包含在前端 artifact 中。

## 使用

在 `workbench/` 安装原锁依赖，并按 `apps/web/package-lock.json` 构建前端；系统需要 Tesseract 和 Noto CJK 中文字体。默认字体路径为 `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`，其他路径可通过 `PARSING_TEST_FONT_PATH` 显式指定。随后执行：

```sh
.venv/bin/python -m packages.parsing.fetch_assets --directory .local/parsing-models
.venv/bin/python deploy/ci_checks.py --suite unit
```

在专用临时 PG17 上，私有环境变量 `CI_POSTGRES_DSN` 指向其本地 postgres 管理库，再执行：

```sh
.venv/bin/python deploy/ci_checks.py --suite postgres --disposable-postgres
.venv/bin/python deploy/ci_checks.py --suite scoring --disposable-postgres
```

全新候选装配使用另一套专用空 PG17；`CI_POSTGRES_DSN` 必须明确包含 `host=127.0.0.1`、独立端口、管理用户、密码及 `dbname=postgres`，服务须使用 SCRAM 密码认证，且不能预先创建能力组：

```sh
.venv/bin/python deploy/ci_checks.py --suite candidate --disposable-postgres
```

在同类专用 PG17 上，将经过上述哈希核验、解压得到的 SeaweedFS 二进制传给作者检查：

```sh
.venv/bin/python deploy/ci_checks.py --suite authoring --disposable-postgres --weed /absolute/path/to/weed
```

该命令自行创建并关闭本轮 S3 服务，无需配置任何现有对象存储或模型密钥。

消息分发使用另一套专用 PG17、Java 17，以及经过上述 SHA-512 校验并解压的 Kafka 目录：

```sh
.venv/bin/python deploy/ci_checks.py --suite dispatch --disposable-postgres --kafka-home /absolute/path/to/kafka_2.13-4.1.2
```

如果系统默认 Java 不是 17，可显式设置 `JAVA_HOME`；该值只传给隔离 Kafka 服务。命令内部设置原生分发开关和新 broker 地址，测试进程不会继承既有 Kafka／业务／供应商环境。无需启动或配置用户已有的 broker。

默认报告在 `.local/ci/<suite>/`，不提交运行凭据。不要将该检查配置指向现有业务环境。旧固定历史包的可选验收边界见 [测试可复现性](test-portability.md)。

## 本轮验证记录

- 原 Python 锁与额外文档处理检查依赖安装成功，`pip check` 通过；npm ci 成功，未改依赖版本或锁文件。
- 包含本轮作者、概览和 CI 完成源码的独立快照通过全域 Ruff、**1046 文件格式、661 实现文件 mypy** 和 Bandit。源码、前端构建、两份 OCR 词典与中文字体均为实际文件并保存 SHA-256，只有安装好的依赖复用；并发中的后续评分执行草稿未混入此快照。
- 新 CI 入口的 **16 项回归通过**；包含失败／错误／跳过统计、拒绝空报告、拒绝旧报告替代崩溃、拒绝 PostgreSQL／作者原生套件假绿、环境凭据隔离、远端数据库与 libpq 路由覆盖拒绝，以及显式旧档案缺失失败。最后增加的 4 项路由反例另做定向回归；CI 入口与引导安全测试最终合跑 **64 项全部通过，0.72 秒**。入口 Ruff、mypy 和 Bandit 通过，显式临时 PG17 的正向连接仍通过。
- 后续独立评分／候选 job 的入口接线回归扩展到 **25 项，全部通过，0.68 秒**；覆盖对应开关、候选 DSN 映射及不预建能力组、拒绝 socket 代替候选密码验证，以及每个原生套件出现跳过时失败。候选环境捕获回归实际调用生产 `bootstrap_fresh.identity_dsn`，验证无额外 `options` 破坏身份派生；另明确拒绝额外 `options`／`application_name`／`connect_timeout`，未放宽引导 guard。新工作流通过 actionlint，修改入口通过 Ruff、格式、mypy 和 Bandit。两个新增 job 的实际原生执行结果见后续 Actions 记录，入口回归本身不算原生验收。
- 分发入口与 Kafka 生命周期守卫组合 **35 项通过，0.47 秒**：包含缺服务参数、原生跳过必须失败、旧服务日志清除、版本文件缺失／启动程序符号链接拒绝、非预期 broker metadata 拒绝，以及启动失败／测试失败／优雅退出超时时只清理本轮进程与临时目录、保留日志。额外检查既有 Kafka 地址、JVM 参数和 `BASH_ENV` 不会随宿主环境进入测试。修改入口与 helper 通过 Ruff、格式、mypy、Bandit，新增工作流通过 actionlint。
- 引导安全测试 **48 项通过，0.55 秒**。干净副本揭示 8 例意外依赖宿主 `.local` 权限，现改为独立目录并复制真实审核 SQL 字节；新增已有 755 私有目录必须拒绝、不得修复权限或连接数据库的反例。生产权限检查保持原样。此修复随候选装配阶段提交 `9db306cd3e152a85856efc6632ae1dd465a6a53f` 发布。
- 官方 `actionlint` v1.7.12 通过工作流语义检查。验证工具归档 SHA-256 为 `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`，按官方 release 元数据核对后使用。
- 真实本地解析与 HTTP 解析组合 **17 项通过、0 跳过，11.41 秒**。本机缺少的词典按既有 manifest 哈希下载，合成测试使用官方 Noto CJK 字体，未修改解析方法身份或放宽验证。
- 临时 S3 引导已实测对象写入／读回、应用凭据拒绝创建其他存储桶（HTTP 403），以及退出后服务端口关闭。
- 新 Kafka helper 实际生命周期验证 **10.45 秒通过**：700 私有目录、600 配置、loopback broker metadata、幂等 producer 的真实 ACK、精确消息读回、同步 offset commit 均完成；退出后本轮 Java 进程已回收、监听关闭、私有数据目录删除、服务日志保留。官方两个启动脚本均使用 `exec`，当前调用不带 daemon 参数；进程句柄对应最终 Java。用于评分阶段的前一独立手动 Kafka 实例也在使用者释放后，核对 PID 启动身份与配置再停止，两个原端口均已关闭。
- 分发阶段独立 PG17＋真实 Kafka 全套 **13 项通过、0 跳过，357.67 秒**；随后加强真实 offset commit ACK 丢失与 seek 重放的两个 Kafka 用例另行通过（47.72 秒），不将这次重复执行计为额外独立用例。该阶段的协议 41 项通过，具体业务机制与生产资格边界见评分分发记录。新增 CI dispatch job 的整套执行仍需其对应提交的 Actions 核验。

| 实际运行 | 通过 | 跳过 | 失败／错误 | 耗时 |
| --- | ---: | ---: | ---: | --- |
| 完成源码快照的默认后端全量 | 3608 | 2328 | 0／0 | 263.24 秒 |
| 既有要求／范围核查／摘要／动作 PG 组合 | 333 | 0 | 0／0 | 1385.08 秒 |
| 同一 CI 隔离环境下单独补跑评分请求预检 | 4 | 0 | 0／0 | 103.54 秒 |
| 固定来源版本／构建／人工编辑 PG＋S3 组合 | 76 | 0 | 0／0 | 771.31 秒 |

333 项组合与 4 项预检是两次真实运行；初版工作流将它们作为一个 PostgreSQL job 执行，后续将预检移入独立评分 job，与新执行账本串行验证。评分阶段自身已完成 16 项执行与 4 项预检的原生组合，候选装配阶段已完成 14 项原生组合，具体源码与测试边界见相应阶段记录。作者检查实际使用临时 SeaweedFS 引导入口。各自固定测试数据库和 API／Worker 临时账号已核验清理。作者日志保留原有 Botocore 时间 API 弃用和测试 fixture 重复注册 router 的警告，没有通过过滤告警改变结果。

按 JUnit 的用例名去重，上述四次 Python 运行共 **3950 个不同用例通过**；原生检查执行了默认作业中跳过的 342 个用例，另有 **1986 个不同的外部／原生用例本轮未执行**。这些计数不代表全部外部系统或真实模型质量已完成验收，不将跳过记为成功。

首次提交 CI 时，本地最后一次完整前端回归仍在执行，尚未记为通过。以下本地失败记录均保留，没有用重跑结果覆盖原始失败：

| 运行 | 结果 | 实际失败 |
| --- | --- | --- |
| 双 worker，183 文件／1815 项 | 1814 通过／1 失败，242.85 秒 | `WorkContextReviewDetails` 超过原有 5 秒总时限；单文件 3 项另行通过，285 毫秒 |
| 单 worker，183 文件／1815 项 | 1814 通过／1 失败，526.30 秒 | `AuthoringLayout` 默认 1 秒查询截止时来源资格仍在加载 |
| 布局测试补充就绪条件后，183 文件／1816 项 | 1813 通过／3 失败，395.39 秒 | `RequirementCheckPlan` 两个测试超过 5 秒总时限，随后一例输入混入前例剩余键入字符 |
| 表单输入隔离修复后，183 文件／1816 项 | 1815 通过／1 失败，394.38 秒 | `WorkContextReviewDetails` 默认查询截止时仍显示核对原冻结输入／准备／结果的加载状态；布局与 17 项计划测试均通过 |

布局测试现显式等待资格核对结束且正文可编辑，保留原有行为断言，并增加延迟快照期间禁止编辑／保存、核对后启用同一节点的回归。只修改该测试；13 项相关定向回归已通过（10.84 秒）。计划测试的实际混合输入及已安装 `user-event` 实现证明：未取消的逐字符定时任务可在测试超时后向下一例焦点继续键入。7 处只用于填入整值校验样本的 `type` 改为原子 `change`，补充理由精确值断言，保留显式勾选／选择、201 字真实粘贴、迟到响应、恢复和协议断言。原文件独立 17 项通过，修复后也为 17 项通过（总耗时 3.47 秒）。最初停顿的资源或调度原因尚无证据，未归咎产品竞态。

详情测试的实际就绪链为三个固定身份 GET，加上冻结输入、执行输入及结果的异步 SHA-256 核验。现仅将第一例的结果区域等待上限设为 5 秒，并增加加载提示消失、恰好三个 GET 的断言；错误摘要拒绝及关闭后迟到响应两例保持原样。该文件与相邻原核查详情共 6 项通过（测试 1.06 秒、进程 7.78 秒），Prettier 与 ESLint 通过，产品逻辑未修改。

本地完整回归已停止反复执行，最终完整验收采用干净 GitHub runner。CI 的单测总时限保持原值；frontend job 的 20 分钟上限为单 worker 全量、依赖和浏览器安装预留时间。

新版全域格式、lint、TypeScript 和生产构建已通过；概览和 B5 编辑各有桌面／手机、明暗主题四组合的真实 Chromium 结果，分别见相应功能阶段记录。

## 首次 GitHub Actions 实际结果

提交 `d9cb947b19aae144b80c067b88ccb4e889aa53db` 的 [push run 40205210399](https://github.com/zys743551828-art/tender-app/actions/runs/40205210399) 已真实启动；以下结论来自该 run 的 job／日志，不能推及后续提交：

| Job | 已核对结果 |
| --- | --- |
| [前端 121204563228](https://github.com/zys743551828-art/tender-app/actions/runs/40205210399/job/121204563228) | 成功；183 文件／1816 项全部通过，生产构建 3.71 秒，概览与固定来源编辑的 Chromium 各 4 组合全部通过 |
| [固定来源 PG＋S3 121204563091](https://github.com/zys743551828-art/tender-app/actions/runs/40205210399/job/121204563091) | 成功；76 通过／0 跳过，507.32 秒；1291 条既有警告保留 |
| [后端默认 121204562885](https://github.com/zys743551828-art/tender-app/actions/runs/40205210399/job/121204562885) | 3657 通过／2358 跳过／1 失败；`test_fusion_desktop_private` 的一个单元测试错误假定运行 UID 为 root |
| [非 owner PG 121204563067](https://github.com/zys743551828-art/tender-app/actions/runs/40205210399/job/121204563067) | 成功；337 通过／0 跳过，889.03 秒；1 条既有警告保留 |

后端失败保留了正确的生产目录 owner 检查。测试仅在目标临时目录上明确模拟 owner，真实文件与权限 IO 保留，并新增空目录／已初始化目录的非 root owner 均须拒绝且不得修权限的两个反例。该文件本地 9 项通过（0.27 秒），Ruff／格式通过。本地尝试普通 UID 复验受工作区依赖不可读限制，未执行，也未改变依赖权限；下一次真实 GitHub 普通用户 runner 将验证该修复。上述 run 因此不能写成整体成功。

## 后续 GitHub Actions 实际结果

提交 `29daf782bac9a55c70c2af9bcfc6a99662a2c4df` 的 [PR run 40206884632](https://github.com/zys743551828-art/tender-app/actions/runs/40206884632) 只触发一套检查，未再重复触发工作分支 push。它验证 GitHub 为 PR 生成的合并提交 `674eb6c6ff7a7d959fb0b2bf9350651b48dab747`。以下为分发 CI 阶段冻结时已经完成的结果：

| Job | 已核对结果 |
| --- | --- |
| [后端默认 121209689790](https://github.com/zys743551828-art/tender-app/actions/runs/40206884632/job/121209689790) | 成功；3669 通过／2358 跳过／0 失败，245.13 秒；5 条既有警告保留。普通用户 runner 上原目录权限单元测试修复已实际验证 |
| [前端 121209689757](https://github.com/zys743551828-art/tender-app/actions/runs/40206884632/job/121209689757) | 成功；183 文件／1816 项全部通过，268.12 秒；构建 5.63 秒，概览与固定来源编辑的 Chromium 各 4 组合全部通过 |
| [评分预检与账本 121209689761](https://github.com/zys743551828-art/tender-app/actions/runs/40206884632/job/121209689761) | 成功；20 通过／0 跳过，387.85 秒；1 条既有警告保留 |
| [全新候选装配 121209689616](https://github.com/zys743551828-art/tender-app/actions/runs/40206884632/job/121209689616) | 成功；14 通过／0 跳过，6.32 秒；独立 SCRAM 身份与候选 DSN 接线已实际验证 |
| [非 owner PG 121209689838](https://github.com/zys743551828-art/tender-app/actions/runs/40206884632/job/121209689838) | 后续阶段提交触发并发策略取消，原生测试步骤未完成，不产生本次通过结论 |
| [固定来源 PG＋S3 121209689863](https://github.com/zys743551828-art/tender-app/actions/runs/40206884632/job/121209689863) | 后续阶段提交触发并发策略取消，原生测试步骤未完成，不产生本次通过结论 |

构建仍有既有大 chunk 提示；原锁中 pypdfium2 4.30.1 的上游撤回警告也保留，后续升级需独立核对解析方法与历史身份，未在本阶段擅自更换。
