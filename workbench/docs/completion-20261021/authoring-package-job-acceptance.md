# 固定整包章节任务 B2：原生执行与候选发布验收

本次范围是 `exact_package_authoring` 手动任务从已保存 B1 输入，经现有原生 Worker、共用费用账本，走到真实候选发布和站内通知。任务成功表示提案已实际发布。采用正文、产生修订来源资格与后续构建分别属于 B3、B4；本批返回 `apply_available=false`、`build_available=false`，确认采用返回 `AUTHORING_PACKAGE_APPLY_NOT_CONFIGURED`。

本批最终原生验收为 **60 项通过、0 失败、0 跳过**，耗时 315.819 秒，源码及 SQL 在执行期间均未变化，所建临时服务已关闭。选定回归为 204 项通过、3 项跳过；跳过的是另外三项要求独立 `fusion_budget_lock` 数据库的旧锁序测试，本批不把它们计为原生通过。Ruff 检查及格式核对覆盖 26 个 Python 文件，Mypy 和 Bandit 覆盖 22 个非测试源文件，均通过。B1 的 14 个冻结路径摘要仍完全一致。完整源码摘要、逐项测试、SQL 顺序和实际命令输出保存在同目录的 `authoring-package-job-receipt.json`、`authoring-package-job-checks.json`。

## 实际路径

| 阶段       | 实现及实际效果                                                                                                                                                |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 明确选择   | 模板只保存 B1 输入 ID、摘要与同一目标章节；模板版本保存指令。没有 `latest`、`version_ids` 或当前事实补全。                                                    |
| 私有草稿   | TaskDraft 保留相同精确输入，明确手动章节意图才可保存模板；自动、含糊或缺少目标的文字保留为未决私稿，不启动任务。                                              |
| 受理       | 重读完整冻结上下文，在数据库事务之外核验真实 S3 原件，再在锁内复核输入、声明、模板 CAS 与最终会话。                                                           |
| 原子入队   | 同一事务创建 task、writing plan、assistant job、原生 operation、共享预算义务、不可变绑定、原始 ACK 与审计。                                                   |
| 费用与执行 | 使用原 `authoring-generate/1` handler、`authoring-generate` step 和 `authoring.generate/1` 调用键。旧模式与新模式共享五项业务身份、章节和用途构成的费用范围。 |
| 候选       | 整个选中上下文作为受控 prompt 数据提交；模型仅能返回目标稳定节点的纯文本替换及冻结证据 ID。Worker 完成对应 `awaiting_publication`，尚无完成通知。             |
| 发布       | API 发布器重新核对真实 job/input/plan/output、来源、事实、规则、目标及费用终态；在同一事务写 proposal、action binding、publication、action link 和审计。      |
| 读取与通知 | 原生历史绑定投影区分 published、stale、failed、cancelled、unknown fee。原任务与提案保持可读；站内通知按真实发布终态去重，关闭项目仍可补记原通知。             |

两个完整包中的逻辑成员、完整物理页、证据块、规则清单、选择事实、原稿和来源闭包保留在冻结计划中。B1 的上下文容量上限不是 B2 的模型容量保证：B2 还检查实际请求字符上限与冻结价格输入硬上界。超限会回滚入队，不截断内容。

## 受保护的权限边界

新增可选 SQL 为 `packages/contracts/sql/authoring-package-jobs.sql`。依赖 B1 输入 schema 和现有 `assistant.sql`、`live-facts.sql`、`intent-budget.sql`；不加入 BASE，不修改旧部署卷。只有已显式配置完整执行器时，`/api/v1/task-kinds` 的 `chapter_suggestion.exact_package_authoring.available` 才为真。

`generation_mode` 只决定路由分派。SQL 核对不可变 `authoring_package_job_bindings`、原 job/operation/plan/task、模板、命令 actor/target/request、完整输入及指令摘要。普通 job JSON 中写入同名模式不能提交为有效 exact job，也不能获得预算许可。延迟约束还逐字段核对完整原始 ACK、实际持有的预算和原生审计；伪造更小的输入并重新计算摘要仍被拒绝。

既有 `assistant_assert_job_authority(uuid)` 保持原签名和完整 legacy 分支。真实 exact binding 进入独立 SQL 核验。旧路径继续执行原 latest-parse/current-material 守卫；本批没有把旧路径包装成固定整包。

API 与 Worker 均使用独立非 owner LOGIN。Worker 不新增 B1 输入、事实、exact binding 等业务表的读取或写入权限，通过固定 `search_path` 的受限 `SECURITY DEFINER` 核验入口执行当前授权检查。PUBLIC 和应用角色不能调用内部核验函数；绑定表只追加，不可更新或删除。

## 复用、费用和取消

相同原命令键先核验历史绑定并返回原完整 ACK，不因原件后来不可用而重新付费。当前运行状态通过单独 GET 读取，不覆盖原受理内容。首次入队回执中的状态是 `queued`；新的明确复用命令保存它受理时读到的原任务状态，可能已经完成、取消或处于费用未决。两种回执完成后均由 B2 专用数据库触发器保护，不能再改写，legacy 命令分支保持原行为。恢复时还逐字段核对原生 job、plan、operation、input、固定结果字段，以及当时已包含的真实候选和发布身份。

同一模板版本、同一输入换 HTTP key 复用原运行；原请求的 `rerun=true` 不被接受。更换模板版本、B1 input ID、指令、模型或包导航身份不能绕过同一业务对象的未决义务。旧与新编写模式之间的同对象费用防重也使用实际原账本核对。

已结清的 exact 运行也按真实完整 `context_digest`、规范化编写指令和冻结 `execution_policy_digest` 查找。仅改模板名、复制模板或重新保存内容相同的 B1 输入，不构成新模型请求。同版本返回原任务；其他版本或模板返回 `AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED`，`details` 提供原 `bid_id`、`job_id`、可用时的 `task_run_id` 及 `new_attempt_authorized=false`。明确改变实质上下文或指令后，仍须通过原手动预算准入。SQL 延迟守卫独立拒绝同语义第二个 job；测试绕过 Python 查找也不能提交重复运行。

未知费用保留原调用，不自动重发。收到明确取消后，原生操作按原状态机收敛；即使取消发生在模拟 HTTP 返回期间，也不能发布正文提案。在最后一次发送栅栏提交至外部 HTTP 接收之间仍存在外部 I/O 窗口，因此本批不声称取消必然免费。

模板暂停或改版阻止新受理，保留已接受请求的原指令和历史。来源撤回、事实/声明/规则变化、项目关闭、目标变化和自然到期分别在受理、发送与发布时再次校验。新的 parse 出现不替换选择的旧 parse；旧 parse 自身仍有效时可以继续原 exact 流程。

## 方法和模型证据的解释

计划保存 `package-authoring-generation-policy/1` 及实现源文件 SHA256；执行和发布比较实际方法指纹，不用新方法默默执行旧请求。历史读取使用原指纹，保持可读。原生模型调用账本另保存实际请求、profile、响应引用、usage 与费用状态。

验收使用真实 PostgreSQL 17、真实隔离 SeaweedFS S3 HTTP、真实 API 命令与原生 Worker。业务原件字节、解析/抽取结果与模型输出全部是显式合成机制夹具；模型 HTTP 使用 `httpx.MockTransport`，禁止实际 provider 网络，付费调用为 0。这些证据证明事务、权限、身份、取消和费用机制，不证明真实标书内容正确、抽取质量或模型编写效果。

导出的前端夹具来自实际 API 响应，包含输入、完整公共上下文、模板与版本、原受理运行 `accepted_run`、当前运行 `run`、原生 job/operation、已发布提案、私有草稿和通知。实际 OpenAPI 分别声明完整 exact candidate 和 `package_authoring_patch` 预览分支；原生验收对排队、候选就绪、发布后的实际 HTTP 响应执行 schema 验证。夹具不含认证 cookie、数据库口令、对象存储凭据或 provider key。

`private-draft-saved.json` 额外保留 `task_draft_flow.created/revised/saved/final`：创建解释的 revision 1、人工修改的 revision 2、保存模板的 ACK、最终 revision 3，以及前三次请求的 body、If-Match、真实响应 ETag 与同键重放响应。前端验收不需要重造早期解释摘要。

## 客户端请求恢复边界

只有收到本次 `POST /runs` 的有效、明确拒绝响应，才可以停止该请求的自动原键恢复。保守允许清单为下列 409/422 代码：`AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED`、`AUTHORING_PACKAGE_RERUN_NOT_SUPPORTED`、`TASK_TEMPLATE_PAUSED`、`AUTHORING_PACKAGE_TEMPLATE_CHANGED`、`AUTHORING_PACKAGE_INPUT_CHANGED`、`ORIGINAL_NOT_AVAILABLE`、`ORIGINAL_BYTES_CORRUPTED`、`ASSISTANT_INDEPENDENCE_UNPROVEN`、`ASSISTANT_ORIGINAL_REFERENCE_AMBIGUOUS`、`ASSISTANT_ORIGINAL_REFERENCE_REQUIRED`、`ASSISTANT_PRICE_UNAVAILABLE`、`ASSISTANT_SYNTHETIC_PRICE_FORBIDDEN`、`ASSISTANT_INPUT_TOO_LARGE`、`AUTHORING_PACKAGE_CONTEXT_TOO_LARGE`。这不是更换请求键重试的授权；仍须保留用户选择，并显示拒绝原因或原任务链接。

`*_BINDING_INVALID`、`*_INTEGRITY`、`IDEMPOTENCY_CONFLICT`、`COMMAND_INCOMPLETE`、未知代码、5xx、权限错误和超时不能据此清除待恢复请求。它们可能对应已经存在但暂时无法核验的原回执。不得将网络失败解释为“服务器未受理”。

## 复现

```bash
/path/to/python -m deploy.authoring_package_job_acceptance \
  --pg-bin /absolute/path/to/pg17/bin \
  --weed /absolute/path/to/weed \
  --receipt /tmp/new-authoring-package-job-receipt.json \
  --fixture-dir /tmp/new-authoring-package-api-fixtures
```

每次使用新的临时 PG 和 S3 目录、随机 loopback 端口及合成账号。脚本核对 PG17、按顺序加载实际 SQL、运行原生测试、记录源码与 SQL 指纹及执行期间是否变化。成功或失败都会关闭自己创建的服务。不得把旧业务库、旧运行目录或真实云凭据传入此入口。

## 后续阶段

B3 将在已发布 action 的真实绑定之上追加章节修订、来源资格、快照和消费记录；既有普通编辑、恢复或结构变更不能剥离资格后回退旧解析。B4 再按每个真实章节修订的资格进行构建、文件发布与明确包采用。B2 的只读候选不是这两项工作的完成证明。
