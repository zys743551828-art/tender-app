> 当前开发分支为 `dev`，跟踪 `origin/dev`；下文独立分支名称与SHA为合并前检查点。正式文档现维护于 tender-docs 的 dev。

# AI投标工作台（当前开发检查点）

当前安装与操作入口：[工作台使用说明](https://github.com/zys743551828-art/tender-docs/blob/dev/使用说明.md)。Desktop full/2 使用固定依赖配方、官方预构建 Gotenberg 和安装后的 Word 执行器；按说明中的实际验收记录选择已验证的应用提交。

当前实现位于 `dev`；[正式实现架构](https://github.com/zys743551828-art/tender-docs/blob/dev/05-技术与设计/工作台实现架构.md)、[运行与验收](https://github.com/zys743551828-art/tender-docs/blob/dev/05-技术与设计/工作台运行与验收.md)、[需求追溯](https://github.com/zys743551828-art/tender-docs/blob/dev/02-业务与产品/实现追溯矩阵.md)与使用说明共同维护实际能力、验证提交和剩余条件。下文早期检查点保留其原范围。

开发统一使用 `dev`（`fusion/bid-workbench`保留来源历史），以本目录为唯一新系统主线，吸纳原dev机制与视觉。整份标书目标与任务以文档仓库[融合实施计划](https://github.com/zys743551828-art/tender-docs/blob/dev/00-项目管理/标书工作台融合实施计划.md)为准；Windows本机检查见[本机融合验证环境](docs/fusion-local-checks.md)。下方原交接和早期运行说明是来源记录，不替代融合目标或当前验收。

新成员请先按[正式首次启动与工程演示](https://github.com/zys743551828-art/tender-docs/blob/dev/05-技术与设计/工作台运行与验收.md#首次启动与工程演示)选择环境。以下阶段交接只保留其检查点范围：[完整交接入口](docs/handoff-20261017/START_HERE.md)、[待办](docs/handoff-20261017/BACKLOG.json)与各角色交接。当前源码包含已验候选与尚未放行的增量，不能按下方历史首切片说明判断整体完成，亦不能直接执行未审初始化SQL。

Word 当前使用官方预构建 Gotenberg，原件保存、受控转换、当前 PDF 采用与对应检查资格分别显示。Desktop full/2 的安装接线、容器内 Worker、本机执行器及生命周期见 [Word 执行说明](docs/word-execution.md)；full/1 保留原兼容契约。各项工程实测与正式业务验收的边界见使用说明。

源码交付位置为 `tender-app/workbench/`，正式使用说明与验收记录位于独立 `tender-docs` 仓库。生产发布与真人业务验收依其正式条件执行。

规则页的“补遗来源核对”仅允许明确选择受影响旧条款、补遗逐字依据和当前全部歧义，再二次确认局部替代；保留无关条款，结果最多为 `partial`，不会授予完整资格或自动复评。包含“其余招标要求保持／不变”的局部补遗不能整份替代原要求。模型提取中的逐字摘录失败最多允许一次独立记账的校正，一次反馈汇总全部违规摘录；仍检查原证据、保持规则结构和已有效摘录，不能靠删除要求消除错误。新策略改变评审方法身份，旧冻结任务不能直接改用新方法重放。

隔离恢复验证入口 `deploy.extended_recovery_runtime --case migration` 新增两个独立 PG17 集群间的合成恢复及有限 API 烟测。它仅接受本轮生成的独立集群和备份，恢复隔离检查后才按源实际权限投影激活目标 API；不会开放其他运行角色，也不是生产迁移工具。实际登录、原件下载、幂等写与精确回收的证据及生产边界随正式使用说明维护，不能以此宣称在途任务或完整生产恢复已验收。

历史补全工作位于分支 `work/bid-workbench-completion-20261021`。请从 [启动与操作验收](docs/completion-20261021/START-HERE.md) 进入，按 [当前进度与验证记录](docs/completion-20261021/PROGRESS.md) 核对编写、Word 导入、多章节 AI 候选、解析、范围核查、人工复核、对比和报告的实际交付。Fusion v10 预览与完整 Worker 运行环境有不同能力，具体启动条件和未完成项均在这两个入口说明。

当前实施版 OpenAPI 快照为 `packages/contracts/fusion-implemented.openapi.json.gz`，完整 schema 与路由未删减。更新命令为 `python -m apps.api.export_openapi --output packages/contracts/fusion-implemented.openapi.json.gz`；随后在 `apps/web` 执行 `npm run contracts:generate`。运行时 `/openapi.json` 和不带 `--output` 的导出仍返回普通 JSON；详细用法见 [后端说明](apps/api/README.md) 与 [前端契约生成](apps/web/README.md#契约与验证)。

---

以下保留早期PDF切片运行说明及后续topic增量记录，作为历史启动资料；新集成环境须遵守交接的固定候选/19SQL/独立角色/资源与费用边界。

# AI投标工作台

全新系统的源码工程。产品与技术主记录在[文档工程](/workspace/tender-docs/README.md)，团队职责、当前范围和依赖由[实施任务板](/workspace/tender-docs/00-项目管理/实施任务板.md)维护。

当前实现的是T0底座的首个PDF资料切片：登录、项目、私有上传、字节核验、批次和版本、后台操作、PDF解析范围及物理页证据。核心评审、RAG、完整评分研究、Word转换／导出和提交闭环按后续切片交付。未配置的评审返回明确不可用，不产生演示风险或预测分数。设计放行不等于实际软件、模型质量或生产验收通过，实际结果见`qa`及文档工程的实现验收记录。

## 运行

要求Python 3.12、Node 24、Docker Compose，至少6GB可用内存。服务仅监听本机。固定镜像的PG17＋pgvector、Kafka和SeaweedFS S3用于独立开发环境，真实OSS及生产容灾另行验收。

在本目录创建后端环境并安装锁定依赖：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
python deploy/configure_local.py
docker compose --file deploy/compose.yaml --env-file .env up -d
docker compose --file deploy/compose.yaml --env-file .env ps
```

PG与Kafka健康后初始化**全新空库**。数据库初始化遇已有schema会拒绝，不会清库；不要在已保存资料的库重跑。

```bash
.venv/bin/python deploy/initialize_database.py
.venv/bin/python deploy/initialize_topics.py
.venv/bin/python deploy/initialize_topics.py --check-only
docker compose --file deploy/compose.yaml --env-file .env exec -T object-store weed shell -master=localhost:9333
```

Kafka初始化默认读取已实施的`apps/worker/execution-policy-11.json`，创建并核验9个主题，包含独立比较、项目助手、全局助手运输。重复运行只补缺失主题，校验已有主题的分区、副本和保留配置，不覆盖配置或删除消息。`check_environment.py`及`check_external.py`使用同一个默认协议，只读核验主题、分区、副本和保留配置，不会把旧6主题环境判为完整。`--check-only`只读核验，缺主题即失败；`--bootstrap`明确选择集群，`--expected-cluster-id`可防止误连后写入。需要某个明确快照时使用`--policy <策略文件路径>`；`packages/contracts/policies/execution-policy.json`保留目标快照，不能用其旧6主题配置代表当前全部运输。初始化主题不启动消费者，也不授予模型调用权限。

在存储管理终端输入`s3.bucket.create -name=tender-private`，完成后用`Ctrl-D`退出。该管理动作创建私有bucket；应用存储身份只有此bucket的读写及列举权。然后执行：

```bash
.venv/bin/python deploy/initialize_object_store.py
.venv/bin/python deploy/check_environment.py
.venv/bin/python deploy/check_compose.py
.venv/bin/python -m apps.api.bootstrap --login your-login --name 你的姓名
```

成员口令由终端安全输入。本会话准备的本地成员访问资料保存在被忽略的私有文件`.local/dev-access.json`，只用于本机开发。`.env`含随机配置，权限600，不提交Git。正式部署为每个进程分别注入所需能力身份，初始化owner仅用于建库。

分别在终端运行；只启动本环境已授权的执行通道：

```bash
.venv/bin/python -m apps.api
.venv/bin/python -m apps.worker relay
.venv/bin/python -m apps.worker consume
.venv/bin/python -m apps.worker consume-export
.venv/bin/python -m apps.worker consume-comparison
.venv/bin/python -m apps.worker reconcile
```

`consume`受理文档、Word转换和派生索引，`consume-export`受理构建/报告，`consume-comparison`只受理无费用比较。普通`consume-review`和`consume-assistant`可能调用收费模型，不随初始化自动启动；全局助手使用独立`packages.assistant.transport`运输，不加入普通Worker订阅。研究、任务控制面和助手控制面也按各自受控运行协议启用。

API为`http://127.0.0.1:8800`。另开终端运行前端：

```bash
cd apps/web
npm ci
npm run dev
```

浏览器打开`http://127.0.0.1:5173`。项目详情深链接为`/bids/:bidId/materials`，页面刷新保留所指项目。PG端口55439、Kafka19093、S3 19000；API与Worker均使用非owner LOGIN。

## 切片范围

| 能力 | 当前边界 |
| --- | --- |
| 登录及项目 | 同源Cookie／CSRF、服务端会话撤销、幂等创建、分页及持久化 |
| 上传与版本 | PDF单传、SHA256及实际长度核验；明确用途、新文件或新版本目标；verified原件显式重绑定后再次CAS提交 |
| 后台执行 | PG Outbox→Kafka→独立Worker，手动offset、租约／fence、去重及失联对账；实际测试覆盖以证据为准 |
| 解析及证据 | PDFium文本页和物理页证据；OCR、复杂表图及未读范围明确显示缺口，解析不是评审完成 |
| 其他格式 | 本切片只接受PDF；外部Word先导出PDF。未接受的DOCX不显示“已保存” |
| 评审及模型 | 没有配置真实模型，不返回假风险／分数；完整A1、RAG及评分研究仍有各自实施与验收任务 |

`packages/contracts/implemented.openapi.json`只列实际注册接口。`packages/contracts/openapi`等是已审完整目标快照，其存在不代表全部目标能力已实现；实施补充见[契约说明](packages/contracts/README.md)。

## 测试与独立验收

```bash
.venv/bin/ruff check apps/api apps/worker packages/domain deploy tests
.venv/bin/ruff format --check apps/api apps/worker packages/domain deploy tests
.venv/bin/mypy apps/api apps/worker packages/domain deploy
.venv/bin/bandit -q -ll -r apps/api,apps/worker,packages/domain,deploy
.venv/bin/python -m pytest
```

后端真实PG／Kafka／S3纵向自测按`tests/test_slice_integration.py`的显式开关执行，未启用时跳过不计通过。前端运行`npm run format:check`、`lint`、`typecheck`、`test`、`build`。独立应用验收按[qa说明](qa/README.md)执行。

QA使用独立配置`.local/qa.env`、独立数据库、Kafka及存储；通过`deploy/run.py --env-file .local/qa.env -- <command>`注入配置，不在命令行传口令。对应端口为PG55440、Kafka19094、S3 19002、API8801和web5174。可用`python deploy/configure_local.py --profile qa`创建新QA配置，已有配置会拒绝覆盖。QA基础设施启动时给Compose传该配置，再按相同初始化步骤运行；前端用`API_PROXY_TARGET=http://127.0.0.1:8801 npm run dev -- --port 5174`连接QA API。

所有测试资料为明确的合成输入。真实模型质量、真实投标人员试用、正式评分精度和生产运行恢复各自验收，机制验证不授予这些资格。

一次性 Docker 测试须使用[资源规则与收尾入口](docs/docker-test-hygiene.md)，记录本轮容器/网络/卷，正常、失败及取消均精确回收；持久开发环境和历史资源不能混入自动清理。

新增预测原生安装、传输及隔离恢复验收入口：`deploy/prediction_native_acceptance.py`。正式结果见文档仓[预测原生联合验证](https://github.com/zys743551828-art/tender-docs/blob/dev/04-验证与测试/预测原生联合验证.md)，区分拒绝链、恢复机制和未完成的正式预测正向链。

当前原生执行安装使用 `material-execution-attempts-v2.sql`，方法/3撤销内部helper的PUBLIC执行；恢复生成格式为/3（完整）或/4（预测对象扩展），旧/1与/2按旧清单只读恢复。失败与复验见[dev CI原生权限修复](https://github.com/zys743551828-art/tender-docs/blob/dev/04-验证与测试/dev-CI原生权限修复.md)。

测试专用预测成功链使用独立且不可晋升的 `prediction-sandbox/1`：已登记测试库显式安装、独立HTTP应用/CLI、原任务与Worker、独立测试结果。业务API/正式报告Word/registry不消费测试资格；跨库恢复或数据库实例变更使旧资格失效。运行入口与版本边界见[正式协议](https://github.com/zys743551828-art/tender-docs/blob/dev/05-技术与设计/测试专用预测认证协议.md)。`python -m packages.prediction_sandbox.cli --help` 可查看测试消费入口；无需配置或调用真实模型。

报价历史按保存时间倒序，UUID游标按同项目的时间/ID继续。独立PG17/私有S3及实际PricingPanel验收使用`deploy/ci_checks.py --suite pricing --disposable-postgres --weed <已校验二进制>`，必须注入临时CI_POSTGRES_DSN和显式浏览器工具。公式与手算、保存/重放、API重建和桌面/窄屏回读均单列；详见[报价模块说明](packages/pricing/README.md)。合成工程验收不代替真实报价条款业务签收。

四组既有工作流的真实App/原生服务组合验收复用上述pricing聚合：`scripts/native-workspace-journeys.mjs`由原生pytest启动，不提供业务测试后门。覆盖实际报价写入、事实与知识状态、任务取消/通知恢复，以及生命周期API/页面显示；合成来源目录和队列准备不是实际上传/转换。详细范围、失败尝试和回执见[四组正式记录](https://github.com/zys743551828-art/tender-docs/blob/dev/04-验证与测试/工作台四组原生组合验收.md)。

FR015 项目设置现提供“项目阶段与归档”：从既有服务器 allowed_actions 展示动作，原因与二次确认、旧版本冲突、原请求回执恢复、归档阻塞与同轮重开均复用原API。前端类型从现有LifecycleChangeRequest/ProjectLifecycleView快照生成，不新增权限、SQL或环境变量。真实App/PG/S3及连接截断恢复使用上述pricing原生聚合；详情见[FR015正式记录](https://github.com/zys743551828-art/tender-docs/blob/dev/04-验证与测试/FR015生命周期表单原生验收.md)。


## 团队运行反馈与配置边界

[正式排障说明](https://github.com/zys743551828-art/tender-docs/blob/dev/05-技术与设计/团队运行故障排查.md)对照了旧 backend 与当前 workbench。根 deploy/Compose 是历史系统，不要混用 PG16/PG17 或 BIDWB_STORAGE/OBJECT_STORE 配置。根 Settings 不自动读取 .env；由已有启动器明确注入。virtual S3 兼容端点不能含桶名前缀；当前同源上传不要求开放桶 CORS。SDK仅必要 checksum、Worker安全阶段日志和严格规则失败分类由离线回归覆盖，未实际连接团队 OSS 或调用模型。不要提交或记录秘密及完整签名 URL。

## 启动前离线配置检查（不连接服务）

在 `workbench/` 执行 `python -S deploy/configuration_check.py --entry workbench --role api --env-file .env`。只需标准库，检查所选私有普通文件、唯一赋值、入口变量族和必需项；输出不含配置值。旧根 Compose 则选择 `--entry legacy-compose`，直接启动旧后端选择 `--entry legacy-direct`。三者不可混用；检查成功不是依赖连通或业务验收。模型可保持未配置，不因此启用任何调用。

本地 `deploy/run.py` 现在在执行子进程之前拒绝缺失文件、旧变量族、重复/畸形赋值或缺少显式角色 DSN，不能靠继承的 DSN 掩盖选错文件。POSIX 文件权限应为600；不自动修改文件、云配置或凭据。full Compose 仍使用既有固定 profile/source 校验，不替换其协议。
