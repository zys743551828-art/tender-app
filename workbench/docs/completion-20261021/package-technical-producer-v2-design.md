# F06：完整图文三次判断与特征 producer 的实际软件装配

状态：正式执行链仍是独立增量设计；[非数值CPU特征投影](../../packages/contracts/package-technical-features.md)、[静态原页／细节派生](../../packages/contracts/package-technical-page-assets.md)、[完整图文材料绑定](../../packages/contracts/package-technical-input.md)及[实际图文请求／单次端口](../../packages/contracts/package-technical-vision.md)已有实现及零外部调用验证。完整材料绑定仅核外部owned投影的一致性，独立必要范围／来源权威、token／价格上界、硬隔离Worker、原生持久化／账本／租约与执行装配尚未完成。不会修改冻结的scope、eligibility、execution/1、reconciliation/1、历史研究核心或旧WIP SQL。真实配对材料缺失只阻塞真实资格／效果，不阻塞软件与零费用机制验证。

## 1. 目标和已确认的软件缺口

业务依据是 tender-docs `13bfcf1` 的《融合详细设计》10.1—10.3、《决策与依赖》DEC-014 及实施计划 F06-02、08、10。输入必须来自服务端冻结的完整相关章节、必要图表与有效条款；每个适用条款三次有效独立判断，重试不混计；保存具体性、有效性、前后一致性及引文诊断。原始判断、未校准逐项结果、正式校准预测和官方标签分别建类型。

现有软件已有真实 owned-job、费用账本、未知计费对账、三次判断隔离的合成验收，但以下仍是软件工作：

| 已有文件 | 当前边界 | 下一批责任 |
| --- | --- | --- |
| `package_scoring_readiness.py` | 无条件追加缺口，真实 provider 标志恒为 false | 新的原生 v2 context 读取实际装配/凭据引用/资格，不把恒拒绝当终点 |
| `package_scoring_profile.py` | 方法 /1，仅文本与表结构；图像未送入模型 | 版本化图文输入、全页渲染引用、维度判断及特征协议 |
| `package_scoring_producer.py` | 只接受 mechanism_test，直接复用旧 score 账本 | 新生产用途命名空间与实际配置 factory，合成库继续物理隔离 |
| `providers/deepseek.py` | `content` 只接受字符串，拒绝图像数组 | 独立图文适配器；复用有界 HTTP、严格 JSON/usage 校验和无自动重发规则 |
| `package_scoring_runtime.py` / Worker | 只允许隔离 test role，CLI 无付费 adapter | 独立真实用途 role、预算/lease/Worker/Kafka 事件装配、显式配置运行 |
| `package_historical_research` | 严格样本与 mean/median CPU 基线 | 未来将已绑定方法的真实三评特征接到独立训练导出，当前不得自动借标签 |

不能给旧 mechanism tables 加一个请求 `real=true` 就转成正式执行。旧约束、测试身份和既有结果保持原样。新 producer 首先交付有资格输入的**原始判断与特征**；原始判断不要求已有合格校准模型。正式校准预测仍必须经过 F06-08 线性模型、独立评估、影子观察、发布和回退。

## 2. 供应商事实及实现决定

2026-10-21 实际读取 DeepSeek 官方 [Vision](https://api-docs.deepseek.com/guides/vision/) 和 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 文档：`deepseek-flash` 已支持 user 消息中的文字和图像块。因此“仓库尚未实现图像传输”是软件缺口，不能写成供应商不支持。官方当前列出内嵌请求体 48 MiB、最多 600 图、无 file_id 时图像总量 64 MiB，15 图以上每边不超过 4096 px。这些是部署 profile 需要冻结并复核的上限，不是完整阅读资格证明。

官方 Vision 的 Token Usage 还说明预处理会把较大图像缩放到约1300×1300的总像素规模。因此即使发送 `detail=original`，也不能用原始像素数量声称细字、线标或复杂图例已可读。profile 必须冻结必要细节的可读性规则；需要局部裁片时，保留完整原页总览，额外裁片绑定同一原页 digest、像素坐标、缩放/渲染参数与完整上下文。预算、图像数量和 byte/token 上界计算包含全部总览与裁片。无法同时保留原页、必要细节和上下文或超出上界时明确拒绝，不静默删页、降采样、切掉图例或用片段冒充完整图文。

首个生产 profile 使用公司指定 DeepSeek、官方 HTTPS、固定 model alias、非流式单次请求、明确 temperature/thinking/output token 上限。图像以经过核验的 inline PNG/JPEG 发送，不引入任意远程图片 URL、供应商检索、工具调用或不明 file_id。保留供应商真实 response model、response ID、request ID、system fingerprint（若返回）、usage 和完整原始响应。模型别名不能冒充不可变权重摘要；不能承诺随机种子可复现。temperature 不承担独立性证明，官方接口说明 thinking mode 下该参数不生效；三次有效独立请求的含义是分开的调用身份、同一冻结输入、互不读取前次输出，并保存实际差异，不能称为统计独立样本。其他模型需各自经过 profile 审查，不能因为兼容 OpenAI 格式就默认等价。

本批一律零外部模型请求。正向以真实图文序列化/解析路径、显式 HTTP MockTransport、真实本地 PDF 渲染与 PG 权限/预算测试完成；真实配置 factory 必须存在，但测试进程无凭据、无网络 fallback。`configured`、最近 Worker 心跳和实际网络调用成功分开显示，不以配置文件存在伪装供应商已连通。

## 3. 当前用途输入权威

先冻结不含核验回执字段的`package-technical-verification-context/2`，独立权威记录指向该context及方法，再将真实回执摘要绑定最终输入，避免摘要循环。当前[单向绑定实现](technical-context-acceptance.md)只核外部原生引用与材料一致性，独立核验注册表／LOGIN及来源和内容权威仍须装配；不使用占位摘要，不把合成引用当已配置权威。

新 schema 建议 `package_judgment_execution`，独立于旧 `package_score_execution`。新接口接受 saved scope ID、显式满分 authority ID（若需要数值输出）、方法/profile ID、期望 context digest 和预算；不接受任意正文、引用列表、执行模式布尔或官方成绩。

服务端构建不可变 `package-technical-judgment-input/2`，至少绑定：

- 项目、稳定标段、主体、轮次的完整 v2 identity，目标 package/revision/scope、scope digest、inventory/rule set、全部权威招标和补遗 revision。
- 当前评审 `input_as_of`、真实取得/生效/适用时点、来源祖先闭包和 source head；`frozen_at` 不替代业务 as-of。
- 所有相关完整章节及后代、关联附件和跨节引用；每条必要条款的原文档、物理页、原文、档位与适用范围。不能只取首册、top-k 或摘要。
- 每个原件的 digest/byte size、冻结 parse ID、物理页全集、证据块和顺序；缺页、重复页、解析失败、图文对不上或超预算均明确拒绝，绝不截断。
- 独立必要范围核验回执：来源权威、原件与规则依据、具体范围/页面/条款映射、核验程序/人员及结果。用户勾选技术册不是证明，模型声称“完整”也不是证明。
- 页图派生回执：从同一实际原件经固定 renderer/version/参数得到、每页像素与字节摘要、渲染时间、原页对应；必要细节无法辨认时明确拒绝。OCR 文本不得代替图页。

“受信任证明接入”允许可审阅的原平台回执、可信受控渲染/核验记录或经配置发行方的签名证据。签名只绑定来源声明，不单独证明内容完整或当时存在；不将原需求限定为某一个签名体系。当前生成的图页可以用于当前输入，不能回填历史 byte-known 时间。

资格分层：`input_verified`、`raw_judgment_executable`、`uncalibrated_numeric_eligible`、`formal_prediction_eligible`、`historical_sample_eligible` 各有依据。满分/聚合不明时仍可保存合法的非数值原始条款诊断；不得给数值总分。历史标签来源和历史四时点证明只出现在独立历史路径，当前 scorer 永远看不到官方标签或 final exports。

## 4. 数据对象与最小权限

| 对象 | 不可变绑定 / 可变状态 | 读写边界 |
| --- | --- | --- |
| `provider_profiles` | provider、endpoint、alias、能力/请求限制、价格来源版本、方法 digest；仅密钥引用 | 配置者登记；API 读脱敏状态；Worker 启动从私有文件加载密钥 |
| `input_verifications` | exact scope/context、必要范围证据、原页及来源闭包摘要、适用时点、验证器版本 | 独立输入验证 LOGIN 写固定 RPC；API 只读缺口与结果 |
| `inputs` / `rule_packets` | 全部完整输入、方法/profile、逐条款实际范围/资产 manifest；封存后不可追加 | 服务端冻结；生产 Worker 仅通过 owned RPC 读同一 lease 的最小完整投影 |
| `input_assets` | 目标原件与确定性页图 byte hashes、顺序、尺寸、媒体类型、派生来源 | 受限资产读取能力；无任意 bucket/list 或任意路径参数 |
| `jobs` / `events` | exact input、generation/fence/owner/lease、暂停/取消状态、预算 ceiling、执行原因 | API 命令 + 独立 Worker RPC；Outbox/Kafka 仅派发身份 |
| `calls` / `call_events` | 条款、replicate 1—3、attempt、发送状态、request/body/model/price 摘要及费用 | 原子 reserve/mark-send/settle；reconciler 单独权限 |
| `judgments` | 有效/无效/无法判断原始响应、slot/call、完整输入、引文校验与失败原因 | Worker 借当前所有权追加；不能直接升级为有效 |
| `features` / `results` | 三个有效独立 call 的完整闭包、方法版本、确定性特征、只读历史结果 | 发布 RPC 复验全部约束；API 只读脱敏结果 |

生产 score LOGIN 不属于 `tender_api/tender_worker/model_train/evaluate`，没有 design/outcomes/chat/proofs/final 的通用 SELECT，也不继承业务环境。原件/图页由专用资产服务或受限存储凭据读取服务端冻结的键；URL/路径不由 HTTP 请求指定。资产消费前后核验当前来源，文件摘要不符立即停止。不得为了适配图像给 scorer 一个通用 bucket 凭据。若首版选择在独立资产表内保存经过限制的图页 bytea，也只能经 owned RPC 输出，不授表 SELECT；两种实现使用相同 manifest 与限制。

输入核验器不能读取历史标签或 final。必要时复制已有纯字节/时间/图像格式校验逻辑为独立受审模块，不能整块调用包含官方标签的 `package_history_proofs.verify()` 再删除几个字段。共享锁顺序沿用治理 91143 → 完整排序 bid 锁 → 图锁 90127，暴露关联涉及时再 91144。

## 5. Owned job、预算、传输和恢复

建议固定 RPC（都核对实际 session role、完整身份、当前用途与 generation/fence）：

| RPC | 行为 |
| --- | --- |
| `execution_context(scope, profile, scale)` | 单次完整观察及 ETag，精确列出未安装/未配置/证据/图页/预算缺口 |
| `verify_input(exact_receipt, expected_context)` | 独立验证器核验并存绑定回执，不接受资格布尔 |
| `freeze_input(scope, verification, method, profile, expected_digest)` | 锁内复核全部源、必要范围及资产，产生不可变输入 |
| `start_job(input, ceiling, actor, command)` | 请求重放优先；验证预算能覆盖每条款三个有效槽位，不能部分预付后假装完整 |
| `claim_job/heartbeat/owned_input/owned_asset` | 当前 owner、generation、fence、有效租约及目的检查；无对象 I/O 长事务 |
| `reserve_call/mark_send/settle_call` | 原子预留、持久发送意图、真实响应/usage结算，未知费用保留预留 |
| `reconcile_call` | 独立凭据/权限，绑定 provider 原始凭证；不能以人工勾选“没发”清账 |
| `publish_result` | 同输入每适用条款三个有效 slot、不同调用/响应、同方法与 provider 身份；源变化或旧 fence 拒绝 |
| `control_job` | 暂停/取消/恢复带 ETag 与幂等键；已成功 slot 复用，unknown 不自动补发 |

每个 slot 与 attempt 分开：三个独立有效调用使用 byte-identical 的完整语义输入，无前次结论、无聊天、无检索追加；slot/attempt/request nonce 仅在账本与受控 request ID 中。一次无效但已计费响应保留真实费用，不能算有效 replicate，也不能称零费用重试。重试策略与最大 attempt 在方法/预算中预先冻结；同一 slot 的成功结果不可被另一个 slot 复用。服务端约束同 provider response ID 不重复充当独立判断。

reserve 已提交且 Worker 崩溃、发送超时、取消或响应计费未知时进入 `reconciliation_required`；不得无条件再次发送。lease 到期不能替旧 owner 发布，迟到响应仍可以受限记账但不授发布资格。取消/来源撤回停止新 reserve/send；已在途请求允许追加真实计费记录，保持不可撤销的费用事实。预算超限、价格profile改变、模型别名不符、输入或图页变化均拒绝新调用。

实际 Worker 具有私有配置文件、白名单环境、固定 `python -I` 入口、心跳及可恢复 one-job 执行，并由已存在 Outbox/Kafka 消费路径调用；事件仅含 job/generation，不带正文或标签。每个外部调用前无打开的数据库事务；网络有总 deadline、无 redirect、受控 endpoint、无普通 HTTP 自动 retry。复用现有账本算法和 `usage_estimate`，但不放宽旧 synthetic 库权限。

## 6. 三评输出与特征

新 `package-technical-judgments/2` 对每条款保留 band、要点覆盖、针对性/具体性、有效性与跨节一致性诊断，逐项附 evidence IDs、原文、文档、解析、物理页，以及必要图像区域/页图 digest。程序核对引文真实、原件与页图绑定、规范 enum、字段闭包、数值有限、全部必需内容被处理。语义诊断是模型判断，不冒充程序已证明正确。

`FeatureBuilder/2` 是纯 CPU 确定性函数，从三个已验证判断和原规则派生特征及分歧。规则档位数值仅来自明确原条款；没有权威分值映射时保存类别特征。图表数量不直接加分，三评多数一致不当独立真值，波动不当置信区间。缺一个有效判断就保存失败/已评范围，不能补0、插值或外推完整总分。

首次输出明确 `prediction_kind=raw_judgments`，`formal_prediction=null`，`training_eligible` 不由 producer 授予。未校准逐项合计仅在所有必需条款覆盖、档位分值/总分/聚合明确且无冲突时计算；单独标为未校准。后续原生历史 feature export 必须联结同一 scope+exact submission+method+完整三评闭包和已经验收的样本准入，不能拿当前正文/最新版判断补旧实交。

F06-08 线性校准、组级 final、质量证书、shadow→发布→回退仍是后续独立可实施软件工作，不以“暂无真实样本”关闭。它可以合成输入验证算法和权限，但不能给真实误差、精度或路由资格。

## 7. API / UI 增量与分工

建议新独立 router，不改冻结 /1 的含义：

- GET saved scope 下 `/judgment-execution-context`：实际能力、资格与完整缺口，重复/未知 query 拒绝。
- POST `/judgment-inputs` 与 `/judgment-jobs`：明确源版本、方法、预算、ETag、幂等键；默认配置缺失时具体拒绝且 jobs/calls=0。
- GET `/api/v1/package-judgment-jobs/{id}`：当前执行、各条款三槽位、真实费用状态、可恢复原因及结果类型。
- POST job `/control`：暂停/恢复/取消；没有 mechanism_test 的公开 UI 或请求开关。
- 独立 `PackageTechnicalJudgment` 面板由 root 挂入已选 saved scope；不要求用户手输 UUID。配置失败、缺完整来源、图像不可读、无满分与无校准模型分别显示。

预计新增 `deploy/sql/package-judgment-inputs.sql`、`package-judgment-execution.sql`、`package-judgment-reconciliation.sql`，以及独立 provider/authority/profile/feature/runtime/Worker/API/contract/test 文件。SQL 均显式 optional，不入 BASE 或默认恢复；安装顺序和故障行为由真实 PG 测试冻结。真正所需的共享挂接先交 root，不静默改冻结方法或合成通道。

## 8. 验收清单与边界

在独立新库使用生产形状的固定 RPC和真正独立 API/verify/score/reconcile LOGIN，专门合成配置必须由初始化阶段登记并锁定在 disposable DB 与测试角色，不可污染生产 origin。实际测试至少覆盖：

1. 真正多页 PDF → 原页渲染/必要局部细节裁片 → byte hash/坐标/顺序 → inline图像序列化 → 真实 adapter解析的零网络链；图像置换、裁片脱离原页/缺上下文、缩放后必要细节不足、缺页、非法图片、超长/过多/预算拒绝且调用0。
2. 每条款三有效独立请求；第二次引用第一次响应、同响应ID复用、重试混计、未知费用补发、失效slot重用被拒；无效响应真实计费与恢复。
3. 未安装、未配置provider、错误profile、credential仅存在未连通、撤回来源、标段/主体/轮次变化、过期lease、旧generation发布、跨目的读label/proof/final均实际拒绝。
4. 取消/崩溃/超时释放对象与连接，网络期间数据库idle，独立heartbeat能续租；未知send/fee不自动重试，晚到回执只记账。
5. 完整软件正向返回可核查三评特征；无聚合/满分不返回数值总分；无校准发布不返回正式预测；合成结果永不进正式样本/metrics。
6. 实际 ASGI/PG fixture供前端协议与浏览器验收；所有源码/SQL/profile/方法摘要及运行收据冻结，零外部模型调用。

这些正向只证明软件和权限机制。真实原件、真实可信范围/时间证明、实际供应商连通和独立质量评估仍须分别据实记录；它们不是继续实现上述软件的前置许可。
