# 助手独立新问题与聚合预算交接：2026-10-17

本功能处于 **WIP，禁止部署或执行当前 SQL**。用户要求立即整理并提交 GitHub，Owner 已停止开发、新测试、DDL、服务启动和运行切换。此文与 `assistant-budget-source-state.json` 记录停工时实物；不是冻结候选或通过声明。GitHub提交由PM统一执行。

## 需求与边界

需求源：文档仓库 `04-验证与测试/a1-delivery-plan/current-implementation-review/助手未知费用下独立新问题协议.md`，含10项验收。主PRD保持 `16f776ef3115f9bace2ff7cf63bfff6652770199c4432e72965bb1369a693297`。本片是全新系统能力，不设计历史系统迁移或旧模型资格承接。

目标是在上一问题费用未知时，由服务端证明另一问题确属不同真实业务对象/用途，并在成员、项目、全局聚合金额上限内显式受理。新nonce、会话、文字改写、上下文修订、来源、token或profile均不能解除原unknown。retry/continue必须关联原intent；同对象同用途的改写保守拒绝，不调用付费分类器。复制工程壳/UUID/标题不能证明独立；正式评分三次完整判断与普通助手问答继续分离。

价格方案使用官方可信完整输入硬上界、本次输出上限、冻结计价版本/币种计算整数向上取整的最坏预留；**这是预算预留估价，不是供应商账单硬封顶**。缺可信上下限、价格或限额则暂停。显式Mock专用synthetic价格不可成为真实模型费用授权。原无可信上限的未知账不得按当前低价回填或清除。旧未知预留跨窗口继续占额度，迟到usage要记账但不得发布旧执行结果。

## 精确SQL与03状态

| 实物 | SHA256 | 状态 |
| --- | --- | --- |
| 文档仓库 `04-验证与测试/assistant-budget-development-checks/sql-protocol01/intent-budget.sql` | `29a78914ef825bb519b2ea4a072559d2fc30bb243015bfc6ec267f058a2271a1` | 保留原件，非可执行批准 |
| 同目录 `sql-protocol02/intent-budget.sql` | `ea53f1fe28afefea9fc81c0ad0b71f6c3ef8c9e804994521d71f2aef64b34403` | 架构静审发现阻塞，未执行 |
| 源码 `packages/assistant/sql/intent-budget.sql` | `ea53f1fe28afefea9fc81c0ad0b71f6c3ef8c9e804994521d71f2aef64b34403` | 停工只读核对，与02逐字相同 |
| SQL03 | 不存在 | 只有修复设计，**未写入源码、未冻结、未审、未执行** |

01/02各自的 `candidate.json` 保留在原目录，不修改失败证据。源码现有API/Worker已引用新SQL能力，但SQL尚不能使用，不能运行新功能来绕过阻塞。

02新增五表：`assistant_price_versions`、`assistant_budget_versions`、`assistant_logical_intents`、`assistant_budget_reservations`、`assistant_budget_events`。采用不可变价格/限额版本与事件，held/sent/unknown持续占用，sticky `requires_manual_reconciliation` 保留迟到核账冲突。RPC覆盖预留、dispatch、结算、迟到usage记录、可信人工核清；仅设计了NOLOGIN预算管理组，没有创建LOGIN或新库。

## 阻塞与未落实的03最小修复

1. **NULL核清漏洞（架构独立反例，阻塞）**：`assistant_reconcile_budget` 未显式拒绝NULL decision/amount/proof_reference/proof_sha。SQL三值逻辑可使IF条件为unknown并跳过，在原执行已终态时将unknown洗成settled/0、清manual flag。03必须逐项 `IS NULL` 拒绝，使用NULL安全组合校验；覆盖所有输入NULL、决策/金额/证明组合、sticky冲突、重复核清、终态限定。不能仅靠Python CLI校验。
2. **项目资格来源不完整（架构独立反例，阻塞）**：Python `project_identity` 已调用原生 `identity.snapshot` / `knowledge.bridge.confirmed_fact`，但SQL `assistant_check_target` 只核当前fact/decision头、值和evidence IDs，未复核不可变确认basis、fact identity、证据来源闭包与实时资格。仅撤回一条source_head且不改五事实头，现SQL读集不变。不能声称SQL已证明“当前有据”。五编号为issuer/project/lot/round/bidder的既有typed fact；不得另建自由填写业务身份注册表。
3. **dispatch原生模型/输出绑定缺口（架构静态反模型，阻塞）**：RPC未读取并比较native `profile_digest`、全局run max_tokens/项目call reservation max_tokens、manifest输出上限、冻结provider/model/price；可能按短输出/低价模型预留却放行较大或不同模型。Python已有先验不足以代替RPC边界。03须核完整冻结profile摘要与native ledger、输出上限、原用途/handler/attempt等真实关系。
4. **锁序尚未解决（阻塞）**：当前预算RPC先锁全局90129，再查业务。不能直接在其内部追加bid/graph锁，现API与engine已有bid/op/graph顺序，可能形成反序。拟在同一短事务中先从不可变job推导真实关联bid并按既有顺序锁定，再核完整live basis/source，最后取预算锁，dispatch提交前保持资格不被撤回。全局任务的跨项目来源亦须覆盖。确切helper与锁序需架构审查后落代码，不能假定已完成。
5. **native写账与预算锁潜在反序（开发分析，未独立证实/修复）**：observe RPC取预算锁后更新native usage；`global_runtime`/`paid_execution`部分分支在native UPDATE后同事务settle预算。拟将native写入提交后在独立事务settle，或去掉observe已结算后的冗余settle，需用真实并发PG证明无死锁。当前未改。

资格桥接的拟议实现是冻结原生确认basis/fact identity/current source closure，验证不可变audit与原生carryover依据，按原有 `fact_sets.evidence_basis`、`authoring.repository.assert_sources`、`retrieval`祖先闭包规则核当前parse/角色/来源head/时效；闭包哈希必须与现有Python规范JSON一致。现证明中尚未保存这些完整字段，SQL canonical JSON/hash helper也未实现。不能拿这些拟议措施当已修复。

## 已保存的API/Worker源码（均WIP）

| 文件 | 当前工作内容 |
| --- | --- |
| `packages/assistant/intent_identity.py` | NFKC/换行/空白完整问题规范化；完整文本anti-key和对象+用途coarse-key；既有五typed事实值推导canonical身份；真实project/finding/rule/section解析、复制壳保守判定；发布前revalidate |
| `packages/assistant/budget.py` | RPC包装与错误映射；原job/Action关联优先；准备/绑定intent；未知账下显式new_question控制；冻结profile/价格；输出预算投影；native预留/dispatch/usage/terminal钩子 |
| `packages/assistant/budget_math.py` | 1e9 scale整数金额、per-million向上取整、官方全输入上界与maxout最坏估价 |
| `packages/assistant/paid_execution.py` | 助手专用项目驱动，复用真实model_calls原生账/执行锁；dispatch前预算门；usage先记账再存原始响应；旧结果不自动补发 |
| `packages/assistant/budget_admin.py` | 单独600私有profile、专用非owner管理LOGIN的封闭price/limit/reconcile CLI；只接受已保存文档SHA，不自动访问价格网页 |
| `packages/assistant/intent_capabilities.py` | 只读配置/可用额度/原未知问题/真实target选项投影；全局会话按成员私有，项目按成员可见；缺配置暂停 |
| `packages/assistant/budget_contracts.py` | 严格intent/预算/capabilities/target实际schema；扩展JobView预算字段；尚未冻结完整组合actual |
| `packages/assistant/jobs.py` | answer/generation受理连接prepare+真实job+bind同事务；原job重放；intent与budget投影 |
| `packages/assistant/protocol.py` | request_mode、related_job/action、真实target、封闭intent_purpose输入字段 |
| `packages/assistant/global_runtime.py` | 全局原生reserve/dispatch/usage/settle预算门；有上述锁序待修 |
| `packages/assistant/tasks.py` | 项目问答接助手专用paid_execution，继续原handler用途链 |
| `packages/assistant/generation.py` | prompt加入显式只读目标，不修改正式评分 |
| `packages/assistant/coordinator.py` | 发布前target复核；终态预算tick |
| `packages/assistant/actual.py` | extend_openapi末尾叠加budget_contracts，未产新冻结actual |
| `apps/api/assistant_routes.py` | POST answer/generation显式new_question标记；新增 `GET /assistant/intent-capabilities` 与 `/assistant/intent-targets` |

尚需细查：capabilities目前只按available>0推可用而非完整最坏金额报价；无fact head时错误映射；目标清单分页/完整覆盖；action真实effect绑定；schema必填/nullable与组合actual；unknown/私有权限UI契约；legacy无价账整体暂停范围。以上均不宣称测试通过。

本Owner未修改共享engine、domain/model_calls或authoring；未改主main组合、frontend12、部署helper。`deploy/bootstrap_fresh.py` / `tests/test_bootstrap_fresh.py` 归PM；其提交状态必须读主交接，不能由本片替代。

## 验证的准确状态

- 停工前运行过：`ruff check packages/assistant apps/api/assistant_routes.py` 通过；mypy同范围 `--follow-imports=skip` 通过（22文件）；既有 `tests/test_assistant.py` **11项通过**。仅有本会话命令结果，不存在本片新冻结的独立质量证据包；此次整理没有重跑。
- `ruff format` 曾格式化助手源；**未把格式化当功能验收**。本片最后也未冻结format/bandit/全量组合检查。
- 拟新增 `tests/test_assistant_intent_budget.py` 的apply_patch因patch格式失败，文件**未创建**，测试**未执行**。计划中的硬Mock用例不能写作“已过”。
- **新预算hardMock执行0；新SQL真实PG执行0；新增RPC/角色/并发/reconcile/NULL/live撤回测试0；新功能实际ASGI/浏览器0；真实模型0。** 未导出、冻结或独立验证新的完整OpenAPI；旧11项pure不证明新聚合预算正确。
- 先前冻结助手11/夹具05的显式Mock浏览器、刷新、Action、取消/unknown证据属于旧能力，不能代替新预算协议。此前 `tests/test_assistant_integration.py` 仅是新测试参考，不代表本片执行通过。

硬Mock后续应覆盖完整规范化/否定数字守恒、大文本、copy壳、同对象改写拒绝、新nonce/context/profile不解锁、retry/continue原intent、全局私有、原Action只消费一次、dispatch提交后唯一Mock调用、gate拒绝0调用、存储失败仍保留usage、取消/撤回/租约后的迟到usage只记账、Mock价格拒绝非MockTransport。

真实fresh PG另需验证NULL矩阵、价格/配置缺失暂停、三范围并发限额、跨窗口unknown保留、未知旧账、native profile/maxout篡改、source撤回窗口、锁竞争、迟到账与可信核清冲突sticky、各受限角色越权。这些不能用假连接/纯函数测试替代。

## 资源、helper依赖与私有状态

**预算fresh库、预算admin LOGIN、真实/合成价格配置均未创建/执行。** 无用户真实费用额度被配置，无旧库补DDL/回填。SQL只创建拟议NOLOGIN组；新LOGIN由PM审核后fresh helper创建。业务API/Worker每进程仅自己的单DSN；admin profile独立单DSN600，业务env必须拒绝其DSN；不得让owner连接进入业务或driver混多个角色DSN。

PM helper04冻结SHA `bc414d201b48c7a7ada62478c53c7d975c840ce4aee217b247b08f9ecd78e869`：47纯检查及质量曾过，但架构独立发现NOLOGIN预算组可继承API组越权，**04不可执行**。helper05（组上游闭包/LOGIN精确membership/effective业务禁止）**尚未写入**。必须先03SQL与helper05分别静审，再由PM批准fresh资源窗口，绝不能对已验库补角色。

旧运行API8816/control hold及其11固定根完全保持；此次新源码未部署到该实例，禁止用新源码启动或清其unknown账。旧夹具参考位置：`qa/assistant_browser_fixture/`；设施固定根在文档仓库 `04-验证与测试/assistant-browser-environment01/facility-candidate02/runtime`，candidate SHA `c3e9fb43c4b82513e20e5826d3a0105a598a281bccedeb684d4950602bd118e7`。运行最终绑定以PM `RUNTIME_AND_PRIVATE_STATE.md` 为准。

私有路径仅作定位：`.local/assistant_ui01-runtime.env`、`.local/assistant_ui01-test-members.json`、`.local/assistant_ui01-fixture05.json`。不读取/打印/上传内容，不复制成员身份到新预算测试。尚无可供本片执行的预算专用新库profile；不要猜配置路径。运行DB、对象、私有配置不随GitHub源码自动恢复。

费用授权**不包含模型**。此前真实付费评审/常驻消费者被自动审查拒绝，缺明确范围/次数/预算；不能以synthetic限额、新协议或admin配置绕过。用户新授权仅固定7个合成OSS对象的一次限次恢复，详情归testing/PM交接，不授权本Owner调用云或模型。本片没有新HTTP/provider/OSS/Kafka消费，不能启动真实消费者或收费替代runner。

## 接手顺序与复现命令

先读产品协议、架构交接与此文，核源清单；修03全部阻塞并保留01/02，完成hardMock测试；与架构确认业务锁序/真实来源资格/native边界，再冻03；等PM helper05审查通过，申请fresh专有角色资源，运行真实PG/API/并发。随后集成Owner显式叠加新main实际组合，前端Owner对新契约负责，独立QA/架构/产品/用户评审后才交付。

以下是接手后可用的只读核对/纯检查命令，**此次整理未重新执行测试**：

```bash
cd /workspace/tender-workbench
sha256sum packages/assistant/sql/intent-budget.sql
sha256sum /workspace/tender-docs/04-验证与测试/assistant-budget-development-checks/sql-protocol01/intent-budget.sql
sha256sum /workspace/tender-docs/04-验证与测试/assistant-budget-development-checks/sql-protocol02/intent-budget.sql
.venv/bin/ruff check packages/assistant apps/api/assistant_routes.py
.venv/bin/mypy packages/assistant apps/api/assistant_routes.py --follow-imports=skip
.venv/bin/python -m pytest -q tests/test_assistant.py
```

预算新测试文件不存在，故没有可诚实提供的已验证budget pytest/PG命令；接手人需先补测试与合成夹具，再新增明确fresh profile的按角色launcher，不得拿旧8816 profile运行。SQL03/helper05未放行前，不运行bootstrap、psql、budget_admin或任何provider任务。任何新结果写新文件，失败和旧候选不得覆盖。

所有自有源码/WIP已保留；本Owner当前静止，仅交PM完成无损GitHub归档。本文件不声称已push或功能可交付。
