# 精确工作上下文 A：后端独立验收

日期：2026-10-21。范围：已批准的只读关联设计 A，精确整包核查／实交解析、范围摘要、生成采用／成员关系目录。源代码已冻结；主应用路由、实际契约生成与前端由根代理接线。本文件不代表四阶段选择器、项目批量摘要或 F05-05 六级主要业务动作已完成。

## 1. 已实现入口与语义

| GET 入口（均为 `/api/v1/bids/{bid_id}/work-contexts` 下） | 返回                      | 固定依据                                                                                       |
| --------------------------------------------------------- | ------------------------- | ---------------------------------------------------------------------------------------------- |
| `/package_review_run/{run_id}`                            | `PackageWorkContext`      | 明确的 run、包修订、清单、冻结输入、执行输入、依赖计划、输入／方法／结果摘要；不读取“最新核查” |
| `/package_submission/{submission_id}`                     | `PackageWorkContext`      | 明确实交的不可变 package binding；只还原其明确绑定的包／清单／可选核查                         |
| `/build/{build_id}/relations?target=package_revision`     | `WorkContextRelationPage` | 明确构建、实际输出 UUID、原生采用命令回执及两条审计／包成员；采用与仅包含为不同关系            |

前两个入口接受可选 `expected_selection_digest`。不符返回 412，不改选对象。关联目录支持 `limit=1..50` 和签名游标；游标固定种子／筛选／完整观察。观察改变返回 409，错误种子或篡改返回 422。重复或未知参数拒绝，`target` 必填且只允许 `package_revision`。

所有业务读取在同一 `REPEATABLE READ READ ONLY` 事务内完成。GET 只允许既有非 owner API 登录角色；Worker、owner、管理角色或继承业务表所有权的角色拒绝。返回 `Cache-Control: private, no-store` 与 `Vary: Cookie`。没有新命令、任务、业务头、资格变更或 source 写入；不调用模型、转换或原件下载。

### 核查与实交摘要

完整矩阵逐项对照冻结要求、规则定义和检查范围，独立重建结果封套，拒绝即使重算摘要后的错误计数、覆盖、重复／缺失行、定义、文档和限制字段。机器五类计数与当前人工四类意见分别返回；人工确认不替换机器结论，不表示已消除风险。

当前观察分别比较身份、包头、权威包头、清单头、规则头、来源、所选事实、方法、实交头及绑定运行状态。系统没有原生整包当前核查头，因此该维度明确 `not_applicable`，不能用创建时间代填。

`overall_coverage=partial`、`inventory_complete=false`、`quality_status=not_measured`。整包阻断风险数、整包通过结论、正式数值预测均保持 `null`。未明确技术评分 scope 时只陈述“范围未选择”。官方结果表完全不参与本摘要；源测试在存在官方技术总分 0 的情况下撤销相关表 SELECT，实交摘要仍成功且不泄漏官方记录或口径。

实交绑定时未有结果，之后的观察只更新“绑定运行状态变化”，不把后来的报告添加到实交摘要。本次原生反例证实：登记实交推进 lifecycle/revision 后，旧排队任务由既有 Worker 以 `PACKAGE_REVIEW_INPUT_CHANGED` 拒绝，模型未调用；另有原生已完成旧运行绑定测试，证明其他新运行不会替换它。假设历史运行后来存在完成报告的回填防线由纯投影反例单独验证，不宣称原生旧任务在登记后仍成功完成。

### 生成关系与范围完整性

`adopted_into` 必须同时满足原命令身份／请求摘要、封闭 201 ACK、确切输出及发布凭据、原采用／资格审计、冻结包和追加成员；回执中的请求理由仅在内部核验，不输出原请求、幂等键或对象存储路径。`adoption_command_id` 是审计 UUID。

`contains_output` 仅说明包修订含同一 `document_version_id`。同文件名、同字节摘要或同快照的另一构建不建立此关系。来源撤回保留历史采用事实并标明当前来源变化。任何一页均基于完整有界观察，最多各读取 1000 条采用命令／成员关系；超过预算返回 413，不把截断目录称为空或完整。关联存在不代表当前准入、原字节重核或整包资格。

## 2. 实际数据库权限依赖

本批没有新增 SQL，也没有在产品路径以 owner 修复权限。现有全新 bootstrap 的 `tender_api` SELECT／只读函数权限足够；隔离库通过实际非 owner 登录验证。部署可执行：

```sh
python -m deploy.work_context_readiness
```

此命令使用正常已配置的 API DSN，同一 RR 只读事务检查三个读取路径；只输出权限布尔值和依赖名称，不输出 DSN、口令或业务内容。缺表／缺读权限拒绝服务，不回退更高权限账号。完整机器可读依赖见同目录 `package-work-context-checks.json`，源定义见 `packages/work_contexts/permissions.py`。

| 分组     | 真实表／视图依赖                                                                                                                                                                                                                                                                                                                                                                                |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 共用     | bids、bid_profiles、bidders、bid_rounds、engineering_projects、engineering_lots、audit_entries；bid_packages、bid_package_revisions、bid_package_heads、bid_package_members、bid_package_parts；retrieval.source_nodes／source_heads／source_ancestors                                                                                                                                          |
| 核查     | bid_package_review_runs／results、operations、step_receipts、effect_receipts；review_inputs、execution_inputs、dependency_plans、受限 dependency_plan_command_receipts 视图；requirement_inventories／heads／extraction_runs、coverage_attempts／results；fact_scopes、review_decisions／decision_heads；fact_heads／sets／items、decisions／decision_heads、evidence_blocks、parse_runs、pages |
| 实交附加 | submission_records、submission_heads、bid_package_submission_bindings                                                                                                                                                                                                                                                                                                                           |
| 构建关系 | builds、build_inputs、draft_snapshots、draft_snapshot_sections、section_revisions、operations、build_outputs；document_versions、document_files、document_file_versions、blobs、document_relations、commands、retrieval.lineage_edges                                                                                                                                                           |
| 函数     | `design.identity_snapshot_v2(uuid)`、`design.bid_requirement_source_snapshot(uuid,uuid)` 的 EXECUTE；使用这些现有只读函数，不授写权限                                                                                                                                                                                                                                                           |

## 3. 固定候选与实际结果

基底提交 `ebe7e80b05cec1699eb0ce449cbda1406f4dc5d2`，只覆盖本批 14 个新源码／测试文件，未混入并行 UI、历史研究或 authoring 代码。候选：`/tmp/tender-review-work-context/candidate/workbench`。完整候选 manifest SHA256：

`b2e414355eccdb2696cd00d994e85c2ae687c5d26e6c13d42df73d7bac28d4fc`

| 验证                                                       | 结果                                                                                                                                                          |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ruff check／format --check（14 文件）                      | 通过                                                                                                                                                          |
| mypy（11 个产品源文件）                                    | 通过，无类型问题                                                                                                                                              |
| bandit（产品模块／路由／契约／只读部署验证）               | 通过                                                                                                                                                          |
| 纯规则反例                                                 | 28 通过                                                                                                                                                       |
| 原生 PostgreSQL 17.11、非 owner API／Worker、真实认证 HTTP | 21 通过；合计 49 通过，1 条既有 Starlette/AnyIO 弃用警告                                                                                                      |
| 本地回环 TCP HTTP                                          | Uvicorn 实际监听随机端口；无 session 401，真实 session 200，精确选定 run 与 no-store 响应；结束停止服务                                                       |
| 业务只读性                                                 | 实际 RR／READ ONLY；尝试 UPDATE 被 PostgreSQL 拒绝；主要业务／命令／操作／模型调用／审计／来源／实交计数不变；读取路径禁止 storage 与模型入口                 |
| 角色／认证／完整性反例                                     | 未登录、撤销 session、跨项目／不存在、owner、Worker、缺 SELECT、重复／未知参数、POST、错误固定摘要、重封假结果／错采用证明／缺 ACK／重复审计全部拒绝          |
| 历史与关系反例                                             | 明确旧核查、人工意见独立、包头／方法变化；同一 RR 内外来源变化；无 run／单正文误入；多构建、多采用、仅包含、同字节同名不同 UUID；空目录、容量、旧游标全部验证 |

首轮为 40 通过、3 个测试夹具／断言问题：owner 的安全 DSN 字符串不含口令；公共观察 `reason` 代码被隐私断言误拦；实交登记后的原生旧任务会因上下文变化失败。已按真实行为修正并补反例，第二轮全量 49 通过。没有为通过测试放宽原生发布或权限防线。

最终收据：`/tmp/tender-review-work-context/work-context-pg-1thy3z3h-receipt.json`；日志同前缀 `-pytest.log`。SQL 与源码全部来自固定候选；只创建新的临时 PG17 集群、随机回环端口和全新运行账号，测试结束停库，未连接旧库。原件、模型响应为明确合成测试夹具，外部付费调用 0；这些是软件机制证据，不是真实标书质量、模型效果或正式评分验收。

可复现命令（隔离候选已经包含所需本批文件）：

```sh
python -m pytest -q tests/test_work_contexts.py tests/test_work_contexts_pg.py
```

PG 用例仅在显式设置 `FUSION_REQUIREMENTS_ADMIN_DSN` 指向一次性新集群时运行；本次独立 runner 及其固定候选核验位于 `/tmp/tender-review-work-context/run_pg.py`、`candidate-manifest.json`。不能把未配置 PG 时的 skip 算作通过。

## 4. 根接线与冻结边界

1. 主应用 include `apps.api.work_context_routes.router`；router 已含 `/api/v1` 完整路径，不重复加前缀。
2. 现有 OpenAPI 扩展流程调用 `packages.contracts.work_context_api.extend_openapi(document)`，仅为实际已挂载的三个 GET 添加封闭 schema、安全要求与响应。按既有生成器产生实际契约／TS 类型。
3. 摘要选择需要完整验证返回的 bid／selection／selection_digest；当前性与固定历史身份分开。导航仍经过原工作面 guard；DTO 不是写请求 CAS 或资格许可。

14 个冻结源码清单与摘要保存在 `package-work-context-checks.json`。本批没有修改主 router、composition、schema plan、导出生成器、既有域文件或前端。后续集成全应用回归由根执行；本收据不替代该回归。

## 5. 后续最小软件扩展

需要新增三个独立 GET，保留本批三个入口不变：

| 新入口计划                                    | 原生依赖与返回边界                                                                                                                                                                     |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/work-contexts/choices?kind=draft_snapshot   | build                                                                                                                                                                                  | package_review_run | package_submission&limit=&cursor=` | 显式 kind，native draft_snapshots／drafts、builds／inputs／operations、review_runs、package submission bindings；返回人可辨的实际标题／修订／时间／状态和确切解析目标，不默认选首项；同一 RR RO、观察游标 |
| `/work-contexts/draft_snapshot/{snapshot_id}` | draft_snapshots／draft_snapshot_sections／section_revisions、drafts、source metadata；核验 manifest／章节／snapshot digest，历史正文与当前可编辑草稿明确区分，不能读取当前章节冒充旧稿 |
| `/work-contexts/build/{build_id}`             | builds／inputs／operations、所选 draft_snapshot、build_outputs／document_versions／blobs及发布／转换证明；每个格式真实状态与独立文件，无成功文件则 `null`，不补另一构建的 PDF          |

扩展应采用新增模块／契约／路由文件，避免改动本批已冻结 DTO。这些目录与精确解析是使四阶段选择无需手填 UUID 的软件工作，可以继续实施。现有 A 的 `navigation_only` 不是 F05-05 六级业务动作政策；项目批量摘要、四阶段前端与完整深链守卫仍需后续集成，不能因本批通过而宣称全 F12 完成。
