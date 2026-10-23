# F10-05 整包复盘独立批次验收

日期：2026-10-21。依据批准的《标书工作台融合实施计划》F10-05，以及本目录的产品验收映射。此文件记录本批实际实现和已运行证据，不把合成测试写成真实投标效果。

## 交付状态

本批完成独立领域、数据库约束、认证 API、前端组件和自动化验证。明确选择整包实交、官方成绩、业务阶段结果和两条核查后，先预览所选依据，再保存不可变的待核复盘；用户另行确认才能创建企业知识候选。缺少结果或核查时，填写具体待补原因仍可保存复盘。

本批没有改主应用装配、共享 OpenAPI 导出、共享契约生成器、`BusinessResults.tsx` 或冻结报价模块。主入口挂载和全应用集成验收由主代理完成，不能用本文件的独立组件测试替代主入口浏览器验收。

## 用户流程和数据边界

1. 从实际提交目录明确选择一条整包实交，历史记录可选，系统不默认采用最新记录。
2. 明确选择该实交的官方成绩、独立业务阶段结果，以及基线侧和实交侧两条已完成核查。结果与核查可以分别声明资料待补；不能只选半个核查对，也不能用同一次运行充当两轮。
3. 核对原身份、包修订、实交绑定、原分数和满分、原核验状态、物理页引用、比较差异及缺口。官方零分保持 `"0"`；未知保持 `null`。技术总分、业务阶段和风险解决资格互不推导。
4. 分开填写成员观察、尚未确认的假设、后续核对整改和补充资料说明，再保存不可变待核记录。成员意见始终标为成员意见，系统不调用模型生成逐项扣分解释。
5. 历史详情同时显示原记录和当前来源变化。官方更正、人核处置、当前实交头或来源状态变化不会覆盖旧记录。
6. 用户填写原因并明确建立企业知识候选。候选初始为 `needs_applicability`，不自动送确认、发布、建样本或发布模型。需要在既有企业知识流程补齐适用主体、条件、期限与精确出处，再分别送确认和发布。

实交侧核查必须属于确切实交包修订；两侧核查还必须与实交的历史身份快照一致。核查的规则定义、原机器行、人工处置和执行方法独立保留。判断变化或成员确认不会被标为“风险已解决”。

未解析的实交凭证可保留在待核历史中。若原件或确切解析尚无完整有效来源图，建立知识候选会被阻断，并明确提示补来源。之后解析或补齐来源需要重新预览并建立新复盘，不能倒改原记录。

## 实现与防线

### 原生事实和不可变复盘

- `packages/retrospectives/observations.py` 在同一调用方快照中读取确切实交绑定、指定官方成绩及核验头、指定业务结果及核验审计、指定两次核查、人核头和完整来源祖先。
- `repository.py` 的两个写动作分别使用原请求摘要、幂等键和 `If-Match`。写入锁定项目后重新读取当前依据；预览失效返回 412。原 ACK 可以恢复，不能把重试替换为另一份选择。
- `package_retrospectives` 和 `package_retrospective_knowledge_links` 均追加不可修改。API 只获得新增表的 `SELECT/INSERT`；Worker 没有这些表的写权限。
- SQL 独立从实交、两次核查的目标包与权威包、官方资料和证据解析重建必需来源集合。声明来源子集、替换原件、重复来源祖先键、跨项目引用不能冻结成合法记录。
- `package_retrospective_comparison` 独立重建完整两轮比较：运行/执行/冻结/方法/覆盖摘要、人核头摘要、原行、定义变化、缺失侧、判定转移、计数、所有输入变化及方法字段变化。最终比较对象必须整体相等，重算外层哈希不能掩盖假摘要。
- 业务阶段复盘快照只保留原登记、核验与当前头事实，省去 `BusinessResultView` 的动态 `usable/unusable_reasons`。SQL 独立校验原审计字段和核验内容，避免把可伪造的动态摘要变成知识事实。

### 受控知识候选

知识候选关联一个 `post_outcome` 的不可变复盘来源标记，候选知识源为 `derived_mixed`。标记的“已发布”仅表示复盘记录存在，知识版本自身仍为候选，且没有自动建立检索索引。

授权修改的既有文件只有 `packages/knowledge/repository.py` 的两个最小调用点：

- 新版本继承原复盘来源、类别和固定摘要；即使新增出处全部为事前原件，也不能把复盘重新标为 `prebid_content` 或公司事实。
- 完整知识版本读取生命周期时重新核对复盘依据，来源变化返回 `source_invalid`。

SQL 额外约束后续知识版本和发布。缺失来源闭包、未发布、未来生效、过期、撤回、跨项目祖先或原记录头变化，都会阻断新的候选流转、版本和发布。历史记录和已经确认的原 ACK 仍可追溯。

### 前端恢复

`PackageRetrospectives.tsx` 是独立组件，按成员、项目和实交分别保存草稿与命令恢复记录。候选动作另按复盘身份隔离。异步预览与回执只应用于原作用域；重新选择其他实交不会接收旧结果。复盘及候选 ACK 都验证原请求、主体、幂等键、预条件、嵌套摘要和响应 ETag 后才清理恢复记录。

组件使用当前语义颜色变量，支持窄屏单列、原生标签/表单、按需展开身份和差异、分页目录与差异。当前目录没有可靠业务包标题时展示真实时间和修订编号，不生成虚构名称。

## 已运行验证

| 范围                       | 结果                     | 证明范围                                                                                                                                       |
| -------------------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 纯 Python/契约             | 13 通过                  | 明确选择、缺失原因、不同核查对、禁止自动资格请求、实际 OpenAPI 引用闭包                                                                        |
| 原生 PostgreSQL 17.11 全套 | 20 通过，101.51 秒       | 新库、独立非 owner API/Worker、真实认证 ASGI、实交/官方/业务结果/核查链、不可变记录、CAS、幂等重放、来源闭包、比较篡改、知识显式发布与撤回阻断 |
| 后续版本 SQL 绕过补充      | 2 通过，18 未选，9.54 秒 | 应用继承 hook 被测试替换后，API 角色直接写入仍不能降级为事前来源，也不能在来源撤回后插入新版本；原生发布仍被拦截                               |
| 前端协议                   | 10 通过                  | 使用原生 PG/ASGI 生成的合成 HTTP 回执核验摘要、零分、完整比较和两种命令 ACK；拒绝错身份/错原请求/错比较                                        |
| 前端组件                   | 4 通过                   | 显式两步保存和候选动作；坏 ACK 跨刷新/实交切换恢复同一请求；迟到预览隔离；412 保留文本并要求新预览                                             |
| Ruff / format              | 通过                     | 12 个相关 Python 文件；含授权 knowledge hook                                                                                                   |
| mypy                       | 通过                     | 8 个新增领域/契约/API 源文件                                                                                                                   |
| Bandit                     | 通过                     | 新增领域/契约/API                                                                                                                              |
| 前端 ESLint / Prettier     | 通过                     | 新增复盘源文件、测试和合成 fixture                                                                                                             |
| 复盘范围 TypeScript        | 通过                     | 继承应用 tsconfig 的独立 include，含组件、协议、测试及实际依赖                                                                                 |
| 复盘组件 Vite 库构建       | 通过                     | 39 模块；真实新增组件和所需引用打包到临时输出                                                                                                  |

原生全套中专门覆盖：计数、判定转移、方法变化、缺失侧、运行摘要、额外字段在重算比较摘要和外层摘要后仍被 SQL 拒绝；缺官方资料不会补零；零分不会产生逐项扣分；业务阶段使用独立记录；源撤回后新版本与发布失败；发布后的知识仍没有新增研究样本。

原件和模型 HTTP 均使用显式合成测试适配器。核查写入真实 Worker 引擎和原生表，消息从真实 outbox 读取后由测试调用处理。没有连接真实 Kafka、OCR、对象服务或付费模型，因此本批不声称验证了生产消息运输、真实识别质量或真实核查效果。

全应用 `npx tsc -b --pretty false` 已执行，当时仅剩并行 F11 的 `TaskPanel.test.tsx` / `useTaskTriggerPage.ts` 类型问题，复盘文件无错误。未改并行文件；全应用构建和主入口浏览器验收须在主代理集成后统一完成。

### 复现命令与回执

工作目录为 `workbench/`，前端命令在 `apps/web/`：

```bash
/tmp/tender-review-venv/bin/python -m pytest -q tests/test_package_retrospectives.py
/tmp/tender-review-venv/bin/python /tmp/tender-review-retrospective/run_pg.py --expected-sql-sha 1cf9ad92465191277c1a99860acdf98bf377966a288ecafcb40644dad7caae71
/tmp/tender-review-venv/bin/python /tmp/tender-review-retrospective/run_pg.py --expected-sql-sha 1cf9ad92465191277c1a99860acdf98bf377966a288ecafcb40644dad7caae71 --selection later_prebid
/tmp/tender-review-venv/bin/python -m mypy --follow-imports=silent packages/retrospectives packages/contracts/package_retrospectives_api.py apps/api/package_retrospective_routes.py
/tmp/tender-review-venv/bin/python -m bandit -q -r packages/retrospectives apps/api/package_retrospective_routes.py packages/contracts/package_retrospectives_api.py
npx vitest run src/PackageRetrospectives.test.tsx src/packageRetrospectiveProtocol.test.ts
npx tsc -p /tmp/tender-review-retrospective/tsconfig.json --pretty false
npx vite build --config /tmp/tender-review-retrospective/retrospective.vite.config.mjs
```

隔离 PG harness 每次生成随机端口和临时口令，不输出口令，不访问旧库，结束即停库并删除口令文件。

- 全套回执：`/tmp/tender-review-retrospective/retrospective-pg-kgvymma5-receipt.json`。
- SQL 绕过补充回执：`/tmp/tender-review-retrospective/retrospective-pg-n3lxfwtd-receipt.json`。
- 本目录持久验收摘要：[package-retrospective-checks.json](package-retrospective-checks.json)。
- 前端合成原生回执：`apps/web/src/test-fixtures/package-retrospective-http.json`。

SQL SHA-256：`1cf9ad92465191277c1a99860acdf98bf377966a288ecafcb40644dad7caae71`。

## 主代理接线清单

| 位置                        | 接线                                                                                                                                |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `apps/api/main.py`          | 挂载 `apps.api.package_retrospective_routes.router`                                                                                 |
| 实际 OpenAPI 导出           | 在 `get_openapi` 后调用 `packages.contracts.package_retrospectives_api.extend_openapi`；只导出已挂载 6 个操作                       |
| `deploy/schema_plan.py`     | 在 retrieval、整包提交、核查运行与人工处置 schema 之后安装 `packages/contracts/sql/package-retrospectives.sql`                      |
| 前端主入口                  | 在实际提交/经营结果语境挂载 `<PackageRetrospectives bidId={bidId} memberId={memberId} onKnowledgeCreated={打开指定企业知识候选} />` |
| `recordedCommandStorage.ts` | 成员清理注册表加入 `package-retrospective`、`package-retrospective-knowledge`                                                       |
| 共享前端能力契约            | 根据最终实际 OpenAPI 重生成共享 `contracts.ts` 的已实现操作能力表。复盘类型已由独立生成器输出，无需手写共享类型                     |

独立类型重生成：`python apps/web/scripts/generate-retrospective-contracts.py`，随后对 `apps/web/src/packageRetrospectiveContracts.ts` 执行 Prettier。该脚本复用现有生成器的 `--schemas`，没有改共享生成逻辑。

14 个顶层类型：`PackageRetrospectiveSelection`、`Notes`、`Request`、`KnowledgeRequest`、`Preview`、`View`、`Origin`、`KnowledgeLink`、`Current`、`Applied`、`KnowledgeApplied`、`Detail`、`Page`、`Choices`（均带 `PackageRetrospective` 前缀）。

## 本批拥有的文件

- 新增 `packages/retrospectives/{__init__,policy,observations,repository,catalog,knowledge}.py`。
- 新增 `packages/contracts/package_retrospectives_api.py`、`packages/contracts/sql/package-retrospectives.sql`、`apps/api/package_retrospective_routes.py`。
- 新增 `apps/web/scripts/generate-retrospective-contracts.py`。
- 新增 `apps/web/src/PackageRetrospectives.{tsx,css,test.tsx}`、`packageRetrospectiveContracts.ts`、`packageRetrospectiveProtocol.ts`、`packageRetrospectiveProtocol.test.ts`、`packageRetrospectiveFixtures.test-support.ts`、`test-fixtures/package-retrospective-http.json`。
- 新增 `tests/test_package_retrospectives.py`、`tests/test_package_retrospectives_pg.py`。
- 新增本验收文件和 `package-retrospective-checks.json`。
- 仅修改授权既有文件 `packages/knowledge/repository.py`，新增 9 行两个最小 hook。

## 未运行和真实材料缺口

没有真实招标/补遗、官方分项扣分原件、真实两轮工程师判断对照或真实成交资料。本批不能证明实际整改效果、逐项扣分解释准确性或中标概率；只有总分时仍保留逐项资料待补。

整包正式预测生产者、严格研究样本准入和风险闭环资格继续遵守原有门槛。复盘动作全部相关资格为 false，没有把企业知识候选升级为研究样本或正式模型。这些外部资料与资格缺口不阻止本批待核复盘和受控知识软件流程交付。

## 检查点 11 集成补充

本批已挂载实际 API／页面并重生成共享能力契约；完整冻结候选的后端、前端、TypeScript 和构建均通过。上文及原始收据保留独立开发阶段的检查状态，最终接线和共享 BASE 验证以 [检查点 11](PROGRESS.md) 及 [汇总收据](task-retrospective-layout-regression-receipt.json) 为准。该补充不改变原生专项的材料性质或正式资格边界。
