# 整包要求投影与人工范围声明

本契约包含不可变要求清单、人工范围声明与只读整包评审输入预检，部署于 fusion_v4 全新预览库；旧预览库及配置卷保留。正式整包评分、审查与提交链未接入。正式条款及决定仍分别以现有 `rule_items`、`decisions`／`decision_heads`／`rule_carryovers` 为唯一权威；新表不提供另一个可写条款正文。

## 冻结内容

要求清单固定本方包修订及 `package_digest`、权威依据包修订及摘要、稳定工程／标段／轮次／投标主体、身份摘要、实际规则集及摘要。每条固定原规则完整快照及摘要、当时精确决定快照，以及明确人工检查计划形成的 `Requirement` 与 `requirement_digest`。修改分类、数量、时点、条件、适用性或规则证据后，旧声明不能套用到新摘要。

未映射条款保留“未分类”、数量未知和适用未知；缺少声明的条款状态为 `unknown`。无引用集合不构成来源绑定。`not_applicable` 必须已有权威包内依据和明确人工声明。长条件正文完整保留在规则快照，投影内只保存其有序摘要引用，不截断正文，也不受手工章节树层级上限约束。

旧 `rule_sets` 未冻结完整抽取解析身份，其 v1 投影保持 `extraction_binding=unproven_legacy_rule_set`。新任务只有精确冻结输入、可信 Worker 完成事实及规则集绑定一致时，才可产生 v2 `exact_frozen_input_result` 投影；输入的全部成员／明确解析／逻辑范围和实际页证据逐项核对，旧投影不回填。两类均保持 `inventory_complete=false`、`review_ready=false`；精确抽取范围与实际抽取质量不是同一事实。即使每条都有人工作用范围声明，整体 `assessment.complete` 仍为 false。不得从文件版本、时间戳、最新解析或原 `matrix_checks` 推断已冻结完整抽取身份。

覆盖声明同时绑定包及要求摘要，页码为明确物理页。证据必须属于所冻解析、目标部件及其页范围；合订本／共享附件的一个证据可以具有多个合法部件归属。`verified`／`not_applicable` 的依据类型必须为 `human_scope_declaration`，附理由和真实证据；这是操作者人工声明核对范围，并非系统独立核验或自动合规结论。其他状态为显式 `human_observation`，不能以缺项默认满足。

## 接口与修订

统一前缀：`/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories`。

| 方法及后缀 | 行为 |
| --- | --- |
| GET 空后缀 | 清单历史列表及当前清单 ID；有当前版时提供 ETag |
| POST 空后缀 | 全量原规则投影，首版 `If-None-Match:*`，后续精确 `If-Match` |
| GET `/{inventory_id}` | 读取指定冻结清单及摘要 |
| GET `/{inventory_id}/coverage-attempts` | 人工范围声明历史列表 |
| POST `/{inventory_id}/coverage-attempts` | 追加一份不可变声明记录，逐条绑定要求摘要 |
| GET `/{inventory_id}/coverage-attempts/{attempt_id}` | 精确重开指定历史记录 |
| POST `/{inventory_id}/review-input-preview` | 明确选择冻结输入的只读预检；不创建正式任务或回执 |

写请求需要真实 Session、Origin、CSRF 与 Idempotency-Key。首版／后续条件缺失为 428，旧条件为 412；同键同正文及条件重放原 ACK，同键不同输入拒绝。分页游标签名并绑定 bid／包／修订／清单范围，不能跨范围复用。客户端不提交来源快照、当前身份或 actor；服务端从实际权威派生。原 manifest 以原规范摘要读取，不根据当前资料、决定或身份重建历史。

新写入要求 READ COMMITTED，锁序为 bid、来源图、包／决定／来源头。可变权威在最终 deferred 约束处重新核对；所有锁取得后选取同一个最终时点检查 known_at、valid_from／until，防止较早检查通过但提交前已过期。此时拒绝必须与 Command ACK 同事务回滚并返回不可重试 409／422，不能变成成功 ACK 或笼统重试 503。

来源快照保守覆盖所选文件版本的全部已知来源节点及全部祖先，记录节点政策、known_at 和来源头版本／状态／效力窗口。已知非标前政策、缺失来源头、未发布、撤回、未来或过期来源拒绝新用；完全无来源图可保留未知投影，但不得产生正向已核验资格。同文件旧来源别名也在此保守范围内，不冒充某一解析已单独取得完整来源资格。

## 整包评审输入预检

预检需要 Session、Origin、CSRF；不要求 Idempotency-Key，不登记 Command，即使客户端附带幂等键也不创建业务写入。请求必须显式给出 `package_digest`、`inventory_digest`、`coverage_attempt_id`、`coverage_digest`；不附人工记录时后两者都为 null。附上记录时必须与所选清单、包、项目及摘要完全一致，不以最近一次记录或多次记录合并代替。

响应为 `PackageReviewInputPreview`，HTTP 200。`manifest` 是 `bid-package-review-input/1`、`kind=preview`，完整包含明确选择的本方包／权威包冻结视图、要求清单与可选人工记录；`digest` 只标识这些不可变选择，不是评审任务 ID、已持久化新冻结记录或正式 `review-content/1` 身份。原评审和报告协议不改写。

检查在 REPEATABLE READ／READ ONLY 事务中进行，不更新当前正文、规则、包、清单头，不读取对象存储或调用模型。当前主体／标段／轮次、包与规则／清单头、项目生命周期、来源政策与效力、成员未知解析和物理页断口作为独立 `blockers` 返回；当前状态变化不改变已选历史输入及其摘要。共享页段按并集检查，未知页数不补假页码。

预检职责分层：`bid_package_review_repository` 读取明确选定的历史输入及当前观察；`bid_package_review_documents` 按冻结解析ID读取成员原件定位与实际页／证据，校验文件摘要、页数、解析器／配置和整份解析证据摘要；`bid_package_review_policy` 只计算阻断及物理页缺口，不访问数据库、存储或模型；`bid_package_review_preview` 只串联调用、返回选定输入摘要及只读结果。冻结未知解析的成员保留原有未知阻断，不能按最新解析或时间补齐。

已冻结成员的文件／页／证据身份无法复核时追加 `PACKAGE_REVIEW_EVIDENCE_CHANGED`，不改原manifest或摘要；正文与单块摘要同时改变也不能绕过整份解析证据摘要。只有明确的输入／证据领域错误被转为该阻断，数据库故障仍按原依赖错误传播，不能伪装成正常预检。只读核验使用同一REPEATABLE READ快照且不加写锁；已有冻结写入继续默认锁定解析行。返回的对象存储定位仅供后续服务内部核验，不进入本预检响应，数据库一致性不冒充原件字节验证。

`review_ready` 和 `launch_available` 固定 false。当前要求完整性未获证明，正式整包执行器未接入，必须保留对应阻断；人工观察和声明只附作上下文，不作为启动评审前必须已全部满足的循环条件。组件只提供“检查所选整包评审输入”，无正式启动按钮；切换或离开再返回同一输入时，迟到响应按代次丢弃。后续正式执行还需冻结方法／用途／事实／来源有效时点、验证原件字节和执行资格，不能把本预检快照直接交给旧单正文执行器。

## 所选整包原件字节核验

`POST .../{inventory_id}/review-original-verification` 使用Session、Origin、CSRF，HTTP 200；请求为 `PackageReviewOriginalVerificationRequest`：完整预检选择四字段加 `input_digest`，必须与所选不可变预检manifest精确一致。不要求Idempotency-Key，不登记Command、operation或正式评审冻结记录。

`bid_package_original_verification` 分别管理两个REPEATABLE READ／READ ONLY快照：先精确读取包成员及完整解析证据，关闭连接后调用独立 `original_verification` 流式读取对象，再开新快照重读全部输入和观察。对象IO期间不持业务连接或锁；解析、原件定位、包头、身份、清单、规则、来源和项目状态变化均不能被前一轮核验遮蔽。第二快照的效力时点重新计算阻断，时间本身递增不作为变化，效力阻断变化必须拒绝。

原件流每次最多1MiB，至多读到声明大小加1字节；核对实际大小及SHA256，不依赖ETag或HEAD声明，不一次缓存完整原件。流正常／失败均关闭；对象缺失返回409，未配置或供应商故障返回503，不将私有定位、签名或错误原文送到用户。明确内存对象流仅用于测试，不接入运行配置。

响应 `PackageReviewOriginalVerification` 为 `kind=observation`，包含选定输入摘要、服务端本次核对时点、每个目标／权威成员的明确版本／解析／文件摘要及大小、当前阻断；`originals_verified=true`仅表示本次全部所选原件字节匹配。`review_ready`／`launch_available`仍false，不产生持久资格或可复用执行凭证，不改旧manifest。对象定位和证据正文不进入响应。期间可变观察或输入发生变化返回409 `PACKAGE_REVIEW_INPUT_CHANGED`，不返回成功观察。

前端原件核验是独立按需加载组件，仅在明确预检后由按钮触发；校验完整成员列表、解析身份、输入摘要、时间和阻断，伪造ready／缺成员／串版本均不展示成功。重新预检，即使摘要相同也清除前次观察、丢弃迟到响应；不自动启动任务。正式执行必须在其实际发布边界重新完成原件和完整身份核验，不能复用本HTTP观察放行。

## 整包候选执行上下文

原件核验的两个只读快照现在同时捕获 `package-review-context/1`：明确包／要求清单／可选人工记录的原摘要、冻结主体、整包方法和政策、用途 `prebid_compliance`、事实集及逐项人工决定／依据、来源快照和服务端效力时点。核验期间事实头、人工决定或方法配置变化，均返回 `PACKAGE_REVIEW_INPUT_CHANGED`；只读观察不使用旧单正文事实校验的当前正文／最新解析路径，不取得该路径的来源写锁。

职责分为：`package_review_context` 读取事实权威与精确成员关联；`package_review_method` 声明整包方法／用途和实际代码摘要；`package_review_identity` 纯构造候选内容及身份；原件协调服务只负责双快照比较。旧 `review-content/1`、单正文方法和旧包manifest摘要算法不变。不借用旧执行器名称或评分资格。

事实捕获保留未确认及拒绝的条目、决定身份和头版本，缺失不默认为已确认；证据只记录与明确冻结文件／解析成员的关联，包外或缺证据为unproven。事实值和审计依据使用 `postgresql-jsonb-text` 表示，避免浮点转换及不安全整数进入规范摘要。本片不重审人工事实依据的正式适用资格；有事实时响应 `facts_binding=unproven`，无事实记录为empty，两者都不授执行资格。

候选 `semantic_digest` 包含明确输入、方法／政策、事实／决定和来源的内容；观察时点 `as_of` 单独由完整 `snapshot_digest` 绑定。两轮只比较语义身份，时间正常递增不会伪造成输入变化，但新时点的来源效力阻断仍须复算。拒绝无时区的时点，等价时区规范为UTC。方法声明的执行器与正式评分资格固定false，纯构造器拒绝不一致用途或伪造的true声明。

`PackageReviewOriginalVerification.execution_context` 仅返回摘要、用途、时点、事实集ID和计数，不返回事实值、审计依据、原件定位或证据正文。前端独立边界函数核对候选版本、用途、摘要格式、时点与观察一致、计数和恒false资格，折叠显示技术信息。原件核验返回的候选只在本次核验内构建，**该HTTP观察不是持久化冻结回执**。需要显式调用下一节的冻结接口保存新记录，观察本身不会自动保存；正式执行／发布仍待接入。

## 不可变整包评审输入与幂等冻结

新增 `POST .../{inventory_id}/frozen-review-inputs` 和 `GET .../{inventory_id}/frozen-review-inputs/{input_id}`。创建需要Session、Origin、CSRF及Idempotency-Key，HTTP201；读取为Session只读HTTP200。`FreezePackageReviewInput` 包含原件核验请求五字段及明确 `context_digest`，不接收客户端正文、证据根、actor、资格或冻结时点。

`bid_package_review_input_routes` 独立处理HTTP及提交失败边界；`bid_package_review_freezing` 处理原回执优先读回、锁外原件IO、最终事务重新捕获与保存；`bid_package_review_input_repository` 只处理不可变存取和原命令回执，不读取当前头。原件快照读取复用同一 `read_in_snapshot`，读检查由RR／RO调用，最终写事务在bid／来源图锁后以READ COMMITTED重新核对。

同键同请求先读原ACK，已有ACK时不读对象、不按当前来源／生命周期重算旧输入；同键不同请求409。并发初次请求可重复做只读核验，但最终bid锁和原Command唯一约束保证只写一份记录及ACK。原件IO不持数据库连接或业务锁；最终事务必须重新核对选择、原件定位／解析证据、方法／事实／来源及当前观察。新增记录和Command ACK同事务提交；延期约束拒绝时不返回成功ACK。存储未配置／原件损坏等初步核验失败不产生Command。

新记录 `package-review-frozen-input/1`、`kind=frozen_input` 绑定明确包／清单、actor／command、输入／上下文／证据根摘要及服务端时点。证据根 `package-review-evidence/1` 保存完整选择、捕获上下文及完整页／证据快照，剔除对象定位。以排序紧凑JSON的UTF-8原文存入不可变表 `bid_package_review_inputs.evidence_text`，SHA256绑定原始文本；其中已有页几何等JSON数字不冒充 `package_canonical_json` 的无浮点协议。外层manifest仍用规范摘要，引用根摘要。读取只校验原记录、根原文SHA和冻结身份，不按当前头／来源重建，不要求对象存储可用。

冻结记录保留未核资格与原阻断，`review_ready`／`launch_available`恒false；保存并不启动模型、operation或评审。当前身份／规则／来源等必须在新冻结提交时仍可用，旧记录则始终可读；未知要求完整性、未核事实等不会被“已保存”覆盖成合规。持久化输入与执行资格是独立状态，后续执行仍须自己的授权与发布前复核。

新增DDL在要求清单后、roles前执行，独立最小权限补片在roles后执行；共享基础计划14项。API仅有新表SELECT／INSERT，Worker仅SELECT；UPDATE／DELETE由权限和append-only触发器双重拒绝。新增fact_heads串行触发器复用原窄权限锁，覆盖首次头插入，不创造第二份事实权威。延期检查重用既有要求／身份／来源完整复核，另核事实头／完整条目／决定依据、精确原件／页证据、命令ACK及摘要；假证据或提交时过期回滚记录与ACK。

本片只交付接口及存储，前端“保存冻结输入”、未决请求刷新恢复、历史入口与正式执行消费尚未接入。初始化规则要求全新库，当前预览切到fusion_v4空库并保留v3数据库、原合成项目及配置卷；不在v3就地改表，也不把旧单正文非空字段填成虚假整包身份。

## 冻结输入内的项目事实管理

在 `.../{inventory_id}/frozen-review-inputs/{input_id}` 下提供五个实际接口：`POST /fact-confirmations`、`POST /fact-withdrawals`、`GET /fact-changes/{command_id}`、`GET /fact-context`、`GET /facts/{fact_id}`。写入需要会话、Origin、CSRF 与幂等键，返回201；读取需要会话，返回200。当前目录与详情必须显式携带 `frozen_digest`。目录稳定分页，游标绑定冻结身份及当前事实集；并发事实头改变后须重读。

确认请求明确给出当前事实集的 `expected_head`、`confirmation=confirmed`、主体／范围／名称／值／单位／证据与理由；替换需明确 `replaces_fact_id`。值只支持原 FactInput 的字符串、布尔或空值，不能将历史可读的任意JSON强转成新输入。详情对复杂或超长旧值仅提供摘要及撤回入口。撤回需要原事实编号、理由及准确当前头。调用方不能提交操作者、服务端时间或资格标志。新确认只消费冻结文件及解析实际包含的证据；目录返回的本方／权威来源包引用来自准确原冻结记录，界面不改读最新包。

新回执 `package-fact-change/2` 通过 `request_digest=SHA256({body,if_match:null})` 绑定完整原请求，同时核对原命令、201 ACK、不可变审计与冻结根。`package-fact-change/1` 原历史按原摘要读取，不补造完整请求摘要，不以旧协议充当新请求的精确确认。历史读取不清除客户端未决操作。事实修改、决定、集头、审计与命令同事务，CAS冲突或最终来源失效整笔回滚；不改变旧冻结输入、证据或报告。

界面显式读取事实、按名称和值选择、从冻结包目录读取原句及文件名，核对后人工确认。HTTP层、当前事实读取、领域写协调、恢复协议、依据选择和局部样式分别负责各自边界。提交前先保存原请求体及键，未知结果只恢复同一笔；账号／冻结身份隔离迟到响应，退出清理私有恢复记录。保存成功后重新核对执行条件。原件字节、事实资格、评审／执行／发布标志恒false，必要事实评估仍为 `not_performed`；这些接口不启动任务或模型。

## 全新隔离库依赖与权限

新增 `sql/bid-package-requirements.sql` 在 core、domain、bid-packages、stable-lot-identity、retrieval、worker-functions 之后、roles 之前执行。不可变表为 `bid_package_requirement_inventories`、`bid_package_requirements`、`bid_package_coverage_attempts`、`bid_package_coverage_results`；仅 `bid_package_requirement_heads` 前进更新。API 需要新表 SELECT／INSERT、仅 heads UPDATE 及新校验函数 EXECUTE，不授不可变表 UPDATE／DELETE。Worker 仅可按实际准备／完成链追加抽取绑定；不能改写资料包或清单。评分与研究角色不新增写权限。既有决定头及规则继承首次写入也由新增触发器按 bid 串行，继承路径复用已有窄权限 `lock_worker_bid`，保护原来没有当前决定的空键；任意直接 SQL 反向锁序仍可能被 PostgreSQL 判死锁而整事务回滚，不将其描述为正常路径无死锁。

真实数据库验证只通过项目 `tender-fusion` 的 Compose checks profile 运行，禁止临时独立容器及业务库。本机复用已有运行时完成纯测试 17 项，及新增源文件 ruff／mypy／bandit 检查。2026-10-19 同组 `requirements-api` 最终 20 项全部通过（22.17 秒），覆盖实际认证、CSRF、首版／追加 CAS、历史原摘要、非法 Unicode、最终提交过期零 ACK、SQL 伪造 assessment、当前决定变化、NULL／类型／安全整数／时间边界及决定空键／Worker 继承／来源新别名锁等待。测试隔离库为 `fusion_package_requirements_api`，API LOGIN 为 `fusion_package_requirements_service`，Worker LOGIN 为 `fusion_package_requirements_worker`，分别使用独立随机测试口令；结束后库及两个角色均清理。测试直接执行同一份最小权限 SQL `deploy/sql/bid-package-requirement-runtime-grants.sql`。

本轮真实执行 SQL 的 Windows 原文件 SHA256 为 `8b57eb43fda2413b2f10c2da641abbfd381eee44eb5b4ec4df147e52ae42f090`，不是 Git LF 规范字节摘要。证据保存在本地忽略目录 `.local/requirements-api-agent.xml`，12 个执行输入的原文件摘要保存在 `.local/requirements-api-agent-inputs.json`；最终测试后已逐项核对未变化。纯测试证据为 `.local/requirements-pure-agent.xml`。

本片新增的直接写入串行边界：`decision_heads` INSERT／UPDATE／DELETE 同 bid，禁止键改绑；`rule_carryovers` INSERT 复用 Worker 窄锁，原 UPDATE／DELETE 仍 append-only；`source_nodes` INSERT 获取既有 90127 图锁，原 UPDATE／DELETE 仍 append-only；`lineage_edges` INSERT 原已获取图锁，原 UPDATE／DELETE 仍 append-only。已知来源头全部需要存在且发布，最终按现有头行加锁，缺头拒绝新用。所有新增函数均为 invoker 并撤销 PUBLIC EXECUTE，不新增 Worker 业务写权限。未完成的专项包括任意直接 SQL 反向 tuple→bid 锁序死锁的零 ACK 验证、完整来源祖先／跨主体矩阵和历史坏数据读取矩阵，不将 20 项结果扩大描述为全部并发／产品验收通过。
