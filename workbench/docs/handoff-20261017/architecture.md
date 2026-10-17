# 架构独立审查交接

当前已静止：不再新增review、创建资源、运行DB/Docker/消费者或调用外部模型/对象。此文件供接手者找回精确输入、结论及未闭合问题；历史设计/开发/QA证据各自保持原字节。用户要求整理全部工作提交GitHub，由PM统一收口提交，本架构角色不另行推送。

## 不可更改的基线

全新建设，无旧系统迁移；历史标书/官方成绩是新资料入库。Kafka+Python Worker，PostgreSQL17+pgvector1024维RAG。正式评分仍须干净输入、完整相关章节、三次独立有效判断；聊天RAG片段不能替代完整评分范围。满分/预算/渲染/模型资格互相独立，登记满分或执行成功不能授正式评分资格。

主设计在tender-docs产品PRD/全新技术方案/详细技术设计，历史检查与原失败不能改写成当前系统已验收。禁止在旧检查库热补DDL或用owner执行业务探针；新SQL先具体静审，再由PM新fresh并用非owner实测。

## 当前可引用的精确放行

| 输入 | 精确SHA256 | 本架构结论与证据边界 |
|---|---|---|
| 统一应用02 candidate | `18b173dd1496994c180ef6c4bd16e8a1a05679e2020255c5a9b7e08d36479061` | 432固定源前后匹配。独立11检查：6静态、2真实非owner PG/登录ASGI生命周期、2A2/Scale组合、1本人AC01原场景。AC01闭合；不授模型/正式评分或完整生产验收。 |
| 统一02 final recipe / actual | `fed95aadb107fb0765a4f76353cbfb42c58c877e0c14503fd62bab38354e7a2a` / `b65141d0db4afd51317e51a919c1582337bd260d858c27bfbeadc0b5c3cf9ab2` | 227路径/258操作/406 Schema；373旧Schema未变，BuildRequest/AuthoringSnapshot按A2有意扩展。17自动response模型核形状，241人工投影不冒全自动响应验证。 |
| 单目标恢复协议03 / driver03 | `db7abef9a5b6ee4ead27a6506953696c557af47ea52bf2b84b5c15f597d96e7c` / `bfaf841ae77cc01313dc95cfcff2ed007205c690d41860981b577cbecef22665` | 仅nonce最小静态修正和5个提取纯函数合成正反例通过；不是实际恢复通过。资源UUID/DB/LOGIN/systemID独立，marker绑定封存源plan和唯一控制行hash。**此旧driver总GET超出后来7GET授权，当前不能直接执行。** |
| OPS05恢复代码 | `6436b14fbd0bd9278f6ae70bea10b1ee4d7e7e2faebda140dd77421d8def052a` | 只允许唯一CHECK四元组的两条完整表达式pair，其他定义ACL/owner严格。本人14离线检查通过；实际恢复见下节，非本人执行。 |
| 分母SQL C | `e771ab52c25cbd19ac0e48f5732de051c2f8f5ecc7b6599a0f7064826b169195` | 静态可另fresh。strict方法来自cohort→research_run→experiment，B修的当前confirmed决定真实事前时间保留。尚无本人C实际PG/应用验收。 |
| 章节导航01 | `390c428faee2afbe088e7b8397647a7bced4f5ea0ab6bac148fb72c8a0f9e14e` | 本人16实际小PDFium机制通过，直接Dest/首标题/印刷页码/三轮固定点。不是新RICH DOCX→PDF、通用PDF安全或完整视觉验收。 |

统一02报告：[统一应用组合02增量架构复核](/workspace/tender-docs/04-验证与测试/application-composition-architect-review/candidate-02/统一应用组合02增量架构复核.md)，最终记录SHA `250b8da9c50e6774b6bd848348c695983c62601776e4b50d3a377d2afcf8184b`。01原AC01真实PG反例与夹具重复失败XML保留，不覆盖。

nonce报告：[单目标恢复标记编排增量复核](/workspace/tender-docs/04-验证与测试/application-recovery-architect-review/single-target-nonce03/单目标恢复标记编排增量复核.md)。导航、分母C报告分别在 `/workspace/tender-docs/04-验证与测试/authoring-page-navigation-architect-review/candidate-01/` 与 `/workspace/tender-docs/04-验证与测试/score-denominator-architect-review/sql-C/`。

## 当前阻塞与证据类型

| 问题 | 冻结输入 | 具体证据和修复条件 |
|---|---|---|
| RP01 / P2 图片可见完整误判 | RICH static01 `e2f15d90940acb10e31cfb85331d22844cce47575fd12855cfb8821d9d08fa31`，350固定输入 | **本人实际合成PDFium反例**：120×90白底数字9原嵌PNG不变，白矩形盖数字，全图均值误差0.4仍complete；实际crop非白像素54→0。58原离线全过但不覆盖稀疏内容。Owner已接受static02局部/前景保护与新profile；02尚未收到。不是沙箱逃逸，但01不授图片完整/M1资格。 |
| AB01 / P1 核清NULL可清零未知费用 | 助手预算SQL02 `ea53f1fe28afefea9fc81c0ad0b71f6c3ef8c9e804994521d71f2aef64b34403` | **纯SQL三值逻辑反模型，未PG**。decision/proof_reference/proof_sha=NULL、amount0令IF=UNKNOWN跳过，终态native可落settled0/manualfalse。需必填显式NULL拒绝和合法组合，不得仅trusted admin掩盖。 |
| AB02 / P1 预留与native方法/输出上限未绑定 | 同SQL02 | **静态关系/金额反模型，未PG/API**。按2048预留，global run/call8192仍满足dispatch读到的state/lease条件；预算2148、native最坏8292而限额5000。缺精确profile/model/price/max_tokens/step身份关系；须发送前RPC重核，不以usage事后超界替代。 |
| 当前有据目标身份守卫缺口 | 同SQL02 assistant_check_target | **静态读集观察，未PG**。只current facthead/confirmed/value/evidenceIDs，不核live evidence_basis/确认basis或source撤回。保持查询读集不变仅撤回源，函数结果不变。API受理和Worker发送前必须同短事务权威桥闭合，不能宽授Worker事实读权；需明确90129与bid/op/graph统一锁序。尚未收到Owner修订稿/闭合证明。 |
| H04 / P1 管理员能力组继承业务权限 | helper04 `bc414d201b48c7a7ada62478c53c7d975c840ce4aee217b247b08f9ecd78e869` | **静态角色图反模型，未PG**。既有NOLOGIN预算组可继承tender_api且六危险flag全false；新LOGIN继承组即获得业务权限，现verify只flags/owner会放过。PM确认helper05尚未实现，04原件保留。须拒非预期上游membership并核新LOGIN exact closure/effective禁止权限，全部通过才写配置。 |

RP01目录 `/workspace/tender-docs/04-验证与测试/authoring-rich-port-architect-review/static-01/` 含脚本、两实际PDF/PNG、检测JSON、独立渲染JSON及完整报告。350源前后hash匹配；本轮没有Docker/DB/云/大树复制，测试用-B/无cache。

预算报告与反模型：[助手预算SQL02静审](/workspace/tender-docs/04-验证与测试/assistant-budget-architect-review/sql02/助手预算SQL02静审.md)，同目录observed.sql/countermodels.py/json/authority-readset-observation.json。helper静态记录：[预算管理员初始化工具04静态阻塞记录](/workspace/tender-docs/04-验证与测试/fresh-bootstrap-architect-review/helper04/预算管理员初始化工具04静态阻塞记录.md)。**预算SQL02不fresh，helper04新增管理员不放行；不能借用户真实测试授权越过这些缺陷。**

## OPS实际状态及限定授权

开发Owner完整限定串行演练已报告通过，结果SHA `9176380c0083fc479354a819b9221db370783392c8ccb9ee898282ce2d59c3ab`，证据索引 `5533e3df11748a2e6ce74b67e37b9257184ca93d368b5eba6291e8f6b14d206d`：164表、7目标对象、暂停API及原source卷重启一致。该结论来自Owner，本架构角色只放过代码/协议与离线机制，没有亲自重做2集群。

独立QA第一次实际新target恢复164 TABLE DATA后正确被marker身份guard拒绝，原执行UUID误用为archive nonce；0云写，精确自有容器清理，失败卷/收据保留。修正03源marker绑定已静审，但后来包含对象上传的恢复驱动被自动审批拒绝，拒绝记录必须保留，不重试/绕过。

用户随后明确授权**这一次限定测试**：仅7个自建合成对象合计322B，专属新prefix，最多7PUT+7GET；unknown停止，不碰其他对象。旧driver03在archive.restore内部已有7GET，又追加7独立GET，共14GET，不能用原静审放行执行。**新限次driver尚待冻结和具体审查；交接优先暂停。** DB-only/no-egress协议草案和原拒绝保留，不能把DB-only改成云拒绝的绕过路径。

单目标方案身份是immutable archive→1新target，不新建/重启/挂源卷；启动1536MiB、阶段256MiB，原full1600/create900不变。容量不足或无PM独占Docker窗口为NO-GO。任何PM停放自有Seaweed模拟器是另行受控动作，要完整保配置/卷/数据和精确恢复命令，不由架构方案隐含批准。限定驱动通过前不执行新恢复。cleanup只核准自有container，保卷/对象/档案，不能删除冻结证据凑空间。

OPS仍只固定07/308源+15SQL，不含最新A2/Score/Scale组合；不授生产RPO/RTO、断电恢复、在途队列/上传续跑、真实业务非空sealed模型资格。

## 既有模块结论及待审队列

- A2 PAGE02 candidate `5cb2bd6f9c205bace488158d3b9656222b3e9a54aa215d1c6bf2d834f11773e9`：本架构结构复核+实际已有7页产物读回，独立QA4项真实PG/ASGI/registered engine/无网Docker结果 `bcaa389af2ef55c3577d9dbb550adf7ab172d27ec0ee01a0ba976cec7aa67ac0`。统一02仅重新验证OOXML/engine组合，未重做PAGE Docker。TOC/章末精确范围与RICH不从PAGE02自动继承。
- 外来Word03 `b12e2e456ead217296510ae6fde3f7747198d75adffe42706bb3692c28406fa6` 全部动态域含合法PAGE/TOC仍保守拒转。W04默认clock_timestamp与主桥接 `9b609a89975c31ab945aacbbe8f63639edd37d51b622ee92c788146270cd7168` 已有相应独立边界；不得为RICH内部PAGE放宽外来Word。
- Score应用01 `32893b6df6fe1d6f0b5485bb3191aa8b4987fee8d690d4062b842d206ba3f9e7` 沿用SQL F `28e9a2f5042e29078c24a20d2191ada9935034b745627e8b1a5c865b487ec5be`，组合/能力不授numeric/formal。独立完整实际评分质量及最终业务闭环不由本架构静审替代。分母C后续新fresh/最终应用候选待实际验证；B库开发结果不能冒C。
- TechnicalScale应用01 `9ad9becd41065d334ff03246026da4f9a79f90db89a5aa0696b3a0ada01c6f62` /SQL C `ba5bd56c4ae03628cfac01d085cf8eb10fa95b094d3d554f2e866db10bb5dfad`，原TS01祖先集合矛盾已静态闭合。统一02仅配置与“不授评分集成”实际检查，不能冒新增分母/聚合已接。
- HISTproof02 `c69aaf845c23db74b794a4e2b20e3bf78a9bf86a9d3d12202fdd5ca33ee91876`：原RR重放缺口已本人实际PG复验；HistoricalInput01 `3d917c3190eca381e43d647bbf7a29422faebb1653605a45784a0a76e10fba45`本人静态/纯机制与其他QA范围分开，归档独立研究不放宽current_review。
- 助手预算SQL03（修02问题）、helper05、RICH static02及RICH资产/API/Worker完整接线、限次恢复driver：**尚未本架构完成精确复审**。接手时先取新candidate/SHA和原始失败映射，不能从口头“已改”放行。
- 新导航虽已16小PDF测试，真实LO若输出GoTo action/丢named目标仍partial；表格PDF几何始终TABLE_PDF_GEOMETRY_UNVERIFIED，图片局部遮盖须RP01修复。完整M1人工成稿/浏览器及最终组合生产验收仍待独立证明。

本架构证据中没有新浏览器验收；真实PG/ASGI、实际小PDFium、离线SQL三值/关系/角色图模型、开发Owner收据和QA证据已在各节区分。后续不要把纯图反模型写成已连接PG越权，也不要把静态可fresh写成业务通过。
