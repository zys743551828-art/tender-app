# 阶段：持续集成与可复现检查入口

## 实现

新增 `.github/workflows/workbench-ci.yml`，对 `main`、`fusion/bid-workbench`、`work/**` 的相关 push，以及面向 main／fusion 的 PR 运行。也支持手动触发。工作流只申请 `contents: read`，checkout 不保留凭据；所有第三方 Actions 均使用核对过官方引用的提交 SHA。

四个独立检查项：

| 检查项 | 内容 | 覆盖边界 |
| --- | --- | --- |
| 后端质量与默认测试 | Python 3.12、原锁依赖一致性、Ruff、格式、mypy、Bandit、全目录 pytest | 外部环境测试沿用显式开关，逐项记录跳过及原因 |
| PostgreSQL 17 非 owner API | 临时 pgvector/PG17 服务，运行既有要求、范围核查、项目摘要、主要动作套件及新增正式评分请求预检 | 必须有真实测试并且零跳过；仅合成数据，无业务库、供应商或模型调用 |
| 固定来源编辑与 Word 导出 | 独立 PG17 与临时 S3，执行固定来源版本、构建和人工文本编辑三个原生套件 | 真实数据库／对象存储与进程内原生 API／Worker 路径；模型响应和业务内容为显式合成夹具，零跳过 |
| 前端 | Node 24、npm ci、格式、lint、TypeScript、完整 Vitest、生产构建和真实 Chromium 检查 | 概览与固定来源编辑各测桌面／手机与明暗主题四组合；浏览器业务响应为显式合成数据，不冒充真实业务或用户验收 |

默认后端部署测试需要真实前端构建产物，后端 job 因此也按同一 npm 锁构建 Web，不在缺少 `dist` 的新检出上直接运行冻结部署测试。

解析测试使用真实 Tesseract 和中文字体；工作流安装 `tesseract-ocr`、`fonts-noto-cjk`，再通过已有 `packages.parsing.fetch_assets` 下载并验证仓库 manifest 锁定的英文／简体中文词典。缺少这些公开运行依赖会导致测试失败，不会把实际 OCR 检查转为跳过。

`deploy/ci_checks.py` 是本地与 Actions 共用的测试入口。它隔离业务环境和模型凭据，移除同一报告位置的旧 JUnit、统计和服务日志后再启动本轮测试，独立统计通过、失败、错误、跳过及原因。无测试、缺报告、pytest 错误或原生套件出现跳过均不产生通过结论。JUnit、JSON 和 Markdown 作为对应提交的 Actions artifact 保留 14 天。

PostgreSQL 检查仅接受明确指定的本地 TCP／Unix socket、端口、用户、`postgres` 管理库及 PG17，且必须传 `--disposable-postgres`。libpq 的 `hostaddr`／`service` 参数或对应环境覆盖会被拒绝，不能绕过显式本地目标。初始化只创建所需 NOLOGIN 能力组；已有组的权限异常会拒绝。原生 fixture 自行创建临时数据库与非 owner 服务登录，测试结束清理。管理连接不会被用于替代业务身份。JIT 只通过该检查 DSN 的会话参数关闭。

作者检查使用 `deploy/ci_object_store.py` 启动 SeaweedFS 4.48。下载归档须通过固定 SHA-256 校验：`4a7d108384d044d95212d1342cdda9533fa55842c1c9b41f606ca3c8a9561124`。所有端口只绑定 `127.0.0.1`；每次创建临时目录、随机凭据和专用存储桶。测试的应用凭据仅能读写该桶，创建桶用的管理凭据不会交给测试进程。正常退出和异常退出都会停止服务并删除临时数据；留存服务日志前移除本次凭据。原生测试使用简短 traceback，避免展开包含测试 DSN 的完整 fixture。

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
```

在同类专用 PG17 上，将经过上述哈希核验、解压得到的 SeaweedFS 二进制传给作者检查：

```sh
.venv/bin/python deploy/ci_checks.py --suite authoring --disposable-postgres --weed /absolute/path/to/weed
```

该命令自行创建并关闭本轮 S3 服务，无需配置任何现有对象存储或模型密钥。

默认报告在 `.local/ci/<suite>/`，不提交运行凭据。不要将该检查配置指向现有业务环境。旧固定历史包的可选验收边界见 [测试可复现性](test-portability.md)。

## 本轮验证记录

- 原 Python 锁与额外文档处理检查依赖安装成功，`pip check` 通过；npm ci 成功，未改依赖版本或锁文件。
- 包含本轮作者、概览和 CI 完成源码的独立快照通过全域 Ruff、**1046 文件格式、661 实现文件 mypy** 和 Bandit。源码、前端构建、两份 OCR 词典与中文字体均为实际文件并保存 SHA-256，只有安装好的依赖复用；并发中的后续评分执行草稿未混入此快照。
- 新 CI 入口的 **16 项回归通过**；包含失败／错误／跳过统计、拒绝空报告、拒绝旧报告替代崩溃、拒绝 PostgreSQL／作者原生套件假绿、环境凭据隔离、远端数据库与 libpq 路由覆盖拒绝，以及显式旧档案缺失失败。最后增加的 4 项路由反例另做定向回归；CI 入口与引导安全测试最终合跑 **64 项全部通过，0.72 秒**。入口 Ruff、mypy 和 Bandit 通过，显式临时 PG17 的正向连接仍通过。
- 引导安全测试 **48 项通过，0.55 秒**。干净副本揭示 8 例意外依赖宿主 `.local` 权限，现改为独立目录并复制真实审核 SQL 字节；新增已有 755 私有目录必须拒绝、不得修复权限或连接数据库的反例。生产权限检查保持原样。此修复随候选装配阶段提交 `9db306cd3e152a85856efc6632ae1dd465a6a53f` 发布。
- 官方 `actionlint` v1.7.12 通过工作流语义检查。验证工具归档 SHA-256 为 `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`，按官方 release 元数据核对后使用。
- 真实本地解析与 HTTP 解析组合 **17 项通过、0 跳过，11.41 秒**。本机缺少的词典按既有 manifest 哈希下载，合成测试使用官方 Noto CJK 字体，未修改解析方法身份或放宽验证。
- 临时 S3 引导已实测对象写入／读回、应用凭据拒绝创建其他存储桶（HTTP 403），以及退出后服务端口关闭。

| 实际运行 | 通过 | 跳过 | 失败／错误 | 耗时 |
| --- | ---: | ---: | ---: | --- |
| 完成源码快照的默认后端全量 | 3608 | 2328 | 0／0 | 263.24 秒 |
| 既有要求／范围核查／摘要／动作 PG 组合 | 333 | 0 | 0／0 | 1385.08 秒 |
| 同一 CI 隔离环境下单独补跑评分请求预检 | 4 | 0 | 0／0 | 103.54 秒 |
| 固定来源版本／构建／人工编辑 PG＋S3 组合 | 76 | 0 | 0／0 | 771.31 秒 |

333 项组合与 4 项预检是两次真实运行；工作流将它们作为一个 PostgreSQL job 执行。作者检查实际使用临时 SeaweedFS 引导入口。各自固定测试数据库和 API／Worker 临时账号已核验清理。作者日志保留原有 Botocore 时间 API 弃用和测试 fixture 重复注册 router 的警告，没有通过过滤告警改变结果。

按 JUnit 的用例名去重，上述四次 Python 运行共 **3950 个不同用例通过**；原生检查执行了默认作业中跳过的 342 个用例，另有 **1986 个不同的外部／原生用例本轮未执行**。这些计数不代表全部外部系统或真实模型质量已完成验收，不将跳过记为成功。

首次提交 CI 时，本地最后一次完整前端回归仍在执行，尚未记为通过。已保留两次完整运行的失败证据：双 worker 运行的 183 文件／1815 项中 1814 项通过，一个既有详情测试超过原有 5 秒总时限；该文件独立复验 3 项通过（285 毫秒）。随后单 worker 运行仍有 1814 项通过，唯一失败为 `AuthoringLayout` 在默认 1 秒查询截止时来源资格仍在加载，总耗时 526.30 秒。

该布局测试现显式等待资格核对结束且正文可编辑，保留原有行为断言，并增加延迟快照期间禁止编辑／保存、核对后启用同一节点的回归。只修改这个测试文件；13 项相关定向回归已通过（10.84 秒）。最终单 worker 全量共 183 文件、预期 1816 项正在执行。CI 的单测总时限保持原值；frontend job 的 20 分钟上限为单 worker 全量、依赖和浏览器安装预留时间。最终计数将单独补充，远端 Actions 运行是本阶段待核验事项。

新版全域格式、lint、TypeScript 和生产构建已通过；概览和 B5 编辑各有桌面／手机、明暗主题四组合的真实 Chromium 结果，分别见相应功能阶段记录。

以上是本轮本地执行记录。GitHub Actions 是否实际启动并通过，须由提交对应的 runs／checks 核对，文件存在不等于远端 CI 成功。构建仍有既有大 chunk 提示；原锁中 pypdfium2 4.30.1 的上游撤回警告也保留，后续升级需独立核对解析方法与历史身份，未在本阶段擅自更换。
