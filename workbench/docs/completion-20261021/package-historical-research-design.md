# F06-06/07/08：整包历史准入与隔离评估设计

状态：独立增量已通过 28 项纯逻辑、17 项真实 PostgreSQL 机制测试（10 项核心、6 项 HTTP／分组、1 项真实租约过期，分别记录收据）。查询守卫补充为五个 GET 拒绝重复及未知参数，已覆盖 14 种实际 HTTP 反例；SQL、CPU 协议与事务重放顺序未变。主应用现已挂强制公开守卫；独立可选反向曝光桥接通过13项实际旧路径/并发/公开入口PG验收。完整共同守卫未安装时公开core统一503，原生两SQL只可作为独立机制路径验证。本增量不修改已冻结范围、资格、执行或费用对账协议，不执行旧 `retrospective-research.sql`。

## 1. 合格定义与证明边界

严格历史候选必须同时绑定原生技术范围、确切材料包修订、实际提交记录及其不可变 binding、投标主体／工程／标段／轮次、完整原件字节和确切解析、所有祖先来源、已核验官方技术标签、独立权威满分与明示聚合、当时的存在／本方取得／发布／生效事实。0 是有据数值；未知、仅综合分和未知聚合均拒绝。当前入库、解析或补充确认时间单独保留，不回填历史。

新证明接入层是一种可配置适配机制，不改变这些条件。第一适配器验证有来源的 Ed25519 签名证据包：签名只证明来源身份和声明完整性；不自行证明声明为真，也不证明完整图文或必要范围。每项事实必须同时给出来源定位、原始证据字节摘要、原件摘要、被证明的内容范围及具体时间语义。真实配置须由部署方确认来源能够证明对应事实；普通 API 不能配置来源或写入核验回执。未来可接档案、平台回执或经审证据核验适配器；不把所有实际证明限定为本签名格式。

图文/范围证明与历史时间证明分开：前者绑定完整物理页、原件、确切解析及必要条款到技术子范围的映射；后者绑定原始字节在历史边界前存在、本方已取得及依据有效的证据。解析 coverage=complete、人工勾选、文件名旧日期或今天生成的 PDF 均不能替代。

本批只建立历史研究候选和独立 CPU 基线评估；不授事前预测、在线误差、正式训练样本、正式模型认证或业务路由资格。先前 package-score-execution 的 mechanism_test 结果不进入此增量。

## 2. 原生数据绑定

`package_historical_research.native_context(scope, submission, outcome)` 从数据库读取并重核以下对象，所有选择均按明确 ID，禁止 latest 解析或伪造 body：

| 对象 | 固定身份／检查 |
| --- | --- |
| 技术范围 | scope ID/digest、原 manifest、inventory ID/digest、全条款选择与所有技术 part |
| 实交 | 当前 native package submission head、submission binding digest、同包／authority／inventory／完整 identity |
| 原件与解析 | 每个成员原件及祖先的 ID/hash/size；scope 中确切 parse ID、每页、文本／表格／视觉记录和几何摘要 |
| 来源 | 完整祖先闭包、用途、原件 digest、来源 head revision/status/有效期；事后 label/summary/cache 不能进入内容侧 |
| 官方标签 | 同一实交的当前 outcome head + verified decision + 全原件/引文/来源证明；score_kind=technical_total，数值和满分有界 |
| 满分与聚合 | 引文必须来自同一 authority 原件的确切 evidence；整段显式技术总满分及量尺；支持的原始最终技术分聚合语义明确，不反推评委分项 |

完整 context 以规范 JSON 摘要冻结。以后每次证明登记、准入、实验冻结和 Worker 读写均重核。旧当前范围可以比历史实际提交晚冻结，只能在额外历史证据足够时成为现在建立的回溯候选，绝不把它变为当时预测。

## 3. 独立 SQL 与接口

新增 `deploy/sql/package-historical-admission.sql` 和后续 `deploy/sql/package-historical-research.sql`，可选、全新数据库初始化；默认 BASE 不安装。依赖完整 BASE（含 native package scopes）和 `model-governance.sql`。不依赖旧 WIP 回溯 SQL或单正文历史输入。

核心表均在新 namespace：`adapters`、`adapter_revocations`、`proofs`、`admissions`、`admission_keys`、`protocols`、`cohorts`、`members`、`exports`、`jobs`、`results`、`predictions`、`exposures`、`exposure_members`。证据、准入、冻结、结果和暴露均 append-only；租约/状态有独立受控 RPC。不存在普通业务角色可写的 confirmed/eligible 开关。

| RPC | 权限和输入 |
| --- | --- |
| `admission_context(scope, submission, outcome)` | API，只读明确缺口与已选择来源；不写样本 |
| `verification_material(scope, submission, outcome, adapter)` | 专用 verifier，仅返回确切核验上下文和所选适配器公开参数 |
| `record_proof(scope, submission, outcome, adapter, envelope, normalized, expected_context_digest)` | 专用 verifier，保存原证据、签名及已核验回执；SQL 重核完整原生绑定 |
| `admit(proof, actor, command)` | API，引用既有证明 ID；重核来源、当前标签和适配器；不得接受客户端资格布尔 |
| `freeze_cohort(protocol, split_at, label_cutoff, selections, actor, command)` | API，服务端 training_frozen_at；全库相关组闭包，整组跨界排除 |
| `start_job(cohort, kind, actor, command)` | API，只创建独立 CPU 任务；evaluate 的预测由已冻结训练模型派生 |
| `claim_job/read_training/finish_job` | 专用 train LOGIN + generation/fence/lease |
| `claim_job/open_final/read_final/finish_job` | 专用 evaluate LOGIN；先固定预测，提交不可撤销 exposure，再读取 final 标签 |
| `renew_job/control_job` | 用途角色续租，API 暂停／恢复代次控制；任何失效事实禁新用 |

HTTP 独立挂载：native saved scope 下独立 `/historical-admission-context` 和 `/historical-admissions`；实验 `/package-historical-research/...`。证明导入仅专用 CLI，不暴露签名配置或机制证明上传 UI。

## 4. 时间、相关组和标签隔离

冻结四个时点：逐样本 `historical_as_of=actual submitted_at`、显式 `submission_split_at`、显式 `label_available_as_of`、服务端 `training_frozen_at`。当前签发／核验时间保持当前；历史事实必须来自独立证据字段及其来源。标签实际可得晚于截止的成员明示排除。

项目相同、任一相同目标原件、证明中有据模板/近重复关系形成相关闭包；计算覆盖所有已登记候选，而非只看选中的成员。组跨实交边界则整组排除；同组不能分到 fit/development/calibration/final。新增相关候选或关系会使原冻结闭包失效。更正前后不能成为两份独立标签。

训练导出只含 fit/development/calibration 标签，final 只有 ID/分组等必要预测元数据；原件、证明、官方页、聊天、检索、缓存和 API 凭据不进入 CPU Worker。独立 evaluate 进程仅在预测固定、exposure 事务已经提交后读取 final 标签。旧 model_governance 的项目／正文 exposure 同样参加防洗白检查。

## 5. 本批 CPU 正向路径与明确剩余

第一条可运行路径为严格冻结的项目等权 mean/median 基线选择：fit 产生候选，development 选择，固定后为 final 派生预测，独立 evaluate 复用现有 `statistics`/`evaluation` 的边界检查、归一化误差、分组区间与覆盖统计。数据划分和来源不因数值结果变化。不能用不存在的三判断特征补零来冒充线性校准。

原生整包三判断到可监督特征的真实生产资格、ridge 等特征校准、最终业务门槛签发、观察发布/回退和真实独立质量验收仍须分别接线；缺少时显式 unavailable。本批的基线评估可验证隔离机制，不代表 F06-08 全部完成。

## 6. 隔离验收

合成适配器只能在独立 `fusion_package_history_mechanism_*` 数据库、匹配 OID 的 owner 初始化记录和专用角色中工作；专用 test API 才能建立合成候选。所有合成准入/评估固定 `research_only=true`、`formal_eligibility=unavailable`，不写旧 samples、在线 metrics、正式模型或路由。

正向：实际非 owner API 建立原生 scope/submission/verified outcome；真正的 Ed25519 验签与原证据 hash 检查；专用 verifier 登记；API 准入；冻结多相关组；独立 train/evaluate 子进程和已提交 exposure；报告保留真实0。负例：跨主体/lot/round/包/范围/实交、原件/解析/祖先变动、今转换冒充旧字节、未来/未知时点、漏页/漏条款、综合分/unknown、未知聚合、标签更正、跨边界组、训练读 final、暴露后重选、源撤回、并发陈旧租约和混合角色。

验证仅用可重建合成证据，不上传私有材料、不调用付费模型、不伪造真实样本数量或质量结论。

## 7. 当前验证与运维边界

实际 HTTP 收据为 `/tmp/tender-review-current/package-historical-research-http.json`，包含原生 scope 的 context/ETag、官方 0 分准入、协议、四时点 cohort、暂停/恢复和 CPU 评估。所有材料、签名来源语义和图像均为明确合成输入，收据不含凭据或私钥。

真实 LOGIN 验证了 API、verifier、train、evaluate 各自权限；train 不能直接读 proofs、native context、官方原件/标签源、final 导出或 evaluate RPC。BASE-only HTTP 返回 `schema_configured=false` 和具体未配置缺口，写请求返回 503。原件撤回、主体/标段/轮次变化和官方更正使新用途失效；已经完成的报告及原 0 分保留只读。

核验进程使用 `requirements-package-history.txt` 的独立依赖（含 Pillow），0600 profile 只含一个专用 DSN。CPU 入口为 `python -I deploy/package_history_worker.py --purpose train|evaluate --profile <private-file> --job-id <exact-id> --generation <n>`；verifier 使用明确 scope/submission/outcome/adapter ID 和私有证据文件。固定入口真实执行一次 owned job，具有独立 heartbeat、generation/fence、120 秒租约与重复完成保护；本批没有另行部署自动轮询或 Kafka 调度器。

反向桥接见 `package-history-exposure-bridge-design.md` 及对应acceptance。该独立SQL现已通过实际旧API/Worker、并发栅栏和生产公开挂载验收；两SQL自身仍不保证旧路径读取原生exposure。公开入口强制核对完整bridge真实函数/触发器/ACL契约，缺安装或漂移503，目录元数据不授资格。
