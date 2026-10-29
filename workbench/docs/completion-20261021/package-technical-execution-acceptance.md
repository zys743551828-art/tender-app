# F06 专用整包执行、正式拒绝与恢复边界

日期：2026-10-21。本记录是范围／量尺检查点之后的独立增量，不修改此前已冻结的 scope、scoring-context 或 sample-context 协议。提交 SHA 和整站发布由总集成人员另记。它不宣告 F06、真实模型质量或严格历史样本验收完成。

## 实际完成的路径

专用整包输入已经接到实际 PostgreSQL owned-job、预算预留、费用结算、lease／fence、调用去重和独立 Worker。机制验收使用独立临时数据库、专用非 owner LOGIN、明确合成资料与 HTTP MockTransport；没有真实供应商请求或付费。两条适用评分规则在独立 Worker 子进程中分别完成三次同输入判断，共六次模拟 HTTP 调用，生成独立的机制结果。

普通产品 API 另行读取正式执行条件。无论数据库是否安装该基础、隔离数据库是否登记过机制权威，正式申请都会在创建任务或预留费用前返回具体缺口。页面只在用户显式操作后读取条件；另一按钮以零预算核对这一拒绝，只有确切范围、方法、条件列表和零任务／零模型请求都通过校验后才显示拒绝回执。页面不提供机制测试授权开关。

| 环节 | 实现及经过的实际验证 |
| --- | --- |
| 新主体 | `score_execution.inputs.package_scope_id` 精确指向原冻结范围；不伪造单正文、review 或历史 input |
| 输入 | SQL 从原包、权威包、规则、全部分册／物理页／证据块／表格结构／来源祖先投影；保留未选分册和排除条款 |
| 请求一致性 | 每条款三次调用使用同一个 packet 和逻辑请求摘要；序号仅在账本中区分，不进入提示词；SQL 独立重建 system、完整 packet、输出 schema 与参数的摘要 |
| 独立有效判断 | 每条款恰好三个不同调用、replicate 1–3，完整覆盖声明的必要分册；逐字引文绑定文档、parse、物理页与 block，至少支持每个必要分册 |
| 原响应 | provider、模型别名、方法摘要、输入摘要、原始 content、结构化 JSON、usage、response ID 和 finish reason 一起绑定；响应内容须与结构化结果一致 |
| 预算及费用 | 使用已有真实账本，以明确冻结价格快照计算保守上界；预算不足时不建 job；先按实际 usage 结算，再判输出是否有效 |
| 受限 Worker | 独立 `-I` 子进程，只接受一个用途 DSN；拒绝 API、普通 Worker、旧评分角色、原表读取及继承的其他环境变量 |
| 当前来源 | 领取、读取、预留和发布复核完整身份、当前包头、清单、原冻结 parse、来源祖先及生效状态；实交或身份变化使当前输入不可用 |
| 结果隔离 | 结果只进入 `package_score_execution.results`；数值预测为 null，formal／training／metrics 固定 false，不进入旧评分结果、shadow 或 samples |
| 正式拒绝 | BASE-only 与安装扩展的实际认证 HTTP 都返回具体缺口；extra `mechanism_test`／`formal_scoring_eligible` 请求字段被 422 拒绝，旧 ETag 为 412，缺条件为 428 |

本轮证明的是“冻结文本／表格结构等证据投影没有被替换或截断”。它没有证明原文件图像已经被模型完整阅读、所有必要范围已被穷尽，或三次真实模型判断具有统计独立性。上述能力在正式协议中保持未具备。

## API、页面与主装配

共同基址：`/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}`。

| 操作 | 实际行为 |
| --- | --- |
| `GET /execution-context?scale_id=...` | 返回 `PackageTechnicalExecutionContext`：嵌套既有 current scoring-context、专用方法身份、软件基础安装状态及明确正式缺口；携带 strong ETag 和 no-store |
| `POST /executions` | 闭合 `CreatePackageTechnicalExecution`，auth／CSRF／If-Match 必需；当前版本固定 409 `PACKAGE_TECHNICAL_EXECUTION_BLOCKED`，详情包括原范围／方法／完整缺口、`jobs_created=0`、`model_requests=0` |

ETag 包含完整条件内容，仅排除 nested `observed_at` 观察时钟。POST 重新读取条件再比较，不把上一次检查当成永久权限。请求的 `purpose` 固定 current_prebid；`scope_digest`、专用方法摘要、显式 `scale_id`、预算和理由都严格校验。API 没有合成端口参数、判断结果上传入口或资格勾选。

根集成挂载：

- `apps.api.package_technical_execution.router`。
- `packages.contracts.package_technical_execution_api.extend_openapi`，只为实际存在的路由增加 schema，不生成未实现成功响应。
- 前端独立 `PackageTechnicalExecution({ saved }: { saved: PackageTechnicalScopeView })`；挂在选中的已保存 scope 之下。它使用独立 `packageTechnicalExecutionProtocol.ts`，不修改共享 `contracts.ts` 和已有资格组件。
- 页面量尺必须显式选择，目录本身不授权满分；当前没有可用量尺时仍可核对其他缺口。正式申请核对固定 `budget="0"`，不会声明任何支出授权。

页面严格校验闭合字段、原 scope／basis／coverage、固定方法 digest、所有正式 flags、量尺选择、每个缺口摘要和外层 ETag。请求切换 scope、刷新或量尺选择后旧显示清除；晚到响应不能污染新 scope。网络错误、412、格式错误、非零调用数或未支持的成功响应都不会变成零调用回执。

## SQL 顺序与权限隔离

本扩展只用于新的独立数据库；不得安装到已有业务库、不得对原数据修补回填。它不进入 BASE，不提供默认生产 Worker 账号，也不创建 owner 机制授权。

顺序为完整 BASE（已含 `bid-package-technical-scopes.sql`），随后：

1. `deploy/sql/model-governance.sql`
2. `deploy/sql/historical-backtest.sql`
3. `deploy/sql/historical-input-qualification.sql`
4. `deploy/sql/model-governance-release.sql`
5. `deploy/sql/score-execution.sql`
6. `deploy/sql/package-score-execution.sql`

满分权威是另一条可选能力，仍按此前记录安装 `technical-scale-authority.sql` 后接 `technical-scale-package-identity.sql`；未安装不会导致本 API 500 或自动猜测满分。

新 NOLOGIN 组为 `tender_package_score_test_api` 和 `tender_package_score_test_worker`。SQL 限制机制数据库名为 `fusion_package_score_mechanism_<8位小写字母数字>`，数据库 OID／名称必须先由 owner 登记；scope 必须由 owner 将确切 scope digest、scope method digest 和专用方法 digest 一起登记，合成权威最长八小时。API、普通 Worker 和用途 Worker 都没有写入登记表的权限。固定数据库名加 owner 登记共同限制该机制，HTTP 参数不具有这项能力。

用途 Worker 没有原业务表、官方标签、来源表、整包原范围、原账本或旧评分 RPC 的读取权限，只能读自己 lease 的 bounded owned projection。旧 ledger 的预算、generation、租约和结算函数复用；仅 `current_input`／`input_packages` 通过独立主体分派，旧单正文 invariants 保留。新输入的模型方法独立，不借旧方法摘要。

本版本 SQL 会创建专用角色，因此验收要求新临时集群；角色已存在会拒绝重复安装，不能静默复用权限未知的角色。测试 fixture 随后才创建独立 API／Worker LOGIN，owner 只初始化和构造合成权威。

## Worker 使用与已完成的恢复

入口为 `deploy/package_scoring_worker.py`，使用 `--profile`、`--job-id`、`--generation`。profile 须为权限 0600 的普通文件，只允许一个 `PACKAGE_SCORE_DATABASE_DSN`，不能包含 API、存储桶、真实模型 key 或其他变量。无明确 fixture 时返回 `PACKAGE_SCORE_PROVIDER_UNQUALIFIED`，在 claim 前停止。

显式验收参数 `--mechanism-response-fixture` 提供 `package-score-http-fixture/1`，必须标为 synthetic，每个响应绑定实际 provider HTTP 请求摘要。它使用现有 HTTP adapter 的真实序列化和响应解析，网络由 `httpx.MockTransport` 封闭替代；没有真实 HTTP fallback。测试价格为合成输入，不能当作供应商报价。

| 中断／恢复情形 | 当前行为 |
| --- | --- |
| 已成功结算的同一逻辑调用 | 读取既有响应；换 input/job/command nonce 也不重发，恢复 job 的新增费用为零 |
| 显式 pause／resume | generation 递增，旧 fence／owner 不再读输入或预留；新的 Worker 使用当前 lease |
| 带费用的无效判断 | 保留实际费用和原响应，不能计为有效判断；恢复时重读原响应并继续拒绝，不以无效输出伪造免费重试 |
| 发送／费用 unknown | 保留预算预留、暂停 job；自动恢复及新 nonce 都被阻止 |
| 明确 not_sent | 结算零费用并暂停；本版本仍要求独立恢复权威，不能通过新 nonce 自行重发 |
| HTTP 期间来源撤回或 lease 到期 | 允许原 call owner 如实结算已发生 usage；禁止发布不再有效的结果 |

本基础单独部署时不提供“未知发送状态可信对账后解除”的 RPC。同批追加的 [独立对账增量](package-technical-reconciliation-acceptance.md) 已验证在专用机制库中保留原始 unknown 状态、核对 provider receipt、有据结算及明确恢复；需独立安装、独立非 owner 对账角色，普通 API／Worker 无此权限。该增量不授予正式执行资格，也没有任意重试次数或未知发送自动重发开关。

## 验证结果

所有原生检查使用 PostgreSQL 17.11、独立非 owner API／Worker LOGIN、全新临时库；测试原件、规则、价格和响应完全合成。真实 provider 调用与付费均为零。

| 检查 | 结果 |
| --- | --- |
| `tests/test_package_scoring_pg.py` | 21 passed，94.04 秒；实际 Worker 子进程、六次模拟 HTTP 正向及权限／预算／租约／账本／伪结果反例 |
| `tests/test_package_technical_execution_pg.py` | BASE-only 1 passed，4.58 秒；真实认证 ASGI、实际数据库、零预算拒绝，输出配对 scope/context/request/refusal |
| `packageTechnicalExecutionProtocol.test.ts` | 18 passed；实际 HTTP fixture、安装基础状态、重算 ETag 仍不能提升资格、错范围／错量尺／伪零调用等 |
| `PackageTechnicalExecution.test.tsx` | 7 passed；显式 GET／POST、零预算、无自动发送、失败处理、晚到响应、重复点击、缺失接口 |
| Ruff + format | 9 个新增 Python 实现／测试文件通过 |
| mypy | 7 个新增源文件，`--follow-imports=silent` 通过 |
| Bandit | 7 个新增源文件通过；固定本地子进程 import 的限定说明保留 |
| ESLint | 4 个新前端文件通过 |

前端整树 typecheck／build、主应用 OpenAPI 生成和发布由根集成运行；本轮定向检查期间并发任务编辑仍有独立类型变更，不以单组件测试替代整站通过。PG 唯一第三方告警为 Starlette／AnyIO 的弃用提示。

新可复现 suite 需要显式 `FUSION_PACKAGE_SCORE_PG=1` 和独立临时 PG 的 `FUSION_REQUIREMENTS_ADMIN_DSN`。BASE API suite 需要 `FUSION_TECHNICAL_SCOPE_PG=1`。不得指向业务数据库。owner 连接仅存在于测试进程环境，未写入文档、回执或 Git。

实际 HTTP fixture：`apps/web/src/test-fixtures/technical-execution-http.json`，外部工作副本 `/tmp/tender-review-current/technical-execution-http.json`。原 PG 收据位于 `/tmp/tender-review-f06/scope-pg-w0gv4_xx/test-receipt.json` 与 `scope-pg-7e6n_4us/test-receipt.json`。可持久阅读的测试摘要和源文件指纹另列 `package-technical-execution-checks.json`。

## 尚缺的正式能力

正式范围与图文权威、真实可用供应商端口／模型身份、可执行官方聚合、正式方法验收及原字节再次核验都保持缺失。有据满分不能授权按条款求和或把三次判断平均为技术分。隔离机制结果没有训练、指标或样本资格。

严格整包历史样本仍需要原包及每个来源的存在／本方知晓／效力证据、研究冻结的历史截止／实交分割／标签可用截止／训练冻结时间，以及真实配对标签的用途隔离。本片不补造上述时间、不将当前原件冒充历史资料、不把官方成绩带入当前模型输入。可运行的软件机制与真实业务／模型验收分别记录。

## 检查点 11 集成补充

本批已挂载实际 API／页面并重生成共享能力契约；完整冻结候选的后端、前端、TypeScript 和构建均通过。上文及原始收据保留独立开发阶段的检查状态，最终接线和共享 BASE 验证以 [检查点 11](PROGRESS.md) 及 [汇总收据](task-retrospective-layout-regression-receipt.json) 为准。该补充不改变原生专项的材料性质或正式资格边界。
