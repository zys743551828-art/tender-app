# 2026-10-17 项目交接：先读此文件

本交接是用户要求的工作检查点，**不是最终交付或上线验收**。所有未提交源码、WIP、固定候选、方案、失败反例和待办一并保留。先核对本目录各角色交接与 `publication-inventory.json`，再继续工作；不要从旧 README 的首个 PDF 切片误判当前能力。

## 仓库与路径

- 当前全新系统源码：`zys743551828-art/tender-app` 的 **`workbench/`**。该仓库根下原 `backend/`、`frontend/`、`deploy/` 为历史实现证据，不是当前新系统启动基线。新系统不承接旧库或旧模型资格。
- 产品、架构、详细设计、实施任务板与绝大多数验证：`zys743551828-art/tender-docs`。
- `tender-design`、`tender-research`、`tender-datasets`：原设计、研究与资料清单，继续保留各自历史证据，不把旧证据改写成当前已验证。
- 本次各仓库工作检查点使用 `handoff/2026-10-17` 分支。最终提交回执见文档仓库 `00-项目管理/交接-20261017/`；不要只克隆 main。
- 原工作区绝对路径为 `/workspace/tender-workbench`、`/workspace/tender-docs` 等。恢复精确候选时推荐保留该路径：源码可克隆到 `/workspace/tender-app` 后用软链接 `/workspace/tender-workbench -> /workspace/tender-app/workbench`。清单中原始绝对路径保持不变；不得批量替换冻结证据后冒称原 SHA 相同。

## 必须保留的用户决策

1. 全新 AI 投标工作台，没有旧系统迁移、双系统、旧库映射或旧模型资格承接需求。
2. Kafka 与独立 Python Worker；不以 Celery/RabbitMQ 配置作为基线。
3. PG17+pgvector，RAG 包含解析、分块、Embedding、向量+词法、重排、证据引用和撤回失效。正式评分使用干净白名单、完整相关章节、三次有效独立判断，不能用普通聊天片段替代。
4. 产品融合 GovDash 的项目/章节工作区与原有风险优先、原文证据、版本闭环长处。产品 Owner 维护产品方案；开发/架构/测试/用户独立评审；PM 对整体交付负责。
5. 机制测试、显式 Mock、真实模型效果、真实官方标签精度、生产运行验收分别记录；不得互相替代。
6. 用户授权团队持续完成项目；本次新指令是整理并提交 GitHub交接，已通知各角色停止继续扩展开发并保存现状。

## 主记录阅读顺序

在文档仓库依次读：

1. `02-业务与产品/AI投标工作台PRD.md`。
2. `05-技术与设计/AI投标工作台全新系统技术方案.md`、`AI投标工作台详细技术设计.md`。
3. `00-项目管理/团队协作与质量准则.md`、`实施任务板.md`。
4. `04-验证与测试/a1-delivery-plan/current-implementation-review/产品交付评审与排期.md`、`remaining-fr.json`、`A2完整成稿交接.md`、`助手未知费用下独立新问题协议.md`。
5. 本目录六份角色交接、`BACKLOG.json`、`RUNTIME_AND_PRIVATE_STATE.md`。

产品主记录最后已知 SHA `16f776ef3115f9bace2ff7cf63bfff6652770199c4432e72965bb1369a693297`，变更链见任务板同目录 `产品主记录变更-20261017-score-increment.json`。40FR仍有未完成项；54需求/128场景的静态追踪通过，不是完整软件通过。

## 目前可依赖的结果

| 范围 | 当前结果 | 不能推导的结论 |
| --- | --- | --- |
| A1/资料、生命周期、报价、RAG/指标 | F05固定310源在8808，actual3249…161路径/188操作；报价不取整和知识V1历史刷新等独立反例已修并复验 | 不是新统一组合已部署，亦非真实模型质量 |
| 统一应用02 | `18b173dd1496994c180ef6c4bd16e8a1a05679e2020255c5a9b7e08d36479061`，432源；actual`b65141d0db4afd51317e51a919c1582337bd260d858c27bfbeadc0b5c3cf9ab2`，227路径/258操作/406Schema；AC01强ETag等11独立架构项通过 | 尚无新native API/普通Worker/整包浏览器放行 |
| Word主桥接 | 原件保存、受限转换、采用与手工PDF接续等11独立QA+5架构；外来Word全部活动域保守拒绝，原W01/W03反例保留 | 不代表DOCX结构导入、复杂Word保真或TOC支持 |
| Word声明/保留原件增量03 | 第二会话声明投影、禁止补PDF借已有版本；开发发现同SHA第二批次503并整改，当前最终冻结/验证状态以development.md为准 | 不能把原503覆盖、用不同随机文件规避，或提前标已native部署 |
| A2 PAGE02 | `5cb2bd6f…`：独立真实8页、1..8页脚、正文数字守恒及取消/迟到/撤回通过 | RICH、目录实页、章页范围、结构导入与M1整包尚未完成 |
| RICH | 已有资产与快照PG/API组件、静态writer/render端口；RP01稀疏图片遮挡误complete真实反例，02整改状态见authoring.md | 原58纯项与组件4项不能代替实际RICH转换/版面资格 |
| 助手/任务/前端11 | 317源夹具05、explicit Mock/local对象；任务05及长会话U10-01关闭；独立一次新项目问题经MockWorker/publisher/刷新通过 | 不代表真实供应商、通用NL任务、通知调度运输全通过 |
| 前端12 | Word/树/计划/双模板新增已实现，145测试及质量通过；随后9项声明投影delta通过，最终状态见frontend.md | 未冻结/未走新8818+5186原生浏览器的部分不得称完整通过 |
| 历史输入/模型治理/评分执行 | HIST02、HistoricalInput01、StageA、Release01、Score01等各有独立机制结果；正式评分完整范围三判断等12项为hard Mock | 无真实官方资料/精度/正式cert资格 |
| TechnicalScale | 祖先闭包权威01独立10项、实际Word→PDF→解析及撤回验证 | 主组合存在资源API不等于评分分母已可用 |
| 分母C | `e771ab52c25cbd19ac0e48f5732de051c2f8f5ecc7b6599a0f7064826b169195`已静审；B新库5项PG/API已过；C新库脚本已准备未执行 | 禁止在B既有库补执行C；回溯/label scale/严格资格仍待 |
| 应用恢复 | code05开发串行源→目标→源复验通过164表+catalog/ACL+7合成对象322B；独立QA原nonce错误被正确守卫拒绝 | 不代表独立QA最终通过、最新全schema恢复、生产RPO/RTO |

## 现在必须先解决的阻塞

- 助手预算 SQL02 `ea53f1fe28afefea9fc81c0ad0b71f6c3ef8c9e804994521d71f2aef64b34403`：核清RPC NULL三值逻辑可将unknown洗成settled/0；AB02/P1还发现2048预留可与8192 native输出上限脱钩，须在发送前绑定profile/model/price/max_tokens/step；项目五编号依据/来源资格另有审查问题。SQL未执行，03/WIP状态见Owner交接。
- Fresh helper04 `bc414d201b48c7a7ada62478c53c7d975c840ce4aee217b247b08f9ecd78e869`：47纯检查及质量过，但架构独立发现NOLOGIN预算组可继承API组越权；**04不可执行**。下一05须验证组上游闭包、LOGIN精确membership及effective业务禁止；05尚未实现。当前源码是04，不能把moving source当通过基线。
- RICH RP01/P2：遮盖稀疏数字却误完整，须复验02并明确表格几何仍未验证。禁止复用PAGE资格放宽外来Word。
- 新统一native环境未创建；03 Word冻结、架构复核和资源串行窗口完成后再启动。旧8808与助手夹具8816保持固定。

## 费用与云操作的精确授权

- 自动审批此前拒绝真实付费评审常驻消费者，因未明确项目/次数/预算；原两调用/0.05美元估计请求仍未获答复。本次**没有新增真实模型调用授权**，禁止启动付费review/assistant/research消费者或绕过拒绝。
- 用户刚明确授权**一次**独立恢复：tender-base桶，固定 `workbench-checks/7f9f160a-9154-48fd-8ac8-f33e9ce5337c/recovery-qa/`，7个逐字证明为自建合成的对象，共322B，最多7PUT+7GET，unknown即停，不LIST/DELETE/改桶设置/传DB或其他档案。材料SHA`8a54340e8c2321cba4ddfc8c2189526c3d5c0811c220b8655403a76cff2706ea`。
- 原driver存在额外7GET和动态前缀，**不能按新授权直接执行**。QA正在新最小driver增加固定前缀/SDK实际调用计数硬门；本次交接指令后已停止启动attempt，须读testing.md核其冻结/待审状态及授权是否已消耗。此前审批拒绝和0副作用证据原样保留。
- bucket CORS变更曾被拒绝；已用同源代理，勿重复申请/修改。

## 接手第一小时

1. 克隆相同检查点分支的仓库，核publication inventory和各候选SHA；阅读所有角色交接，分清moving source、固定候选、运行实例。
2. 检查私有状态/模型缓存/DB与Docker卷是否仍在原环境。GitHub包含源码、设计和可公开的合成验证证据；密钥/成员口令/运行DB与私有归档未上传，详见私有状态交接说明，不能宣称仅clone即可原样接续全部运行实例。
3. 不重跑未批准SQL，不清库，不格式化Kafka，不回收未知容器/卷，不删除失败证据。源码/配置/identity检查应在首个副作用之前。
4. 分配Owner并按BACKLOG依赖恢复：独立恢复限次driver审查→单目标窗口；Word03架构→clean19SQL/native联调；RICH02架构→受限实际转换；助手SQL03/helper05审查→fresh专有角色+hardMock；分母Cfresh→研究后续。
5. 资源窗口约32GiB磁盘，必须串行Docker/大build/复制。OPS初始1536MiB/阶段256MiB门不能降低。新Kafka19098仅为腾空间park了可重建binary cache，数据/config保留，恢复方法见运行说明。

## 如何验收本次交接

本次交接只核文件完整性、秘密排除、角色收口和GitHub远端提交可回读，不重新运行全部付费或外部机制。已有测试按具体证据继承；失败、skip和WIP不改为通过。任何遗漏/敏感文件隔离在发布清单中明示，不静默删掉本地原件。
