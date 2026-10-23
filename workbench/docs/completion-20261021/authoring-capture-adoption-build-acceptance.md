# 检查点 15：固定输入采集、正文采纳、精确构建与明确入包

本批在检查点 14 的固定整包候选生成与发布之上，接通 B1 首份输入的选择与保存、B3 候选正文的明确采纳，以及 B4 固定修订的真实 Word 构建和明确入包。输入保存、候选发布、正文采纳、文件生成和文件入包分别保留身份、回执及实际状态。

基线提交为 `e54c86cae104acb3b5edb0cfddfd15afeabdf6cb`，交付分支继续使用 `work/bid-workbench-completion-20261021`，对应草稿 [PR #1](https://github.com/zys743551828-art/tender-app/pull/1)。本批未合并、未部署、未调用付费模型。正式图文三评、历史研究工作面、项目摘要及其余完整产品验收仍按原计划推进。

## 用户可以完成的流程

1. 在「可复用任务」的新建固定整包编写模板或私有草案中，选择已有固定输入，或打开「采集新的固定编写输入」。明确选择双包修订、要求清单、已保存正文快照、章节和稳定文字节点，再选择事实、业务身份及逐条用途。核对后保存，不默认采用最新包或首条事实。
2. 将保存成功的输入用于当前模板或私有草案。继续沿用 B2 的明确手动生成、预算约束、同语义原任务复用与真实候选发布；保存输入、草案或模板本身不运行模型。
3. 打开真实候选操作卡，读取完整原稿、拟稿和目标，核对后明确采纳。界面继续检查服务端返回的新正文修订、快照与来源资格，确认确实保存了该候选才提供后续入口。
4. 打开采纳结果对应的确切稿件，浏览章节与历史。明确选择输出格式并生成文件；没有冻结目录或版式的快照使用既有内置正文模板，不隐式补入另一套排版参数。
5. 核对成功文件，再明确选择目标投标包、用途及解析范围，追加到该包的新修订。生成不自动入包，入包不自动核查，也不授予正式投递资格。

每一步丢失回执时均可恢复已经发送的原请求。界面保留原正文、原条件头与原幂等键，不通过换键、选择最新版本或重新生成来掩盖未知结果。完整操作说明见 [START-HERE](START-HERE.md)，B3/B4 组件及浏览器细节见 [前端专项验收](authoring-exact-frontend-acceptance.md)。

## B1：固定输入目录与采集工作面

新增目录读取覆盖可选择的双包、要求清单、正文快照与稳定节点、事实集及可用事实。目录只提供实际可核对的对象；保存仍使用已有 B1 原子捕获命令，核验完整来源、原件字节及当前事实用途后再提交。目录刷新不会替换用户已经选定的修订。

采集表单保留未保存输入并接入离开保护。成功 ACK 必须绑定同一项目、操作者和原请求；不可信成功响应不能清除恢复记录。保存成功后可直接供当前模板或私有草案选择。

真实 capability 响应暴露了一处旧 WIP 接线错误：`capture_available=true` 可以同时带有后续 executor 未就绪的原因。旧界面把任何 blocker 都当成不能捕获，导致合法 B1 保存入口被禁用。修正后分别核验捕获状态和执行状态，保留严格的预期协议。测试与浏览器现使用原生导出的 capability，未将其手改为空 blocker 来迁就 UI。

原生目录／保存验收为 **32 项通过、0 跳过**，运行真实 PostgreSQL 17、非 owner API 角色及本机 S3。原始 HTTP bundle 保存在 `apps/web/src/test-fixtures/authoring-input-catalog-http.json`，SHA256 为 `3bd492556e08abd7c84009ed42d3de0136b9f86b4aaa433d0c8a446dfaf6e410`。

B1 Chromium 验收覆盖 390px／1280px、浅色／深色、明确保存／丢 ACK／错误操作者三类流程，共 **12 个场景、24 张截图**。目录与 capability 重放未经改写的原生响应；POST 回执为明确标注的模拟响应，绑定界面实际请求。它证明界面与恢复行为，不冒充浏览器直接执行了数据库事务。没有页面异常、外部请求或横向溢出。

证据：[原生收据](authoring-input-catalog-native-receipt.json)、[浏览器收据](authoring-input-capture-browser-receipt.json)、[桌面采集界面](authoring-capture-desktop.png)、[手机采集界面](authoring-capture-mobile.png)。

## B3：真实候选采纳与受保护的正文资格

采纳继续使用既有 `POST /api/v1/assistant/actions/{action_id}/resolve`，由真实受保护的 action binding 判定固定整包路径。客户端无需也不能通过新增 mode 字段授予自己资格。

新的采纳依次完成只读观察、事务外原件字节核验与锁内重检，随后进入共享的 `save_draft → append_section`。 typed admission 对象本身没有授权作用；共享写边界重新核验真实 action、command、操作者、完整请求、目标 CAS、固定输入和完整拟稿。恢复旧 WIP 时发现的直接 INSERT 路径已移除。

新章节修订、来源资格、草稿 head、完整快照扩展、引用绑定、候选消费与审计记录在同一事务提交。SQL 延迟约束核验真实 job、output、publication、model-call、budget、command、action、revision 和 snapshot 链，阻止伪造消费、移除资格扩展或留下半套记录。

原 ACK 恢复先验证原请求和不可变结果，随后才考虑新业务准入。来源后来撤回或原件后来丢失不会改写已经完成的原 ACK 与历史快照。权限反例验证的是仅撤回资格表 INSERT、保留原请求及历史读取依赖时，原 ACK 与 Worker 历史仍可读取；新采纳继续拒绝。该结果不涵盖读取所需 SELECT／proof RPC EXECUTE 也被撤回的情况。相同候选换幂等键也只有一次全局消费。真实的第二轮重新捕获、发布和采纳已经验证从 r2 追加到 r3，资格绑定新的输入与实际父修订。

普通保存、恢复旧稿、目录／样式修改、批量应用和 Word 导入均不能剥离已有 exact 来源资格。当前支持纯文字稳定节点；含该类修订的草稿暂不开放普通编辑，仍可浏览章节、读取历史和恢复已经发送的原请求。需要新正文时可重新明确捕获当前快照，再生成和采纳下一轮单节点候选。资格仅证明真实候选已采纳且来源链可验证，`content_correctness_certified` 保持 `false`。

API 的 `apply_available()` 检查实际表权限和 RPC 权限。Worker 仅使用受约束的快照 proof RPC，没有获得资格表或事实表直接 SELECT，也没有取得 B3 写权限。快照 WorkContext 保留完整 manifest 与摘要，并通过 protected proof 核验新增扩展；历史读取不授予新的执行资格。

最终原生验收 **41 项通过、0 跳过，249.126 秒**；源码及 SQL 前后稳定，结束后再次比对待提交工作树仍一致，独立服务全部关闭。证据：[B3 原生收据](authoring-exact-revision-native-receipt.json)。原始采纳 HTTP fixture 的 SHA256 为 `8b83e9476e4b790c7fe6143d6de661045a301a97dbf98342287ceb3cfa232e69`，已用于最终前端协议与浏览器验证。

## B4：固定构建、真实 Word 与明确入包

构建继续复用既有 API，固定真实 draft revision、snapshot、各章节资格及完整 B1 输入。Worker 在事务外检查全部固定原件的存在、长度与 SHA256，生成真实 DOCX 并写入 S3；发布事务内重新核验来源、事实、规则、作用范围和资格。完整固定输入均进入来源链，不只保留正文恰好引用的少数证据。

入包复用现有对象字节核验和明确采用命令，并在最终提交前重查当前依据。对象 I/O 期间发生事实变化时，命令拒绝且不留下半套成员或资格记录。固定构建要求 `follow_up: "none"`，不会顺带发起核查。

混合快照按实际章节资格分流。没有 B3 资格的旧章节仍执行原有来源与结构守卫，不能借另一章的 exact 资格绕过检查。已经固定的旧 parse 不被较新的 parse 偷换。

构建历史和原 ACK 在来源后来失效后继续可读。内部历史投影仍检查不可变 proof 和真实绑定，仅允许当前 dependency digest 与历史观察不同；该模式没有作为请求参数开放，也不用于新构建或入包准入。新用途始终重新核验当前来源与事实。

B4 仅向 API／Worker 增加 packet 与 assert 两个窄 RPC 的 EXECUTE。能力检查还核验 B3 snapshot proof 的 EXECUTE；撤权后新请求与 Worker 计算明确拒绝，已完成原 ACK 仍可恢复。

最终原生验收 **14 项通过、0 跳过，116.941 秒**，包含真实 Word 内容、S3 字节、明确入包、来源／事实变化、原件损坏、混合章节守卫、旧 ACK 与历史读取，以及 RPC 撤权反例。源码及 SQL 前后稳定，独立服务全部关闭。证据：[B4 最终原生收据](authoring-exact-build-native-receipt.json)。

前端保留第 02 轮稳定运行导出的原始正向 fixture，SHA256 为 `520fac9f118dde10a1f44f352d826b9b18e525e99d0d173f657b196e5dc1017c`。其 [配套原生收据](authoring-exact-build-fixture-native-receipt.json) 为 13/13 通过；最终第 03 轮增加权限反例，正向 HTTP 契约未变。两轮随机身份分别记录，没有拼成同一次端到端会话。最终后端验收以前述 14 项收据为准。

**本轮 Word 真实成功，PDF 返回 `RENDERER_UNAVAILABLE`。** 当前受控 PDF renderer 要求既有 Docker 隔离和固定镜像证明，环境没有 Docker socket。主机 soffice 不具备该受控证明，未用它替代既有资格。界面分别显示两种格式结果，成功 Word 可以独立采用。

## 完整冻结候选验证

本候选以检查点 14 为基线，仅纳入 B1 采集、B3 采纳、B4 构建、对应 UI／契约和验收证据。正式图文 producer v2 等其他旧 WIP 未混入。源码冻结后，完整套件使用项目原有测试范围，不增加排除项。

| 验证           | 实际结果                                                                                                                  |
| -------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 完整后端       | **2,621 passed、1,731 skipped、0 failed、0 errors，129.62 秒**；4 条依赖警告，1,018 个选定源码／SQL／契约输入前后摘要一致 |
| 完整前端       | **169 个文件、1,551 项通过，51.94 秒**；567 个选定源码／脚本／配置输入前后摘要一致                                        |
| 前端静态与构建 | 改动文件 Prettier、ESLint，整项目 TypeScript，生产构建全部通过                                                            |
| Python 静态    | 41 个 Python 文件 Ruff／format，34 个实现文件 mypy／Bandit 通过                                                           |
| B1 原生        | 32 项真实 PG17／S3 通过，0 跳过，98.78 秒                                                                                 |
| B3 原生        | 41 项真实 PG17／S3／API 通过，0 跳过，249.126 秒                                                                          |
| B4 原生        | 14 项真实 PG17／S3／Worker engine 通过，0 跳过，116.941 秒                                                                |
| 最终浏览器     | B1 12 场景／24 图；B2—B4 56 场景／56 图，0 JavaScript 错误、0 外部请求、0 横向溢出                                        |
| 实际契约       | 冻结应用重新导出的完整 OpenAPI gzip 与提交快照逐字节相同；前端使用对应生成类型                                            |

专项用例与完整测试分别运行，计数不能相加；1,731 项按现有条件跳过，未计为通过。B3/B4 定向前端 96 项和 B1 的 7 项均属于完整前端范围。最终浏览器保留加载文件的运行前后指纹，提交前再次核对 B1 的 39 个、B2—B4 的 180 个文件与当前内容一致。

前端主入口为 722.95 kB、gzip 225.58 kB，既有大 chunk 与混合导入提示仍保留，没有据此宣称性能验收完成。后端保留 Starlette／AnyIO、PDFium 和 OSS SDK 的 4 条依赖警告。

完整命令、输入指纹、原生／浏览器收据摘要、失败轮次及最终比对见 [集成回归收据](authoring-capture-adoption-build-regression-receipt.json)。B3/B4 最终浏览器收据及四张代表图见 [前端专项验收](authoring-exact-frontend-acceptance.md)。

## 发现的问题与修正记录

- 原生 B1 capability 与旧 UI 假定不一致，实际响应使 3 个组件用例失败。按阶段修正协议后，改用原始 capability 复验，最终组件和浏览器通过。
- 旧 B3 WIP 存在直接写修订、SQL 触发器别名／变量冲突、过期候选误报，以及 exact manifest 不被历史读取识别的问题。已改为共享写入、受保护原子资格和准确状态检查；正向、拒绝、权限撤回与第二轮采纳都有真实数据库证据。
- B4 历史读取曾被当前依赖失效阻断。现仅对真实历史视图使用严格不可变 proof 的历史模式，新用途仍执行当前检查；原生测试验证了两类行为。
- 无固定目录／版式的快照曾被 UI 附带双模板参数，真实 API 会返回 `BUILD_TEMPLATE_SNAPSHOT_MISMATCH`。现发送原生支持的内置正文模板请求，并以原始 HTTP fixture 核验。
- 只读草稿曾影响章节导航，或让恢复路径生成新的重复 PATCH。现区分新写入、未发送本地编辑和已发送原请求，分别保留导航、输入与精确恢复。
- 首次完整后端运行因新检出目录缺少锁定 OCR 资源，出现 2 failed、14 errors；未改产品或测试。恢复项目锁定的 `eng`／`chi_sim` traineddata，并逐一核验长度与 SHA256 后，以同一源码、同一完整命令重跑得到最终通过。原失败摘要留在集成回归收据中。
- B3 曾有一轮 41 项全通过但跨越并行 B4 权限修改，源码指纹发生变化；该轮未认作最终通过。双方冻结后重新运行，取得本次稳定 41 项收据。

## 装配与复验

以下均为可选扩展，未纳入 BASE、默认 Fusion v14 或现有 v14 恢复清单。按既有基础 schema、独立 API／Worker LOGIN 与运行 grants 装配后，顺序为：

1. `authoring-package-inputs.sql`。
2. `assistant.sql` → `live-facts.sql` → `intent-budget.sql`。
3. `authoring-package-jobs.sql`。
4. `authoring-exact-revisions.sql`。
5. `authoring-exact-builds.sql`。

每个扩展继续遵守原依赖和权限检查。缺少安装、权限或外部服务时能力明确不可用；业务进程不能借用 owner 权限补齐。

原生复验入口在 `workbench` 下执行，PG 必须包含 uuid-ossp 与 vector，S3 使用指定本机测试二进制：

```sh
.venv/bin/python -m deploy.authoring_input_catalog_acceptance \
  --pg-bin /tmp/tender-review-f06/pg17/bin \
  --weed /tmp/tender-completion-runtime/seaweedfs-4.48/weed \
  --receipt /tmp/authoring-input-catalog-recheck.json

.venv/bin/python -m deploy.authoring_exact_revision_acceptance \
  --pg-bin /tmp/tender-review-f06/pg17/bin \
  --weed /tmp/tender-completion-runtime/seaweedfs-4.48/weed \
  --receipt /tmp/authoring-exact-revision-recheck.json \
  --fixture-dir /tmp/authoring-exact-revision-recheck-fixtures

.venv/bin/python -m deploy.authoring_exact_build_acceptance \
  --pg-bin /tmp/tender-review-f06/pg17/bin \
  --weed /tmp/tender-completion-runtime/seaweedfs-4.48/weed \
  --receipt /tmp/authoring-exact-build-recheck.json \
  --fixture-dir /tmp/authoring-exact-build-recheck-fixtures
```

## 证据边界与剩余条件

原生验收运行真实 PG、API、非 owner 角色、Worker engine 和 S3；Worker 从真实 outbox 消息直接执行，本批没有另外启动 Kafka broker 验证消息运输。源文件、解析／提取完成事实和模型结果为明确合成资料，模型使用 MockTransport，付费调用为 0。浏览器运行真实组件和 Chromium，但使用明确的原生响应重放与故障模拟，不能替代真实数据库竞争、解析质量或供应商效果验收。

当前仅支持纯文字稳定节点的固定整包采纳，普通编辑的来源继承仍未开放。PDF 受控转换、真实标书内容及排版、正式评分和投递条件、目标环境长期运行及完整 F00—F14 仍需各自验收。本批证据关闭的是上述软件接线与恢复缺口，不授予业务正确性或完整产品完成资格。
