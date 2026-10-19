# 整包要求投影与人工范围声明

本契约包含不可变要求清单、人工范围声明与只读整包评审输入预检，部署于 fusion_v3 预览库；旧预览库及配置卷保留。正式整包评分、审查与提交链未接入。正式条款及决定仍分别以现有 `rule_items`、`decisions`／`decision_heads`／`rule_carryovers` 为唯一权威；新表不提供另一个可写条款正文。

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

## 全新隔离库依赖与权限

新增 `sql/bid-package-requirements.sql` 在 core、domain、bid-packages、stable-lot-identity、retrieval、worker-functions 之后、roles 之前执行。不可变表为 `bid_package_requirement_inventories`、`bid_package_requirements`、`bid_package_coverage_attempts`、`bid_package_coverage_results`；仅 `bid_package_requirement_heads` 前进更新。API 需要新表 SELECT／INSERT、仅 heads UPDATE 及新校验函数 EXECUTE，不授不可变表 UPDATE／DELETE。Worker 仅可按实际准备／完成链追加抽取绑定；不能改写资料包或清单。评分与研究角色不新增写权限。既有决定头及规则继承首次写入也由新增触发器按 bid 串行，继承路径复用已有窄权限 `lock_worker_bid`，保护原来没有当前决定的空键；任意直接 SQL 反向锁序仍可能被 PostgreSQL 判死锁而整事务回滚，不将其描述为正常路径无死锁。

真实数据库验证只通过项目 `tender-fusion` 的 Compose checks profile 运行，禁止临时独立容器及业务库。本机复用已有运行时完成纯测试 17 项，及新增源文件 ruff／mypy／bandit 检查。2026-10-19 同组 `requirements-api` 最终 20 项全部通过（22.17 秒），覆盖实际认证、CSRF、首版／追加 CAS、历史原摘要、非法 Unicode、最终提交过期零 ACK、SQL 伪造 assessment、当前决定变化、NULL／类型／安全整数／时间边界及决定空键／Worker 继承／来源新别名锁等待。测试隔离库为 `fusion_package_requirements_api`，API LOGIN 为 `fusion_package_requirements_service`，Worker LOGIN 为 `fusion_package_requirements_worker`，分别使用独立随机测试口令；结束后库及两个角色均清理。测试直接执行同一份最小权限 SQL `deploy/sql/bid-package-requirement-runtime-grants.sql`。

本轮真实执行 SQL 的 Windows 原文件 SHA256 为 `8b57eb43fda2413b2f10c2da641abbfd381eee44eb5b4ec4df147e52ae42f090`，不是 Git LF 规范字节摘要。证据保存在本地忽略目录 `.local/requirements-api-agent.xml`，12 个执行输入的原文件摘要保存在 `.local/requirements-api-agent-inputs.json`；最终测试后已逐项核对未变化。纯测试证据为 `.local/requirements-pure-agent.xml`。

本片新增的直接写入串行边界：`decision_heads` INSERT／UPDATE／DELETE 同 bid，禁止键改绑；`rule_carryovers` INSERT 复用 Worker 窄锁，原 UPDATE／DELETE 仍 append-only；`source_nodes` INSERT 获取既有 90127 图锁，原 UPDATE／DELETE 仍 append-only；`lineage_edges` INSERT 原已获取图锁，原 UPDATE／DELETE 仍 append-only。已知来源头全部需要存在且发布，最终按现有头行加锁，缺头拒绝新用。所有新增函数均为 invoker 并撤销 PUBLIC EXECUTE，不新增 Worker 业务写权限。未完成的专项包括任意直接 SQL 反向 tuple→bid 锁序死锁的零 ACK 验证、完整来源祖先／跨主体矩阵和历史坏数据读取矩阵，不将 20 项结果扩大描述为全部并发／产品验收通过。
