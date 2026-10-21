# F11 固定整包章节任务：输入、发布、采用与构建设计

状态：**设计，尚未实现或验收**。本文件独立于已冻结的章节任务切片 A；不改变 A 的 `legacy_section_and_source_versions` 语义，也不把已有 `source_version_ids` 路径计为固定整包能力。

目标是一条完整领域流程：**明确选择整包与草稿章节 → 保存不可变输入 → 原生生成候选 → 发布可审阅建议 → 人工确认并产生绑定来源资格的章节修订 → 基于该修订构建 → 明确采用新文件至包修订**。输入生产者只是第一个检查点。首轮仅支持手动、单章节、一个明确节点的建议；事件、定时、多章节批次及任意外部来源扩展后续单列。

## 1. 已查明的接线边界

下面均为现有代码事实；这些端口可以提供基础设施或比较逻辑，不能未经分支处理就成为新模式的输入生产者。

| 当前入口                                                                | 当前行为                                                                             | 新模式必须处理的边界                                                          |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| `packages/tasks/inputs.py::capture`                                     | 读取当前正文、材料、规则、事实、章节头，并按时间取最新解析                           | 新模式在进入此函数前明确分派；禁止把 package ID 降成版本列表后进入旧捕获      |
| `packages/authoring/generation.py::freeze_generation_plan`              | 按版本取最新解析；读取当前规则与事实；限制来源数量、证据数量和正文长度               | 新生产者只从显式修订及解析读取完整输入；超出容量明确阻断，不切前若干项        |
| `packages/assistant/jobs.py::queue_generation`                          | 调用旧计划、当前 `project_memory` 与当前业务身份解析                                 | 新模式有独立接受函数；复用原生账本和队列，不能复用其动态上下文拼装            |
| `packages/assistant/context.py::project_memory`                         | 当前规则、事实、问题，部分列表最多 100 项                                            | 不作为整包模型输入；完整冻结上下文及精确引用单独持久化                        |
| `packages/assistant/intent_identity.py`、`budget.py`                    | 从当前确认事实推导业务身份、检查独立性、复用与费用义务                               | 从显式事实快照构造同一业务身份；当前数据只作拒绝式复核，不替换冻结事实        |
| `packages/assistant/sql/live-facts.sql::assistant_assert_job_authority` | 预算预留及发送时调用 `assistant_assert_live_fact`，其 SQL 要求最新解析和当前材料集合 | 新 SQL 以真实 exact job 绑定选择独立核验分支；保留旧守卫，不能绕过预算 RPC    |
| `packages/assistant/coordinator.py::publish`                            | 比较当前记忆、调用旧生成接受器并写提案                                               | 先识别严格新模式，再进入独立发布栅栏；旧分支保持原行为                        |
| `packages/authoring/patches.py::apply_proposal`                         | 当前事实、规则、最新解析和当前章节来源检查                                           | 新提案类型有独立采用入口与不可剥离的整包绑定                                  |
| `packages/authoring/repository.py::save_draft/append_section`           | 采用后仍两次调用旧 `assert_sources`；快照还读取结构、图片与版式依据                  | 来源资格必须绑定实际新 `section_revision`；不能在提案入口检查一次后跳过保存层 |
| `packages/authoring/build_repository.py::freeze_build/publish_build`    | 每章调用旧来源守卫；结构、图片再次检查                                               | 从固定快照读取逐修订来源模式；不能在构建时重新解释为最新解析                  |
| `packages/authoring/package_outputs.py`                                 | 校验实际构建、输出、快照、原件；当前资格仍调用旧章节/结构守卫                        | 保留构建与字节证明，增加 exact 修订资格核验分支，再显式采用至包               |

特别是 `assistant_assert_job_authority` 和 `append_section` 两处：只改 Python 生成入口，会留下真实数据库拒绝或错误回退，因此它们属于必要接线，不能留作“以后兼容”。

## 2. 首轮产品语义和不支持状态

第一版采用一个明确关系：`draft_using_package_context`，即“使用所选固定整包为所选草稿章节生成建议”。草稿章节与包内文件不天然一一对应，不能从当前草稿、文件名或包成员顺序推断这种关系。只有另有真实构建及快照回执证明时，未来才可展示“该章节属于包内生成正文”。

所选投标包、依据包均完整进入上下文；修改对象只有明确选择的草稿快照中的单章节点。采用提案只追加草稿修订，不改原包、原文件、当前正文指针或提交记录。构建输出随后仍通过现有明确采用动作创建新包修订，不能自动切包或自动提交。

| 阶段                | 用户可见能力                                               | 必须明确阻止的行为                                                   | 阶段完成标准                                                   |
| ------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------- |
| B1 独立输入生产者   | 保存、查看、分页选择固定输入；查看来源、事实声明和阻断理由 | 生成、发布、采用、构建均不可据该记录启动；提示执行器尚未接通         | 真实数据库和原件存储的输入往返、串号及竞态用例通过             |
| B2 原生候选发布     | 手动任务绑定 B1 输入；执行原生 job；查看发布建议和站内通知 | 建议不可通过旧提案、旧批次或手动保存入口应用；显示“采用资格尚未接通” | 原生队列、HTTP 模型桩、发布事务及费用/取消反例通过             |
| B3 修订绑定采用资格 | 明确确认 exact 提案，追加带不可变来源资格的新章节修订      | 未接通的构建、结构修改、富文本变更等必须明确拒绝，不能回退旧来源解析 | 新修订、资格、消费、快照原子写入；旧入口不能剥离绑定           |
| B4 后续构建与包采用 | 从固定快照生成实际文件，发布后明确采用至新包修订           | 不自动更新原包、不把技术成功解释为语义正确或可直接投标               | 实际文件字节、构建原生回执、来源失效、输出资格与包采用闭环通过 |

能力返回分别提供 `capture_available`、`generation_available`、`publication_available`、`apply_available`、`build_available` 和稳定的 `blocking_reasons`。B2 的任务成功仅表示“建议已发布”；采用和构建有独立状态，不能用一个绿色完成状态覆盖整条流程。F11 的该领域流程须到 B4 才可计入完成。

## 3. 新请求：只收精确选择，不收客户端准入证明

拟新增 `POST /api/v1/bids/{bid_id}/authoring/package-inputs`。下面是字段草案，尖括号均为说明占位符，不是可执行请求：

```json
{
  "protocol": "package-authoring-input-request/1",
  "purpose": "authoring",
  "target_relation": "draft_using_package_context",
  "package_context": {
    "target": {
      "package_id": "<uuid>",
      "revision_id": "<uuid>",
      "manifest_digest": "<sha256>"
    },
    "authority": {
      "package_id": "<uuid>",
      "revision_id": "<uuid>",
      "manifest_digest": "<sha256>"
    },
    "inventory": {
      "id": "<uuid>",
      "digest": "<sha256>",
      "rule_set_id": "<uuid>"
    }
  },
  "target_section": {
    "draft_id": "<uuid>",
    "snapshot_id": "<uuid>",
    "snapshot_digest": "<sha256>",
    "base_draft_revision": 1,
    "section_id": "<uuid>",
    "section_revision_id": "<uuid>",
    "base_section_revision": 1,
    "section_digest": "<sha256>",
    "schema_digest": "<sha256>",
    "node_id": "<stable-node-id>",
    "before_node_digest": "<sha256>"
  },
  "facts": {
    "fact_set_id": "<uuid>",
    "fact_head_revision": 1,
    "identity_fact_ids": ["<five explicit fact ids>"],
    "uses": [
      {
        "fact_id": "<uuid>",
        "fact_item_digest": "<sha256>",
        "subject": { "kind": "bidder", "id": "<uuid>" },
        "reason": "<why this fact applies to this chapter>"
      }
    ]
  }
}
```

服务端按严格 schema 拒绝多余字段和重复身份，核对所有摘要与实际关系。`fact_head_revision` 是客户端明确选择的前置条件，不能在请求内省略后自动填当前值。五项身份事实对应既有业务身份：采购人、工程、标段、轮次、投标主体编号；必须在显式事实集中唯一且有有效确认依据。业务事实使用声明可为空，但不表示事实齐全或不需要事实。

初版事实用途单独为 `authoring`。现有 `package-fact-usage`、`selected-fact-admission` 的协议用途是 `prebid_compliance`，不能改字段名后当作编写准入。复用其精确来源、确认依据和范围比较原理，新增 authoring 声明契约。声明记录操作者、命令、主体、事实内容与证明摘要；声明本身不证明事实真实，仍必须核验原确认、原页证据、当前效力和主体范围。初版所有被消费的事实证据及章节既有引用须能在所选两个包的明确成员与解析中闭合，超出者明确阻断，不补当前项目资料。

模板只保存已存在的输入引用：

```json
{
  "task_kind": "chapter_suggestion",
  "section_id": "<same target section>",
  "instructions": "<explicit task instructions>",
  "source_selection": {
    "mode": "exact_package_authoring",
    "input": {
      "authoring_input_id": "<uuid>",
      "authoring_input_digest": "<sha256>"
    }
  },
  "trigger": { "mode": "manual", "cron": null, "timezone": "Asia/Shanghai" }
}
```

输入记录冻结上下文；模板版本冻结指令；原生编写计划再绑定两者。这样同一精确上下文可以配不同明确指令，但不会悄悄改动旧任务的指令。所有 UI 先展示所选输入，禁止从 `version_ids`、当前包或最新解析生成替代引用。B1/B2 不扩展 `exact_package_trigger` 的现有否决核查语义。

## 4. 不可变身份与内容

拟定义 `package-authoring-input/1`，其摘要覆盖以下内容。关系 ID 和数据摘要均须保存：只有摘要不能证明跨表归属，只有 ID 不能证明实际内容。

| 身份层     | 必须冻结的内容                                                                                                    | 复用基础与边界                                                                                        |
| ---------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| 业务主体   | 工程、标段、轮次、bid、投标主体及确认状态；身份快照、五项事实与确认依据；规范业务关联键                           | 复用 `intent_identity.association_key` 规范；读取指定事实，不调用动态 `project_identity` 组成模型输入 |
| 两个完整包 | 包 ID、修订 ID、manifest digest、类型、成员顺序、逻辑成员 ID、版本、源类别、用途、完整 parts 和物理页范围         | 复用 `bid_packages` 值对象和精确修订仓库；共享附件及重复物理文件仍保留各逻辑成员                      |
| 每个解析   | parse ID、parser/config/evidence digest、文档 SHA/大小、完整 pages、每块 ID/页码/顺序/类型/文本摘要和精确几何身份 | 复用 `bid_package_review_documents.read_member` 的精确读取及 `read_parse_identity`，不得选择最新解析  |
| 要求       | 原生清单 ID/digest、规则集、所有清单条目及文本、来源锚点、原生抽取操作/回执/范围摘要、人工更正链及有效性证明      | `package_inventory_proof` 只能证明抽取范围与回执，不能冒充语义无遗漏证明                              |
| 事实       | 显式事实集/修订、选用事实 ID、精确值表示、单位/主体/范围、当前确认 ID、basis/沿用链、原页锚点、authoring 范围声明 | 保存原 `value::text` 与证明原文摘要，避免浮点或 JSON 重编码造成“相同”误判                             |
| 章节       | draft/snapshot/section/revision 的完整关系、内容与 schema 摘要、目标稳定节点及 before digest、快照中章节列表      | 显式快照读取；当前章节头仅用于 CAS，不能用于替换目标                                                  |
| 结构与资源 | 固定结构版本、章节计划、目录/版式模板版本、相关图片版本及正规化/导入证明、所有引用闭包                            | 结构/图片未实现 exact 支持时明确不支持；不能把 rich 或导入来源静默抹掉                                |
| 来源与时点 | 直接来源及所有祖先 ID/修订/关系/摘要、用途政策、状态、known_at/有效区间、观测时点、原件核验信息                   | 来源撤回和自然到期是当前失效条件；输入的历史内容不因此被覆盖                                          |
| 方法       | 输入契约、资格政策、内容/schema 与输出政策、提示词构造器/实现指纹、完整性与容量政策                               | 方法变化须重新核对，不以旧输入直接替换新 profile                                                      |

生成正文成员另核验实际 `build → build_input → draft_snapshot → outputs → publication receipt → document bytes` 关系。`package_outputs.capture/verify_bytes` 可提供此证据；其当前资格检查仍含旧守卫，须由目的明确的 exact 分支处理，不能简单传 `check_generated=False` 当作准入。

完整整包意味着所选成员、逻辑范围、全部物理页和可用证据均被保留。不能只用 RAG 命中、前 100 条记忆、前 500 块或前 30 份文件后仍称完整。B1 可保存完整证据并报告容量；B2 仅在整个模型输入能被实际配置的模型/预算容量容纳时开放。超限返回具体计数和容量阻断，不自动抽样。后续若需要分批，必须另做全量覆盖账本和明确依赖计划。

正文数据与几何数据采用两个明确编码层：业务 manifest 继续使用既有规范摘要；原解析证据摘要使用现有数据库算法及其精确文本，不能把 PostgreSQL numeric 转为浮点再重算。模型输入另保存其实际发送字节的 SHA256。所有 schema 均拒绝重复键、NaN/Infinity 及不完整字段。

## 5. 持久化及数据库守卫

建议增加独立 SQL 文件，按阶段加载，不放宽旧 manual/trigger 守卫。

| 新记录                              | 作用与必要约束                                                                                                              |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `authoring_package_inputs`          | append-only 的上下文 manifest、证据原文/摘要、输入摘要、方法、actor/command/时点；bid 与所有父记录具复合归属约束            |
| `authoring_package_fact_scopes`     | 初始 bind 及后续 withdraw 事件，绑定 input ID、事实内容/证明、主体与 actor/command；有序前驱摘要，撤回即失效，不更新旧声明  |
| `authoring_package_job_bindings`    | 原生 job、operation、writing plan、输入 ID/digest、指令/模板摘要、原生与父命令；原子写入并由延迟约束核对实际 ACK/审计       |
| `authoring_package_action_bindings` | 已发布候选、原 job/output/plan/input、action payload SHA 与目标基础修订；不能只复制 action payload 来伪造资格               |
| `authoring_exact_section_bindings`  | 每个采用后真实 section_revision 的来源资格；含内容/schema/引用摘要、原 action/job/input、父修订及资格方法；和修订同事务写入 |

输入和声明可以在同事务预分配 ID，并用延迟外键校验双向关系。避免循环摘要：声明绑定输入 ID 与独立 `basis_digest`；最终 input digest 再覆盖声明摘要，声明不回填最终 input digest。撤回只追加事件，不让历史输入重算摘要。

SQL 校验至少包括：完整字段集合、模式、bid/轮次/主体、真实父子关系、输入/计划/输出摘要、命令 actor/target/request digest、成功 ACK 及审计一一对应、事实声明前驱、原生 handler/step/fence，以及不得利用旧配置绕过 exact 绑定。数据库验证关系和数据一致性；原件字节实际核验由受控服务执行，不能宣称 SQL 自身已读取对象存储。

Worker 不获得 API 角色凭据或事实表全量读权。新增受限制的 `SECURITY DEFINER` 核验入口，以实际 job ID 与 lease/fence 查绑定，只返回核验结果，固定 `search_path=pg_catalog,design` 并撤销 PUBLIC 执行权。任意客户端 JSON、ready 标志或 HTTP receipt 均不构成入队/发送许可。

## 6. 四段事务栅栏

### B1：冻结输入

1. 在只读 REPEATABLE READ 中按全部显式 ID 捕获包、解析、清单、事实、章节及来源证明。核验当前目标仍与所选快照一致，但不读取当前内容替代原内容。
2. 关闭数据库事务，读取全部原件与已纳入的导入/图片字节，校验 SHA256、长度和真实对象关系。
3. 新开只读快照重新观察并比较；只有纯观测时间允许按明确规则排除。任何事实、章节、来源、结构、规则或身份差异都要求重选/重确认。
4. 在 READ COMMITTED 下完成原命令幂等判定、最终授权与加锁复核，再一次写入 input、事实声明及审计。失败不留下可选择的半份输入。

锁序沿用共同入口的 bid 互斥，再按既有顺序锁目标、来源图/有序祖先和预算；不得引入“持有预算锁再等待 bid/来源”的反序。B1 无预算锁。具体锁序须与 `assistant_assert_job_authority`、草稿保存及来源撤回同时做真实并发用例，而非只凭 Python 顺序推定无死锁。对象存储 I/O 始终在事务之外。

### B2：接受、执行和发布

接受时再次核验 B1 输入、事实声明和所有目标；模板暂停/关闭、版本改变、输入失效直接阻断。将新 task、原生编写计划、job、operation、预算义务与双向绑定在一个事务内提交。丢 ACK 返回原命令结果；换 HTTP key 不重复创建相同执行。

保留原 `authoring-generate/1` handler、`authoring-generate` step 与 `authoring.generate/1` 计费调用键。新增严格 `generation_mode=exact_package_authoring/1` 和独立 payload/schema 分派，在旧 `_patch_set_mode` 之前处理；未知或不完整模式直接拒绝。此选择保留 `intent-budget.sql` 中原 handler/attempt/fence 约束，避免为新名称拓宽费用身份。新输入生产者不调用旧 `queue_generation`，但复用其原生 queue/ledger 的受约束基础设施。

Worker 在 reserve 前、发送前分别核验 exact 绑定、活跃任务、闭包来源和固定事实/章节/规则。`assistant_assert_job_authority` 增加只对真实 `authoring_package_job_bindings` 生效的分支；旧 `assistant_assert_live_fact` 分支完整保留。新分支比较明确 parse/member 和当前效力，不能按 latest/current_material 重新填充输入。Provider HTTP 在事务之外，调用结果或费用未知不得重发。

Worker `succeeded` 仍只是 candidate-ready。发布器在新的完整事务内核验原 input/plan/output 和当前依赖，结构化输出必须引用冻结 evidence ID，保持目标节点 ID 和 before 摘要。写提案、publication、action binding、action link 及审计原子提交；发布中途故障整体回滚，重投不创建第二提案。

数据库不能撤销已被远端接收的 HTTP。最后一次发送栅栏提交后到网络接收之间仍有外部 I/O 窗口；晚到的取消或来源变化必须阻断发布/采用并按真实账本结算，不能宣称已经免费撤回。

### B3：确认并产生修订来源资格

新提案 payload 使用独立 `kind=package_authoring_patch`，保留助手现有 `authoring.apply_patch` 业务工具名及独立绑定。旧 `apply_proposal` 已拒绝非 `authoring_patch`，不能通过旧入口误用；助手 resolve 和新专用采用 API 只在实际 exact binding 存在时进入新采用器。B2 未启用采用器时两个入口都明确返回尚未支持。

采用要求真实 published job/action link、未过期、未消费、请求 digest、固定输入、当前来源/事实/规则资格、目标 draft/section CAS 同时匹配。在同一事务内追加新 section_revision、exact qualification、draft snapshot、action consumption 和审计。不得先保存章节再补资格，也不能让客户端传 `skip_source_check`、`exact=true` 或任意 proof 字典绕过旧守卫。

`repository.append_section` 通过服务端可信的类型化准入对象进入独立 exact 来源验证器；旧调用没有此对象，继续旧校验。数据库再核验新修订与资格一一对应。`freeze` 与 `snapshot_content` 保留每个真实修订的来源模式和资格摘要；缺失 exact binding 时整份快照不可当 legacy 继续。

后续普通编辑、恢复章节、结构移动、批次建议都必须先识别当前修订的实际 binding。首轮对未接通的操作返回 `AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED`，允许读取和保留草稿；不能把引用复制为普通旧章节。支持普通文字编辑时，可创建显式继承的来源资格，但新修订标明人工编辑且不继承“模型已生成/已审阅”结论；新增引用、规则、结构或资源必须重新取得适配资格。B3 验收明确列出实际支持的操作，不宣称所有编辑器功能都已兼容。

### B4：构建、发布与包采用

构建按显式 snapshot ID 读取每个 section_revision 的真实模式。legacy 章使用原守卫；exact 章使用该修订的固定 package/parse/rule/fact/asset 资格。混合快照逐章验证；不能为了有一章 exact 而关闭其他章的校验。

`freeze_build` 将逐修订 qualification digest、实际 snapshot、结构/图片/版式身份和渲染配置加入 build input。计算阶段只读这些固定内容；发布阶段重新核验相同资格和当前来源效力。文件写入成功但发布失效时保留实际计算记录，不注册可采用输出。

`package_outputs` 的 capture/current/observe 路径验证 build manifest 中的 exact binding。随后 `package_adoptions.adopt` 仍执行实际字节核验、包头 ETag、最终来源复核和明确 append-member；同文件可追加新包修订，但不改老包。通过包审阅输入再次读该生成成员时，资格仍可追溯到实际新章节修订，不能绕回当前草稿重建证明。

结构计划、版式和图片来源属于构建依据，必须同样有精确资格。首轮可限定为现有纯文本稳定节点；如果实际章节/快照含尚未支持的富文本、图片或导入依赖，应在 B1 报不支持，而不是到构建时静默丢弃。扩大支持范围作为独立带测试的后续切片。

## 7. 哪些变化使输入失效

| 变化                                     | 处理                                                                              |
| ---------------------------------------- | --------------------------------------------------------------------------------- |
| 同一文档又生成另一条 parse               | 不改所选 parse，不把最新 parse 当作新正文；所选原解析及其来源资格仍有效时可继续   |
| 包出现新修订                             | 不切换选择；显示仍使用原明确修订。若其来源/要求已被真实撤回或效力声明改变，则阻断 |
| 所选事实的确认、范围声明、证明或主体变化 | 原输入不变，本次使用失效。初版事实头变更采用保守失效，不偷偷映射新事实 ID         |
| 规则及清单更正/有效性改变                | 原抽取回执保留；当前使用失效，要求选新清单/重新冻结；不能改用 current_rule_set    |
| 目标章节、draft、结构或已纳入资源改变    | 当前任务/候选不得写入；按阶段显示 stale 或 CAS 冲突                               |
| 来源撤回、祖先改变或自然到期             | 新发送、发布、采用及构建发布分别阻断；历史结果仍可读                              |
| 模板暂停、修改或项目关闭                 | 不启动新任务；已生成结果按当前发布/采用约束处置，历史通知继续可核对               |
| 模型/方法/容量政策变化                   | 旧输入可读；若执行所需方法不匹配则显式不可执行，不静默换模型/截断内容             |

所有比较均区分历史内容与当前使用资格。历史发布记录不因后续失效而改写为从未发生；UI 另显示当前能否采用、能否构建。

## 8. 费用、复用、取消与通知

新模式继续使用业务用途 `section_draft`，不另造一个能够避开既有费用义务的 purpose。费用关联仍由证据确认的工程/标段/轮次/主体与真实章节目标确定；包、模板、输入记录、request key、模型配置的新 ID 都不能证明业务独立。对不同章节但同内容的已有未知费用守卫也须保留。

区分三类摘要：固定上下文摘要、原生计划/模型输入摘要、粗粒度费用关联键。前两者保证实际输入与复用；第三者保证换包装不能重发未核清调用。同上下文、指令、目标与执行方法的重投复用原 job/result；初版不开放 `rerun=true`。真正新调用须另有原有预算政策允许的明确新意图，不能由换 key 获得。

取消使用原 operation/step lease 与 fence，已有 HTTP 未知状态进入原 reconciliation 流程，不为了取消而伪造“未收费”。候选尚未发布为 `awaiting_publication`；published、stale、failed、cancelled、unknown fee 投影沿用 A 的真实终态原则，新结果用独立 `task-package-authoring-result/1`，不扩大 A 的 legacy scope 枚举。

通知绑定实际 job、publication、action、结果摘要及原任务版本。重复消息、丢 ACK、旧错误成功通知不能抑制正确终态；采用/构建另有领域结果，不把“候选已发布”通知误写成“文件已完成”。对话自动化保持现有独立语义。

## 9. 必须具有的原生正反例

每阶段使用全新临时 PG17、真实 API/Worker 角色、真实命令/队列/回执；原件测试使用本机 S3 兼容存储，模型使用受控 HTTP 桩，外部付费调用为 0。测试必须标明合成业务数据，不能据此声称生成质量或真实投标相关性已达标。

| 阶段 | 核心正例                                                                                    | 核心反例/故障注入                                                                                                                                               |
| ---- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1   | 两包多成员、多物理页、共享逻辑附件、指定旧 parse、原件及事实证明成功冻结                    | 新 parse 诱导、跨项目/轮次/主体、错误 section revision、漏页/漏块/重复身份、geometry 摘要篡改、原件字节错误、事实声明撤回、IO 后并发变更                        |
| B2   | 精确输入→原生命令/job/plan/operation→HTTP 桩→候选→publication；旧 latest 函数设为抛错仍成功 | 自造 binding/ACK、剥离 mode、篡改模型 payload、预算 SQL 接错分支、unknown fee 换 key/模板/包仍阻断、发送前撤回/取消、重复 Worker 和丢 ACK、publication 中途回滚 |
| B3   | 明确确认产生新修订及 qualification；重复确认返回原消费                                      | 旧 apply、旧批次、手动 save、恢复章节绕过；action/job/input 串号；目标修改/事实更新/来源到期；修订写入后资格失败全回滚；缺失 binding 不能视作 legacy            |
| B4   | 真正构建 DOCX，若选择 PDF 则走实际受控渲染；发布→下载字节→明确采用新包→再读取证明           | 构建期间来源/事实失效、旧 snapshot 与新资格混用、剥离 build manifest binding、富文本未支持、包头竞争、PDF 关系缺失、生成输出复读时偷偷改用 latest               |

并发重点：关闭/撤回与发送、发布、采用、构建发布分别竞争；同输入两个请求竞争；普通保存与 exact 采用竞争；input/qualification 被合法角色直接伪造的 SQL 反例。Worker 不应因新增模式获得业务写权或明文事实全库读权。

最终真实闭环必须覆盖 **旧 parse 在新 parse 已存在时仍被精确消费 → 发布 → exact 修订 → 实际构建 → 新包成员复读**。只通过输入生产者测试不足以证明该流程可用。

## 10. 文件分工及最小旧文件接线

以下新文件为建议名称，尚未创建。按阶段独立提交，不在一次大改里假定四段都已完成。

| 阶段 | 新模块/文件建议                                                                                                                                                                                                                             | 需要改动的最小旧接线                                                                                                                                                                                                            |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1   | `packages/authoring/package_input.py`、`package_input_repository.py`、`package_admission.py`、`package_input_contracts.py`；`packages/contracts/sql/authoring-package-inputs.sql`；`apps/api/authoring_package_inputs.py`；专用 PG/存储测试 | 根的 `apps/api/main.py`、`packages/domain/schema_plan.py`、契约生成器与预览 schema 版本；必要时只抽取精确文档/证明纯读 helper，不改旧 review 用途                                                                               |
| B2   | `packages/authoring/package_generation.py`、`package_publication.py`；`packages/tasks/package_authoring_runs.py`、`package_authoring_result.py`；`packages/contracts/sql/authoring-package-execution.sql`                                   | `tasks/models.py`、`inputs.py`、`runs.py`、`runner.py`；`assistant/generation.py`、`budget.py`、`authority.py`、`coordinator.py`；新 SQL 替换 `assistant_assert_job_authority` 的明确分支；任务表单/卡片/协议验证与原生结果路由 |
| B3   | `packages/authoring/package_proposals.py`、`exact_sources.py`；`packages/contracts/sql/authoring-exact-revisions.sql`；专用采用 API                                                                                                         | `authoring/repository.py`、`snapshot_structure.py`、`section_sources.py`；`assistant/actions.py`；旧 `patches.py`/`batch_patches.py`/`structure_repository.py`/恢复入口增加服务器实际 binding 检测，未支持者拒绝；新提案 UI     |
| B4   | `packages/authoring/exact_build.py` 与实际构建/采用端到端验收脚本                                                                                                                                                                           | `authoring/build_repository.py`、`snapshot_structure.py`、`package_outputs.py`；按实需接 `rich_snapshots.py`/`format_bindings.py`，未支持内容在 B1 拒绝；包采用模块只增加必要的资格分派                                         |

`assistant/paid_execution.py` 的模型调用、账本结算和重试逻辑原则上无需改变；新资格由现有 `assert_source_guards` 及预算权威入口调用。`assistant/intent_identity.py` 的规范化函数可只读复用，新的精确目标适配写入独立模块；不得为调用方便而新增可传入任意 prepared target 的通用绕过参数。

根统一负责 BASE 顺序、主应用路由、OpenAPI/shared contracts、操作/幂等清理注册、恢复比较及预览版本。新增 SQL 进入恢复清单后必须做当前 schema 的真实 PG+S3 往返；新函数定义若导致 pg_dump/reparse 差异，应提交逐字段、逐字符串的明确证据，不增加通用 SQL 规范化白名单。

### 建议立即实施的检查点

从 B1 开始，同时预留 B2/B3/B4 的明确能力状态与输入身份。B1 的首个可审查交付包含：严格请求/不可变记录、完整两包精确证据、authoring 事实范围声明、目标快照关系、原件双观察栅栏和 PG/S3 正反例。根审定上述目标关系、事实用途和数据库边界后，顺序实施 B2、B3、B4，不因 B1 验收通过就停止领域流程。

本设计没有创建新任务、调用模型、改写 A 文件或启动任何服务。既有 A 的 20 个冻结路径与验收收据保持独立。
