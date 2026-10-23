# F11 精确整包事件与定时触发：后端独立验收

日期：2026-10-21。范围：明确保存的整包否决核对输入，经独立任务 runner 接受事件／定时意图，进入既有原生整包核查，读取当前状态、取消及站内通知。本证据独立于 F09 检索容量验收；不把本轮结果归入检索回执。

## 结果与适用范围

全新临时 PostgreSQL **17.11**、独立非 owner API／Worker 登录通过 **37 项**实际数据库／ASGI／原生 Worker 用例，**0 失败、0 错误、0 跳过，164.553 秒**。其中自动触发 **14 项**，既有精确手动任务回归 **23 项**。测试采用合成原件和显式 `httpx.MockTransport`；外部模型调用与付费调用均为 **0**。实际调用原生 Worker handler，核对原生 operation、outbox、结果及 SSE 持久记录；本轮没有启动 Kafka broker，不声称验证了真实 Kafka 消费运输或模型业务效果。

原始机器回执：[exact-package-trigger-receipt.json](exact-package-trigger-receipt.json)，SHA-256：

`fd94ebf0f142d9d80a28bcaa0ffb8d3b389820cae456a6e2bc2088f972e95b6f`

回执记录实际 JUnit 用例、Python 3.12.14、PG 版本、任务源码与顺序 SQL 摘要，以及运行前后源码／SQL 均未变化。初始化 owner 仅用于新库建表、账号引导和明确的反例故障注入。业务 API、触发协调器和 Worker 分别走实际非 owner 权限。新库和口令已清理，没有修改旧环境、旧库或远端。

当前共享 OpenAPI／前端注册表由集成负责人在下一批统一生成；本文件冻结后端证据，不据此宣称 F11 四类领域处理器或前端整包任务全部完成。

## 明确输入与触发契约

| 模式 | 触发 | 行为 |
| --- | --- | --- |
| `exact_package_review` | 仅 `manual` | 保持原手动契约、原命令、原 SQL 守卫。保存不运行。 |
| `exact_package_trigger` | 显式 `material_updated` 或 `schedule` | 保存同一组十个确切输入 ID／摘要；只允许 `denial_check`，不得指定章节。 |

十个输入字段为整包、修订、要求清单、冻结输入 ID／摘要、执行准备 ID／摘要、依赖计划 ID／摘要和方法摘要。事件仅唤醒已保存的输入，不选择事件中的新包、`latest`、`current_body` 或其他轮次；保存事件发生时的真实 `materials.committed` ID、当时资料快照、模板版本、成员和去重键。事件生效窗口之前的事件被忽略，非当前事件被记录为过期。原件核验期间事件变化时，本次意图阻断，不改用后来事件。

新自动模板调用旧 `POST /task-definitions/{id}/runs` 返回 `409 TASK_PACKAGE_TRIGGER_EXPLICIT_WAKEUP_REQUIRED`。需要人工启动一次时，先明确核对确切输入并保存为手动模式；不能把漏时恢复解释为自动运行当前最新包。

保存模板不读取原件、不调用模型。协调器只在事务内持久保存 `task-package-trigger-intent/1`。runner 提交并关闭该连接之后，才在锁外读取原件、验证实际摘要。最终短事务重核项目生命周期、原模板版本／暂停状态、事件或计划身份、来源权限及执行条件，再建立 `task-package-trigger-run/1` 与原生 `package-scope-review` 的不可变绑定。运行期依旧使用现有原生 Worker 预算、模型账本、取消和结果守卫。

## 定时与恢复语义

默认仍为 `manual`。明确选择定时后保留已有 cron／时区校验，默认时区 `Asia/Shanghai`，模板返回下一计划时刻。独立进程未启动时，不会因浏览器打开页面、保存模板或展示下一时刻而调度。

- 一次轮询最多发现 50 个项目；项目间使用原服务器游标轮回。每项目最多接受 50 个到期计划、扫描 50 个资料事件、恢复 10 个未决整包意图并扫描 100 个通知候选。事件模板超过 100 个时整轮拒绝，不截断后假称完整。
- 未观察到的到期时段延迟达到一分钟时，记录有界漏时范围，跳到下一计划时刻，不逐个枚举、不自动补跑。自动整包模式的恢复记录为 `skipped_reconfirm_exact_input`，`run_current_once_ref=null`，返回原模板的 `reconfirm_template_ref`。
- 已持久接受的 pending 意图与未接受的漏时不同：进程重启后继续核对该意图的原身份。模板改版／暂停、项目关闭、原事件过期或来源失效时保存阻断终态，不替换输入。
- 同输入同模板的后续事件可复用原任务／原生运行。费用处于 reserved／unknown 时阻断新运行，不通过新事件或新模板绕过账本；显式复检仍须重新准备带理由的确切输入。
- 意图取消只取消尚未关联原生运行的 pending 意图；已 accepted 返回 `409 TASK_TRIGGER_ALREADY_ACCEPTED` 与原任务链接，转到原生 operation 的取消入口。原取消请求使用原 ETag、原幂等键恢复。
- 关闭项目仍可回补已接受原生任务的终态通知；此扫描不授权关闭项目新执行。通知按既有状态摘要去重，费用待核对转入实际终态后仍能继续发现。

## 实际反例与结果

| 验收面 | 原生证据 |
| --- | --- |
| 事件到真实任务 | 持久事件→pending 意图→原件锁外核验→原生任务→Worker 合成 HTTP→结果→站内通知／SSE；重复事件和重复 Worker 投递不增加模型尝试。 |
| 完整原输入与复用 | 比较模板的十字段选择与任务冻结输入；后续新事件同输入仅复用一个任务／一个原生运行。 |
| 并发恢复 | 两个恢复者同时完成锁外核验，仅发布一个原生运行，回执一致。 |
| 原件核验期间竞态 | 模板改版、暂停、关闭、来源撤回及新资料事件五种反例均阻断；不产生新任务、原生运行、操作或 outbox。 |
| 定时与漏时 | 一个确切到期时刻仅一次；计划回执绑定原 `scheduled_at`。三天漏时不生成补跑，返回重新确认确切输入。 |
| 取消 | pending 取消、同键恢复、已取消意图恢复；已受理原生运行按原 operation 取消并由普通 reconcile 收敛，模型尝试为零。 |
| 未知费用 | 模拟 HTTP 回执丢失，一次模型尝试；重复 Worker 不再发；新事件阻断为账本待核对，原意图 ACK 不被当前状态替换。 |
| 强制存储约束 | 伪造父命令 ACK 的触发身份，延迟约束在提交时拒绝；任务／原生运行／outbox／resolution 原子回滚，原 pending 意图保留。 |
| 项目关闭恢复 | 独立 runner 将 pending 意图保存为关闭阻断；对已接受且随后失败的原生运行，在项目关闭后只回补一份通知。 |
| 稳定目录分页 | 按 `(created_at,id)` 排序；故意令后插入意图的 UUID 更小，分页仍按创建顺序完整读回，未知游标返回 404。 |
| 权限与旧行为 | API 不能更新／删除意图；Worker 无 INSERT 权限；旧 manual 模板收到事件不运行；23 项原 manual 反例保持通过。 |

原始触发 ACK、当前意图、当前任务状态分别读取：意图被接受不表示核查成功，任务已完成也不改写原触发 ACK。站内通知与 SSE 持久记录不代表外部消息送达。

## SQL 自审与挂载清单

新增 `packages/contracts/sql/task-package-triggers.sql`，必须在 `task-package-reviews.sql` 之后应用。执行前自审 SHA-256：

`ca96f73baec6e5b3db739da5420db1e6efdde0769c0c2d8fd49e7c5fd8cea45f`

新增不可变 intents／resolutions；API 仅 SELECT／INSERT；没有 Worker／PUBLIC 表授权，没有 `SECURITY DEFINER` 或删除已有表。原手动 `task_package_binding_guard()` 的完整主体作为旧分支逐字保留，其 SHA-256 为 `44aa9ab31a690aa6fbfe537c30335ad193f0467ce82ddae49a8ee076f9aaddf8`。入口先依据实际模板版本及新模式／schema 分派到严格自动守卫，不能把自动模板藏在旧 manifest 中绕过原生绑定。

新增意图、resolution、自动 task binding 的约束核对原请求命令、成员、模板版本、配置摘要、事件／计划、原生运行、父子命令 ACK、复用审计、计划回执及通知审计。关键完整性约束延迟到事务提交，允许原子建立整个关联后再核验。

已有 `apps/api/task_routes.py` router 内新增以下路径；根集成需要将它们加入实际 OpenAPI 导出允许列表并重新生成前端契约／注册表：

- `GET /api/v1/bids/{bid_id}/task-package-trigger-intents`
- `GET /api/v1/bids/{bid_id}/task-package-trigger-intents/{intent_id}`
- `POST /api/v1/bids/{bid_id}/task-package-trigger-intents/{intent_id}/cancel`

详情 ETag 为 `"task-package-trigger-intent:{id}:{input_digest}"`；取消 body 为 `{"reason":"明确取消原因"}`。`GET /task-kinds` 的否决核对新增 `exact_package_triggers`，如实标示 `requires_independent_runner=true`、不自动选输入及补跑为零。

独立 runner 入口仍为 `python -m packages.tasks.runner`；本轮没有自动启用部署服务，也没有创建、恢复或改变对话自动化。

## 重现与静态验证

复现必须提供已安装 UUID／pgvector 扩展的本地 PG17 二进制目录；脚本显式核对 PG17、自审 DDL 摘要，启动全新数据库和随机回环端口，最后清理。Python 环境使用现有 requirements，不向旧环境安装依赖。

```sh
python -m deploy.task_package_trigger_acceptance \
  --pg-bin /absolute/path/to/pg17/bin \
  --reviewed-sql-sha ca96f73baec6e5b3db739da5420db1e6efdde0769c0c2d8fd49e7c5fd8cea45f \
  --receipt /tmp/new-task-trigger-receipt.json \
  --http-fixture /tmp/new-task-trigger-http
```

HTTP 导出可省略；本轮导出 16 份实际 ASGI 合成数据响应，剔除会话、CSRF、口令和签名 URL，用于前端契约反例。回执记录各份内容摘要。对应合并夹具为 `apps/web/src/test-fixtures/task-package-triggers-http.json`。

本轮后端静态结果：ruff check 与 format **20 文件通过**；mypy **18 源文件通过**；Bandit **0 报告项**；`test_task_package_inputs.py`、`test_task_scheduling.py`、`test_task_draft_interpreter.py` 共 **104 项通过**；相关 `git diff --check` 通过。仅对明确本机 subprocess 及受控 XML 保留现有精确 `nosec` 标注；不接受动态拼接查询，runner 已使用 psycopg SQL 组合。

## 剩余真实边界

本轮只关闭精确整包否决核对的后端事件／定时链。`scoring_review` 继续返回 `TASK_SCORING_NOT_QUALIFIED`，需要另行接入完整技术评分生产者；`supplement_impact` 仍只是已登记效力关系核对，语义影响为 unknown；`chapter_suggestion` 是现有章节提案队列，尚不代表精确整包生产者。受限中文任务草案保留，不声称实现任意自然语言工作流。真实标书质量、真实环境长期调度和实际 Kafka 运输仍需各自证据。
