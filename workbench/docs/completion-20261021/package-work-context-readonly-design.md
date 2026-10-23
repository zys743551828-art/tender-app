# 项目整包摘要与四阶段上下文：只读关联设计

日期：2026-10-21。状态：设计提案，未增加 API、SQL、契约、页面或业务头。以批准主计划 F12-06／F12-08、UI 导航 3–5／9–10 与 AI9 为依据；前置的后端主要动作规则仍归 F05-05。本文件不宣称上述工作已完成。

## 1. 结论与最小下一批

应建立一个按用户明确选定对象解析的只读工作上下文，再让项目摘要、正文／生成／核查／实交入口共用其确切身份。四个阶段有一对多和可缺失关系，不能做四个自动跳向“最新”的按钮。

现有数据已经支持草稿快照→构建→输出文件、投标包修订→核查、实交→冻结整包与可选核查的精确关系。最主要的服务缺口是：生成文件采用回执缺少只读发现入口；没有统一的整包上下文解析／摘要；深链尚不能完整携带某轮整包核查或某次实交。新增只读服务可以完成这些软件工作，不需要真实模型、官方成绩或新业务授权作为前提。

建议下一批先做**明确选定的整包核查／实交上下文解析与摘要**，同时发布生成采用关系的只读目录。前端先实现独立四阶段选择器、只读上下文详情与摘要，根负责最小导航／页面挂载。旧业务写接口和原请求恢复机制保持独立。

## 2. 已核对的真实能力与缺口

| 对象／关系         | 已有实际入口或字段                                                                                                      | 可以陈述的事实                                                                                            | 仍缺什么                                                                  |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| 项目               | `Bid.current_body_id`、`current_review_id`、`next_action`                                                               | 项目与旧单正文当前头                                                                                      | 没有可直接代表全部整包的风险／评分摘要；旧评审头不能充当整包核查头        |
| 草稿               | `GET /bids/{bid}/drafts`、`.../drafts/{draft}`、`.../draft-snapshots/{snapshot}`                                        | 保存修订、快照、章节与正文                                                                                | 历史快照作为统一选择器对象的显示入口；当前编辑器不能被冒充成历史只读稿    |
| 构建               | `GET /bids/{bid}/builds?draft_id=...`、`GET /builds/{id}`                                                               | `AuthoringBuildIdentity` 固定 draft／revision／snapshot／input；每个格式有独立输出状态                    | 统一选择器需先选构建，再明确具体格式／文件；“构建已受理”不能显示“已生成”  |
| 生成文件采用       | `POST /bids/{bid}/builds/{build}/package-adoptions` 的持久回执                                                          | 回执固定构建、文件、草稿快照、采用后的整包修订；`automatically_started_review=false`                      | 目前没有 GET 采用关系目录；刷新后不能靠前端缓存或文件名恢复该关系         |
| 投标包             | 包目录、修订目录、确切修订 GET                                                                                          | package／revision／digest 与每个成员、解析、用途、页范围                                                  | 包目录没有人为名称时应显示“投标包 · 修订 N”与身份详情，不造名称           |
| 整包核查           | native `.../frozen-review-inputs/{id}/execution-inputs/{id}/review-runs/{run}`；项目 `knowledge-reference-targets` 目录 | run 固定 package／revision／inventory／frozen／execution／dependency plan／input／method，结果独立 digest | 没有“整包当前核查头”。知识目标目录只是发现入口，不是当前性或执行资格证明  |
| 实交               | `GET /bids/{bid}/submissions`、`GET /submissions/{id}`                                                                  | `PackageSubmissionView.package_binding` 固定包、清单、范围、可选核查、附件与当时门禁；更正链另留          | 独立选定 submission 的主工作面深链；单正文与整包必须用 discriminator 区分 |
| 官方成绩／业务结果 | `outcome-context?submission_id=...`、outcomes、business-results                                                         | 官方结果属于确切 submission；head／核验／可用性分别存在                                                   | 不能把项目成绩合并成当前包预测，或用总分猜逐项原因                        |
| 正式技术分状态     | 精确 technical-scope 的 scoring-context／execution-context                                                              | 当前协议明确数值预测为 null、资格条件与缺口可读                                                           | 摘要只能显示实际不可用／未选择原因，不能填零、旧分或合成分                |

核对源码：[项目投影](../../apps/api/views.py)、[旧评审投影](../../apps/api/review_views.py)、[生成目录](../../apps/api/history_routes.py)、[生成身份](../../packages/authoring/build_views.py)、[采用协议](../../packages/authoring/package_adoption_contracts.py)、[采用回执](../../packages/authoring/package_adoptions.py)、[核查原生 API](../../apps/api/bid_package_review_run_routes.py)、[发现目录](../../packages/knowledge/bridge.py)、[实交关联核验](../../packages/domain/bid_package_submission_observations.py)、[正式分只读边界](../../packages/contracts/package_technical_eligibility_api.py)。

## 3. 关联规则

### 3.1 允许的关系

| 起点→终点                 | 服务端必须核验的依据                                                                                | 基数与展示                                                               |
| ------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 已保存快照→构建           | 构建 identity 的 bid／draft／draft_revision／snapshot_id／snapshot_digest 完整匹配                  | 一个快照可有多个构建；展示目录，用户选择                                 |
| 构建→输出                 | build_outputs 所属 build／bid、格式、成功状态、确切 document_version；详情补原字节 digest 与大小    | Word／PDF 是不同文件；待完成格式保持没有文件                             |
| 输出→采用后的包修订       | `adopt-authoring-output` 持久回执的 output 与 package 身份；回执与规范 manifest 摘要相符            | 同一输出可被多个包采用；明确选择关系，不能取最后一个                     |
| 输出→另一个包含它的包修订 | 精确包成员明确包含同一 document_version；若有生成准入则另列验证状态                                 | 只称“此修订包含此文件”，不能伪称通过某次采用形成                         |
| 包修订→核查               | run.scope 与 input 中 target package、inventory、冻结输入、执行输入、依赖计划、方法及各 digest 匹配 | 同包可有多轮／多方法／多清单；列表排序不构成选择                         |
| 实交→包／可选核查         | immutable `package_binding.manifest.selection_request`、subject 与 review_run 快照                  | 选定实交可以直接还原它明确冻结的关联，不自动补上未绑定核查               |
| 实交→成绩／结果           | outcome／business_result 的 bid_id 与 submission_id，明确 head 或明确历史记录、核验状态             | 默认可展示服务器声明的结果头及“当前观察”；不能更改用户固定的历史结果选择 |

文件名、下载时间、项目标题、日期接近、同样的字节摘要、列表首项和当前正文头均不足以建立上述关系。摘要相同也不允许跨 document_version、包或投标主体补连。真实缺关系时显示“尚无已证明的关联”，提供只读目录，不自动采用、构建、核查或补录。

### 3.2 当前性与历史身份分开

历史对象的 ID／manifest digest 不会因当前包换版而改写。当前性是一次读取时观察到的状态，建议显式枚举：`matched`、`changed`、`unknown`、`not_applicable`，带 `observed_at` 与原因。

必须分别记录包头、清单头、来源／事实／方法、实交头等比较结果。不能用一个 `is_current=true` 覆盖全部语义，更不能根据“最新创建的一轮”给整包核查造一个 current head。已选历史核查可以继续阅读原结果；“有历史结果”和“可用于当前投标”分开呈现。

## 4. 建议只读 API

下列路径和版本名为本提案，尚未注册到实际 OpenAPI。

| 接口                                                                        | 用途与限定                                                                                                                                                    |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /bids/{bid}/work-context-choices?kind=...&limit=...&cursor=...`        | 四阶段发现目录；kind 仅允许 draft_snapshot／build／package_review_run／package_submission。按明确筛选发现，不选首项。支持 draft／package／revision 等有界过滤 |
| `GET /bids/{bid}/work-contexts/{kind}/{id}`                                 | 解析明确对象。draft_snapshot 用 snapshot ID；build 用 build ID；核查用 run ID；整包实交用 submission ID。返回规范身份、只读状态、摘要与原生读取目标           |
| `GET /bids/{bid}/work-contexts/{kind}/{id}/relations?target=...&cursor=...` | 按确切种子列有凭据的其他阶段关系；返回关系类型和证明摘要。采用关系从持久回执／规范记录读取，不暴露命令幂等键、请求头、对象存储路径                            |

首批无需创建全局“当前包”“当前核查”或用户选择业务表。用户最后选择仍是成员／项目隔离的浏览器导航偏好，恢复时重新解析确切身份。若以后需要跨设备同步，另加用户偏好协议；它也不能成为业务资格头。

### 4.1 精确选择与返回字段

客户端保留规范 `selection`，由发现／解析响应取得，禁止把多个互不相干的选择拼成一个合格上下文：

| kind               | 必备固定身份                                                                                                                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| draft_snapshot     | bid_id、draft_id、draft_revision、snapshot_id、snapshot_digest                                                                                                                                                      |
| build              | bid_id、build_id、draft_snapshot_id、snapshot_digest、build_input_id、input_digest、manifest_digest；output 只有明确选定实际成功格式时才附 document_version_id／format／sha256                                      |
| package_review_run | bid_id、package_id／revision_id／package_digest、inventory_id／digest、frozen_input_id／digest、execution_input_id／digest、dependency_plan_id／digest、run_id／input_digest／method_digest、nullable result_digest |
| package_submission | bid_id、submission_id、package_binding_digest；subject 从 frozen binding 取得；可选 run 只能来自该 binding                                                                                                          |

DTO 采用封闭键与 discriminated union。ID 必须为真实 UUID，摘要为小写 SHA-256，缺失值用 null／明确状态，不用空字符串。请求路径种类／ID 与返回 selection 不符则拒绝渲染；非法类型、重复参数、跨项目对象、外来包修订等应被接口拒绝。客户端不能传入 counts／availability／next_action 等派生值。

响应建议包括：

| 字段                                | 含义                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------- |
| `version`                           | 固定 `package-work-context/1`；升级另行兼容                               |
| `selection`、`selection_digest`     | 上表规范选择及摘要；所有小节都必须绑定同一选择                            |
| `observed_at`、`observation_digest` | 当前只读观察时间与整体响应依据摘要；不冒充历史冻结时间                    |
| `identity`                          | 项目／轮次／标段／投标主体真实名称及 ID，身份未确认时明确显示待确认       |
| `state`                             | 原生 operation／output／submission 状态，不能把 accepted 映射为 succeeded |
| `current_observation`               | 按包、清单、来源、事实、方法、实交头分别比较；不可观察项为 unknown        |
| `summary`                           | 第 5 节限定的范围计数、评分可用性与主要下一步                             |
| `native_targets`                    | 封闭的工作面目标枚举与确切 ID，不接受任意 URL／脚本                       |
| `limitations`                       | 可显示的缺口代码与简短说明                                                |

读事务使用 `REPEATABLE READ READ ONLY`，在同一快照中核验选择、关系、结果和当前观察。使用 API 非 owner 账号，只授所需 SELECT 或受限只读函数。GET 不写 audit、heads、qualification、task、command、source、admission，不跑模型、转换、原件下载或修改保存状态；返回 `Cache-Control: private, no-store`。

`original_bytes_reverified` 固定 false，除非另有独立且明确的原件校验操作。既有 `package_outputs.capture` 是只读证明读取，但其 current admission／字节重核能力不能被摘要的“关联存在”替代。[已有 capture 边界](../../packages/authoring/package_outputs.py)

### 4.2 目录完整性与分页

每个目录返回 scope、items、has_more、next_cursor 和 observation。零项且读完可以称“没有已登记关联”；未读完、访问失败或预算截断只能称“当前已读取范围未发现”。总数未知为 null，不能用当前页长度作全量计数。

新目录采用绑定筛选／种子／观察上下文的游标，避免并发插入导致 offset 漏项。续页发现当前观察变化时明确拒绝拼页并要求重新读取；之前结果仍可作为“上次读取”保留。已有 offset 发现目录可以暂复用为选择辅助，但不能据其多页拼接结果宣称原子全量。

## 5. 项目与报告摘要

### 5.1 未选择时

项目列表先显示项目阶段、真实主体、包目录观察状态和“选择包／核查继续”。未选择整包时 `selected_context=null`，整包风险／评分／主动作中依赖具体范围的字段保持未知。即使项目当前只有一个包，也不自动替用户固定某个修订或某轮核查。

用户曾明确选择的上下文可恢复为“上次查看”；在只读解析成功前，不显示旧绿色状态为当前。项目列表若需要批量读取，应新增受限批量只读投影，复用同一服务解析每条 selection；不能在浏览器给每行盲目请求最新包／最新 run 后汇成一个分数。批量接口可作为单对象路径验证后的独立优化，不应先扩大首批范围。

### 5.2 已选择时

| 摘要项   | 服务端推导与展示要求                                                                                                                                    |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 范围身份 | 包修订、所选清单、run、方法、结果摘要；主文案人读名称优先，身份详情折叠                                                                                 |
| 机器结果 | 从所选 native result 的完整 matrix 推导并核对原 counts；显示“已声明范围内：发现不符／未找到／无法判定……”                                                |
| 人工意见 | 从明确 run／result／row 下的意见头单独统计，返回 human_heads_digest；不得覆盖机器结论，也不得把确认当风险解决                                           |
| 覆盖     | matrix_coverage、overall_coverage、清单完整性各自列示；当前整体部分覆盖不能写整包通过                                                                   |
| 阻断风险 | 只有复用现有领域门禁、其范围完整且当前观察可核时才给“已知阻断”计数；语义不成立时 null，并显示范围待核。不得把 satisfied 条数换算成合规率                |
| 技术分   | 未明确技术 scope 时“未选择范围”；已选则按实际 eligibility/execution 只读协议显示。当前 `numeric_prediction` 仍为 null；正式分、报价分、官方分为不同字段 |
| 官方事实 | 仅实交阶段且绑定确切 submission 时展示明确官方记录／口径／核验状态。当前投前 summary 不读取官方标签，防止泄漏到预测视角                                 |
| 下一步   | 一个后端派生 `primary_action` 与其余分组计数，所有入口复用同一 observation／selection_digest；按钮只打开明确工作面，执行仍需该领域正式命令              |

`PackageReviewRunSummary` 的 `requirement_count` 不是风险数。现有范围核查整体覆盖为 partial，不能把其零不符显示为“无风险”。[范围报告当前语义](../../apps/web/src/PackageReviewReport.tsx)

下一步的六级业务优先仍应以 F05-05 批的同源政策落地；本设计不在前端再造一套排名。首批可先给严格导航动作：选择缺失范围、读取原记录、核对变化依据、查看明确运行状态或进入所选结果。任何“重新核查／生成／提交”仍由正式工作面进行新鲜门禁、显式确认及原请求恢复，不能因摘要按钮直发 POST。

## 6. 前端最小关联协议

独立新增 `WorkContextSelector`、`WorkContextSummary`、`workContextProtocol` 和只读 hook。选择器上方显示一次项目／主体；四个阶段提供真实目录、固定选择和已证明关系，不让每个子面板重复选项目或偷偷选择最新记录。

1. **初次进入**：优先恢复完整有效深链，其次成员／项目隔离的已选偏好；两者都没有则停在明确选择。缺参／重复参数／跨项目记录显示错误，不回退当前头。
2. **切换阶段**：保存原选择；通过现有导航 guard 与 PackageScopeGuard 后，解析用户点击的对象。仅同一 bid／member／request sequence 且身份匹配的回应能提交新上下文，迟到回应不切走当前任务。
3. **草稿阶段**：已保存快照与本地未保存编辑分开显示。快照可以只读回看；打开当前编辑稿是明确的另一导航。未确认保存不得改变“已保存版本”或生成／核查选择。
4. **生成阶段**：目录可以按创建时间排序并标“最近生成”，但不选首项；Word／PDF 分别有状态。下载使用所选实际文件 ID，选择成功文件不表示已采用进包。
5. **核查阶段**：若从实交绑定进入，使用它明确冻结的 run；没有绑定则显示缺失。若从包进入，列匹配候选，由用户选择。不能用 `Bid.current_review_id` 或最新 run 代填。
6. **实交阶段**：保留明确标准／补录与更正链；切换实交同时切换成绩／结果的 submission scope，旧请求不得覆盖新卡。
7. **本地稿与未决命令**：选择器不能清除原 scope 的 drafts、command key、body、条件或业务回执。guard 未放行则保持原页／选择；返回原 scope 可继续恢复。上下文 DTO 本身不能成为写请求的 CAS 或替代业务 ETag。
8. **窄屏**：一个阶段及其目录／详情按需展开；桌面可以紧凑显示四阶段入口。切换只读视角不启动业务操作。

根需要的共享接线：

| 位置                                     | 最小接口                                                                                                        |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| App／ProjectWorkspace                    | 统一 `selectedWorkContext` 与 `onSelectWorkContext`；仍走现有导航 guard                                         |
| AuthoringPanel                           | 已有 `onOpenDraft` 只表示进入当前编辑；历史 snapshot 另用独立只读预览，避免伪造编辑基准                         |
| AuthoringBuilds                          | 可传明确 selectedBuildId／selectedOutputId；匹配 identity 后显示，不改创建构建逻辑                              |
| packageNavigation／BidPackages／核查子面 | 当前链接只有 package／revision／inventory；需扩展完整 frozen／execution／run 只读目标并验证关联，缺参数不选最新 |
| SubmissionPanel                          | 可传明确 selectedSubmissionId／expectedBindingDigest；展开指定记录，仍保留原命令 scope                          |
| 项目列表／报告摘要                       | 复用同一 summary DTO，禁止分别在前端计算主动作／风险                                                            |

当前可复用的明确选择范例：[整包导航验证](../../apps/web/src/packageNavigation.ts)、[实交精确选择](../../apps/web/src/PackageSubmissionSelection.tsx)、[构建原请求恢复](../../apps/web/src/AuthoringBuilds.tsx)、[核查原请求恢复](../../apps/web/src/PackageReviewWorkspace.tsx)。

## 7. 可独立实施的批次与验收反例

| 批次                | 可独占文件范围                                                                      | 成果                                                                                  |
| ------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| A：原生关系与摘要   | 新 `packages/work_contexts/`、独立 API／contracts／SQL 只读权限或索引、独立后端测试 | exact resolver、adoption／membership 关系目录、run／submission 摘要；不新增业务 heads |
| B：选择器与只读详情 | 新组件／协议／样式／单测／浏览器夹具                                                | 四阶段明确选择、恢复、未知状态、原生目标输出，先用真实协议合成 HTTP 验证              |
| C：根共享接线       | 根所有的 App／ProjectWorkspace／导航／既有面板 prop                                 | 深链、返回、跨工作面同一身份、同源摘要；原有独立入口继续兼容                          |
| D：列表批量摘要     | 在 A 的解析规则上新增有界批量读与列表 UI                                            | 避免 N+1 与部分目录假全量；延后到单对象验证完成                                       |

下一批验收必须包含以下反例，不需要真实业务资料即可实现和验证：

- 同项目两个包、同包多个修订、同修订两轮核查，创建时间与用户选择相反；始终打开明确对象。
- 同一草稿快照两个构建，Word 成功而 PDF 失败；生成摘要／下载不替换为另一构建的 PDF。
- 同名不同文件、同字节不同 document_version、同输出多次采用；只承认对应证明关系。
- 无采用回执但成员包含同一 document_version；只能显示“包含”，不能显示“由此采用生成”。
- 实交没有 run、离线补录、单正文实交混入整包路径；不自动补核查或跨 discriminator 解读。
- 包头／清单／来源／方法／事实／人工意见头在读前后变化，结果仍为历史且当前观察失效；续页不能混合观察。
- 目录空、还有下一页、403／404／读取失败分别显示；风险未知不显示 0，正式分仍为 null。
- 仅有 satisfied 或零 violated 但 overall partial；不显示整包通过或标准提交资格。
- 官方分只有技术总分或综合分、核验待定；不推测另一口径，不输入当前投前预测。
- 390 px／桌面深链、刷新、后退、快速 A→B 切换与迟到 A 回应；无未授权写请求。
- 切换时本地编辑未保存、保存 ACK 丢失、构建／核查／实交未决；守卫保留原请求和原 scope，可返回恢复。
- 原生 PG 使用 API 非 owner 账号；读取不能改任一业务表、来源用途或正式资格。证明字段篡改、错误 join、跨项目 ID、缺失 manifest／receipt 都拒绝关联。

## 8. 本次做了什么、没有做什么

本次重新读取批准 F12 目标、现有只读目录、生成身份／采用回执、整包核查／实交／成绩关联以及相关前端选择与恢复代码。新增本设计文件，没有执行数据库查询、模型或业务命令，没有改后端／共享 UI，没有把任何提案路径登记成已实现接口。

助手确认卡与来源详情的完成情况另见 [本批验收](assistant-review-details-acceptance.md)。本设计的下一步是根分配 A／B／C 的文件边界后实施；无需等待真实标书或官方结果才能完成上述软件路径。
