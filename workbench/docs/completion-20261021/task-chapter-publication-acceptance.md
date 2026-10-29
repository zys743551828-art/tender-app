# F11-02 切片 A：章节任务的原生发布结果

日期：2026-10-21。范围：`chapter_suggestion` 原任务路径的 job 关联、真实 publication 终态、站内通知和任务结果预览。

本切片已通过 **19 项真实 PostgreSQL 17 用例、111 项纯后端回归、71 项前端用例、21 个真实 Chrome 场景**。模型 HTTP 全部使用明确的合成 `MockTransport`；真实外部模型请求和付费调用均为 **0**。没有修改远端，也没有新增 SQL 或放宽旧任务守卫。

## 1. 修复的问题与结果

旧任务把 `authoring-generate/1` 操作的 `succeeded` 当作章节任务成功。但这个操作只确认 `assistant_outputs` 中的候选已可靠保存，原生 `coordinator.publish` 仍可能没有执行，或因输入变化、项目关闭、原生提案创建失败而不发布。

现在任务读取会核验原生历史链，再投影业务状态：

| 实际原生记录 | 任务读取 | 站内通知 |
| --- | --- | --- |
| 原生操作 queued / running | 保留原生处理状态 | 不发完成通知 |
| 操作 succeeded、候选存在、尚无 publication | `awaiting_publication`，界面“等待提案发布” | 不发完成通知 |
| publication published，候选、action、job、章节基准一致 | `succeeded`，可审阅原生提案 | 持久记录一次此真实结果 |
| publication stale | `superseded` | 记录原输入已过期 |
| publication failed | `failed` | 记录发布失败，不把模型完成当作成功 |
| 原生操作失败或取消 | `failed` / `cancelled` | 记录真实终态 |
| 调用或预算账本仍有未知费用 | `reconciliation_required` 优先 | 记录需核账；新运行键、rerun 不得重复付费 |
| 原任务与原生历史记录关联无法核验 | `unknown`，不返回可用提案结果 | 不伪造成功 |

`succeeded` 表示原章节提案曾经真实发布，不表示用户采纳，也不表示项目通过评审。发布后来源再发生变化，不会改写历史发布收据；持久操作卡和原编制应用守卫负责决定当前是否仍可采纳。

### 原生历史绑定

新受理的章节任务保存 `task-authoring-binding/1`，包括 job/input digest、writing plan/digest、原生 operation、command、actor。读取时核验：

- 原不可变模板版本、冻结配置、任务输入摘要和父命令。
- 原生 job、writing plan、章节历史修订以及冻结规则/事实上下文。
- 历史 evidence 与具体 parse ID、document version、文本和物理页的关联；此核验不查询最新解析。
- `authoring.generation_queued` 的唯一 job/plan/operation/command 记录。
- 候选摘要、已入账的 model call、原生 effect receipt。
- 已发布 action 的 job/link/tool、request digest、章节基准和候选修改内容。

已受理的旧任务如果没有新增绑定字段，仍可使用原保存的 `assistant_job_id` 重建同一历史链；不回退到当前章节或 latest job。无法完整核对时保持未知。

### 通知恢复与旧通知兼容

独立任务 runner 的有界项目发现增加了已关闭项目中的原生章节终态。它仅核对已受理任务并补齐通知，生命周期守卫仍阻止新的任务工作。

通知与 `task.authoring_notification_bound` 审计关联在同一事务追加。该关联固定 notification key、run、job、publication、action 和结果摘要。旧版曾把 `candidate_ready` 当成功的通知原样保留，但缺少真实发布关联，不能压住升级后真实 publication 的新通知。第二次处理仍去重。没有改动 `TaskNotificationPayload` 的 API 格式。

任务面板明确说明通知保留当时记录，当前发布状态须打开绑定任务核对。站内通知没有发送邮件、Slack 或其他外部消息。

## 2. 仍然保留的真实边界

本切片仍然使用原 `source_version_ids` 路径。模板允许 `current_project` / `selected_versions`，任务受理时由既有编制流程选择解析、生成 writing plan 并冻结原生 job。

**这没有实现 `exact_package_authoring`。** 它没有把整包修订、需求清单、冻结输入、执行输入和依赖计划绑定到一个新的编制协议；也没有把旧 `version_ids` 转成“固定整包”。任务结果显式返回 `source_scope="legacy_section_and_source_versions"`、`automatic_apply=false`，界面展示这一边界。

未改对话自动化、原手动默认、已有精确整包否决任务语义或正式评分资格。没有自动应用正文、自动创建确认事实、自动提交或自动发布知识。

## 3. 真实 PostgreSQL 验收

入口：`deploy/task_chapter_acceptance.py`。最终原始收据：[`task-chapter-publication-receipt.json`](task-chapter-publication-receipt.json)。

环境为全新随机 loopback 端口的 PostgreSQL **17.11**、独立临时目录、合成账号密码。Owner 仅执行 schema/bootstrap 与明确的合成价格/预算夹具；实际 API 和 Worker 使用不同的非 owner LOGIN，测试显式检查角色。结束已停止本轮 PostgreSQL 并清理本轮数据库目录，没有写旧服务或旧库。

使用当前 BASE SQL，再安装真实 assistant、live facts、intent budget、generation batches 扩展。原始收据包含有序 SQL SHA-256、参与源码 SHA-256、每条测试结果、原样 HTTP 响应文件 SHA-256，且测试期间源码与 SQL 均保持不变。

真实路径是：HTTP 保存模板与 `/runs` 受理 → `queue_generation` → 原生 `authoring-generate/1` Worker → `assistant_outputs` → `coordinator.publish` → 原生 action/publication → `runs.notify`。不是直接塞入一条成功 operation 来代替业务执行。

| 用例组 | 数量 | 已验证内容 |
| --- | ---: | --- |
| 候选、原生发布与去重 | 1 | 候选阶段不成功、不通知；原启动 ACK 丢失重放；待发布 rerun 复用；重复 Worker 和 coordinator 只产生一次调用、一份提案；未自动改稿 |
| 发布前输入变化 | 3 | 章节修订、已确认事实、来源状态变化均变为 stale，不能发成功通知 |
| 原生发布失败 | 1 | 明确注入“真实提案插入后失败”，嵌套事务回滚 action，原生 publication 为 failed |
| 未知费用 | 1 | Mock HTTP timeout 真实进入未知账本；新键和 rerun 被拒绝，原键可恢复 |
| 取消 | 1 | 原 operation 的真实取消 API、Worker reconcile、重复取消 ACK，最终 cancelled 且没有模型调用 |
| 错误历史关联 | 4 | job ID、job input digest、operation ID、parse ID 被明确破坏时不投影其他成功 |
| 旧已受理任务 | 1 | 不含新增绑定字段时，仍重建原始 job 历史，不选当前输入 |
| 项目终止后的通知 | 3 | published、pending 后 stale、未知费用三种终态均能补通知；不重新打开项目、不创建新 run，通知后不再选入该项目 |
| 无效模型结构 | 1 | 原生操作失败、无候选与提案；真实账本为 failed + usage_reported，不误报未知费或成功 |
| Worker 前撤源 | 1 | 在源守卫处阻断，无模型 HTTP、无候选或提案 |
| 模板暂停与历史 | 1 | 暂停不重写已经受理的任务；既有 job 发布保持原版本，后续撤源不改写历史收据 |
| 旧假成功通知兼容 | 1 | 明确构造旧版通知收据，待发布仍不追加成功；真实发布并关闭项目后补一条带原生关联的新通知，保留旧审计 |

总计 **19 passed、0 skipped、0 failures**，运行 **30.708 秒**。所有原件、价格、预算和模型输出都是合成验收资料，不证明模型写作质量或真实商业报价资格。测试禁止真实同步/异步 HTTP transport；对象存储使用合成内存字节，这里不声称验证了 S3/Kafka 部署。

## 4. 前端与浏览器

共享 OpenAPI / `contracts.ts` 已由主集成加入 `TaskAuthoringResult` 和 `awaiting_publication`。任务面板没有使用额外临时类型或伪造 API 能力。

`TaskRunCard` 先核对 run/job/operation/section/binding/result 关联。仅在真实 publication 允许时打开独立只读结果面；获取 action 后再次校验 action、job、project、section 和 revision。身份不一致时不展示或链接其他提案。原始输入与业务结果核对失败时，不继续显示一个“已完成”状态徽章。

正确提案复用 `AssistantPatchComparison` 展示实际原稿、拟稿和文字增删。打开或切换对照只发 GET。需要采纳时，用户通过该 action 的固定链接进入现有持久操作卡；没有新增自动采纳入口。重新读取不再确认原 publication 时，旧提案入口移除。

`apps/web/src/test-fixtures/task-chapter-http.json` 的 10 组正文来自最终 19 项原生验收的真实 API 响应，和原导出 JSON 在数据上逐项相等。前端测试 **71/71** 通过，其中新协议测试 29 项、新章节组件测试 12 项，另有原任务面板和精确整包任务回归。

[`task-chapter-publication-browser.json`](task-chapter-publication-browser.json) 记录真实 Chromium **156.0.8078.47** 的 **21/21** 场景：1280、768、390 像素 × 待发布、已发布、章节过期、未知费用、取消、任务错绑、提案错绑。390 为深色主题。检查了真实组件、固定提案链接、文字差异、移动端前后稿切换、无写请求、无意外 HTTP、无横向页面溢出和无 JavaScript 错误。任务错绑和提案错绑两类为明确的响应错误注入。

浏览器回放没有连接业务数据库、没有调用模型。实际数据库链路由上节独立验收提供。已目视检查宽屏发布结果、窄屏深色发布结果和窄屏待发布结果。

## 5. 静态检查与复现

[`task-chapter-publication-checks.json`](task-chapter-publication-checks.json) 保存冻结源码摘要、原生/浏览器收据摘要、fixture 对等结果和检查清单。Ruff、5 个生产 Python 文件的 mypy / Bandit、前端 owned 文件的 Prettier / ESLint 与 `git diff --check` 均通过。纯后端契约、输入、解释器、调度和守卫回归为 **111/111**。整站 tsc 与完整应用回归由主集成统一执行，独立收据不冒充整站验收。

在仓库根目录使用已有 Python 环境与 PG17 prefix：

```bash
"$TENDER_PYTHON" -m deploy.task_chapter_acceptance \
  --pg-bin "$TENDER_PG_BIN" \
  --receipt /tmp/task-chapter-new-receipt.json \
  --http-fixture /tmp/task-chapter-new-http
```

收据路径与导出目录必须是新的。脚本不安装依赖、不继承模型密钥，不连接现有数据库。`--http-fixture` 导出的每个状态文件已经包含真实 run、历史模板版本、operation/ETag 和相应 proposal；需要更新前端 fixture 时，按现有聚合文件的同名键原样合并，不改响应身份或状态。

前端在 `apps/web` 运行：

```bash
node_modules/.bin/vitest run src/taskAuthoringProtocol.test.ts \
  src/TaskChapterResult.test.tsx src/TaskPanel.test.tsx \
  src/ExactPackageTaskUI.test.tsx

PLAYWRIGHT_MODULE="$TENDER_PLAYWRIGHT_MODULE" \
CHROMIUM_PATH="$TENDER_CHROMIUM_PATH" \
node scripts/check-task-chapter-browser.mjs /tmp/task-chapter-new-browser
```

浏览器脚本生成本轮截图、实际源码摘要和 `receipt.json`，并关闭自己的 Chrome / loopback HTTP 服务。

## 6. 交接文件

本切片拥有的生产后端：`packages/tasks/{models,runs,runner,authoring_result}.py`；验收入口和测试：`deploy/task_chapter_acceptance.py`、`tests/test_task_chapter_results_pg.py`。

前端生产文件：`TaskRunCard.tsx`、`taskState.ts`、`TaskPanel.tsx`、`TaskAuthoringResultPanel.tsx`、`taskAuthoringProtocol.ts`。前端验收文件：`taskChapterFixtures.test-support.ts`、`taskAuthoringProtocol.test.ts`、`TaskChapterResult.test.tsx`、`test-fixtures/task-chapter-http.json`、`scripts/check-task-chapter-browser.mjs`。

文档与证据是本文件及同前缀的 `receipt.json`、`browser.json`、`checks.json`。共享契约生成与 `AssistantPatchComparison` 由主集成拥有，本切片只引用。下一切片 `exact_package_authoring` 先提交独立设计，不通过旧 latest parse 路径实施。
