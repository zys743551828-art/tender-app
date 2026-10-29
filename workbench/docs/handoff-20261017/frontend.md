# 前端无损交接 · 2026-10-17

当前静止点：**11已冻结并经独立用户复验；12是已实现主要界面的WIP，未最终冻结、未在新原生环境走浏览器。** 用户改为优先整理GitHub交接后，前端已停止开发、build、测试及复制产物；不等待资源窗口占槽。不得把下列源码/机制检查写成Word/A2整包或生产验收通过。

工程根：`/workspace/tender-workbench/apps/web`。本文件在仓库 `docs/handoff-20261017/frontend.md`。下面的 `apps/web/...` 均相对仓库根。截图、独立用户报告仅引用原路径，不搬大树、不包含账号、Cookie、票据、私有profile、用户原件或模型密钥。

## 1. 候选、真实环境与证据层次

| 前端 | 精确manifest SHA-256 | 真实运行/资产关系 | 实际契约与后续证据 |
| --- | --- | --- | --- |
| 08 | `31c298b5c905744e58be5345ef4077794e4941c350aed0811e8cd8750fc0c623` | 固定08原生Origin `http://127.0.0.1:5178` → API8808，后端先F04再F05；112源/215资产。不是用07旧界面代替修复。 | actual `3249fec969b04a3bc298bfd77a2f0dda7d1a4f3a1f1213a1a8d6648db6998fe7`，161路径/188操作。开发102 tests；独立F05最低比值法真实登记→试算→保存A/B→刷新/旧方案/dirty/开关/390通过。均值全边界、真人和整FR不因此通过。 |
| 09 | `1ff95626d95bcc7ebc1c6230d339e99cec5766077d64a121c664236491e98621` | 固定资产服务5179；浏览器保留Origin5176，**只将非API资产overlay为09**，API/OSS仍原8806。不能称09独立同源部署。112源/215资产。 | 同08的actual `3249fec…`，知识普通知识历史version入URL、刷新/返回/前进及bid/trace/citation保留通过；指定非法版本404不回退最新。 |
| 10 | `d1be8aa67adfa75adaf7f904efcc626b720e5931b694adec8fca115126af3aee` | 最终为原生Origin5184 → 固定task05 API8816，128源/215资产；早期8808无费控制面自查曾用开发资产overlay，不能与最终原生证据混写。10旧进程后来被11准确替换，固定文件保留。 | actual `4af4b5d611539485be74aeed8b98f07d95fb4bc4e9c16572a781f219e5877ae2`，164/193/325；task04与05契约同字节。完整助手/任务的软件机制与显式Mock隔离设施，不代表真实provider质量或Kafka验收。 |
| 11 | `af1a992ec7539c465b873abd04bcc87e4bbc89901962f2f6c283e395ef8629e5` | **当前原生Origin5184 → API8816固定task05**，130源/215资产。开发阶段11资产overlay记录单列，最终native结果无overlay/HMR。 | 与10同actual `4af4b5d…`。独立用户U10-01已关闭：6组只读＋1次项目turn/1次显式Mock/2条持久消息，刷新可读；结束control还原hold。 |
| 12 | **无最终candidate manifest或最终SHA** | 计划新Origin5186 → API8818，**尚未启动/未做native浏览器**。主源码是WIP；main `dist`是较早02构建，**不匹配当前03/UX WIP**，不可直接当12最终包部署。 | 02正式统一基线 actual `b65141d0db4afd51317e51a919c1582337bd260d858c27bfbeadc0b5c3cf9ab2`（227/258/406）；当前types临时从Word声明03 actual `c2ac41880bfd60c183df3228d22c9c3c9881eb15226d26e818c027e850fb523f`（227/258/407）生成，必须等PM最终组合绑定。 |

候选源与资产清单位于：

- `apps/web/qa-previews/pricing-method-08/frontend-candidate.json`
- `apps/web/qa-previews/knowledge-version-09/frontend-candidate.json`、`contract-binding.json`、`history-live-result.json`、`开发自查说明.md`
- `apps/web/qa-previews/assistant-task-10/frontend-candidate.json`、`HANDOFF.md`、`assistant-mock-browser-result.json`、`tasks-browser-result.json`、`assistant-live-result.json`、`cold-runtime-binding.json`
- `apps/web/qa-previews/assistant-continuation-11/frontend-candidate.json`、`HANDOFF.md`、`development-browser-result.json`、`native-browser-result.json`、`cold-runtime-binding.json`

11运行绑定文件SHA：`d2f9bf39ad8613918398c10139bef3b622d522ad0c79b84fe4a7ae004deb41df`。08—11清单中的“待独立验收”等状态是冻结当时记录，后续独立通过另有报告，不改写旧manifest。

独立报告及截图原位置（本次不复制）：

- `/workspace/tender-docs/04-验证与测试/implementation-user-review/pricing-f05/报价用户闭环复验.md`、`result.json`
- `/workspace/tender-docs/04-验证与测试/implementation-user-review/knowledge09-delta/知识历史版本修复复验.md`、`result.json`
- `/workspace/tender-docs/04-验证与测试/implementation-user-review/assistant-task10/助手与任务前端10独立用户复验.md`及同目录截图/结果
- `/workspace/tender-docs/04-验证与测试/implementation-user-review/assistant-continuation11/前端11长会话整改与独立发送复验.md`、`final-result.json`、`independent-delta01-result.json`、`independent-project-positive03-result.json`、`final-readback01-result.json`

这些外部报告如需在另一台机器复核，应由PM按整体证据交接清单保留；只克隆前端源码不能恢复私有数据库、原件存储、会话账本或浏览器未发送草稿。

## 2. 12保存状态与源码边界

只读WIP盘点：`docs/handoff-20261017/frontend12-wip-state.json`，SHA **`f37e1c071add9ea2b3308c73fb936c98d53d0dab9e55aac4f95be76af7c65e6e`**。146个当前源码输入，较11改变33个文件；源码树摘要 **`48b6c3bbdd3de3e927a7e167eea49fb5a6e9dcff261238fe611bd5c51ef15b91`**。这是交接时WIP盘点，**不是冻结候选**，没有复制frozen-inputs/frozen-dist。

源码ownership仅`apps/web`及自身自测/说明。本轮按PM新指令额外写本交接目录。没有修改backend、worker、domain、deploy、packages/contracts、冻结08/09/10/11或旧`tender-app`。08的两个PricingFormulaEditor文件及09的Knowledge核心已在02契约核查时逐SHA保持；11的130源/215资产在交接盘点中再次全部核验。

主要新增/修改：

- Word：`src/uploadFormats.ts`、`uploadTransport.ts`、`Project.tsx`、`ProjectWorkspace.tsx`、`WordOriginals.tsx`、`DocumentRelationNotice.tsx`、`Evidence.tsx`、`ArtifactActions.tsx`及相关测试。PDF/DOCX分格式链；单传媒体类型正确；分片/完成请求原body、tag、key恢复保留。合法文件校验后才创建批次，空文件不制造空批次。
- A2：`src/AuthoringStructure.tsx`、`authoringStructureState.ts`、`AuthoringPlan.tsx`、`AuthoringTemplateEditor.tsx`、`AuthoringFormatBindings.tsx`、`AuthoringPanel.tsx`、`AuthoringReferences.tsx`、`AuthoringBuilds.tsx`及测试。树稳定ID、预览/一次应用、删除影响、历史恢复；计划双CAS；双模板版本、保存与匹配；格式字段真实来源；固定快照构建。
- 恢复：`src/useRecordedCommand.ts`增加相应member作用域清理。目录/计划/模板输入按成员及对象在sessionStorage保留；请求恢复沿原意图，不把“保存版本”变成“另存家族”。
- 生成器：`scripts/generate-contracts.py`新增仅实际已用schema roots。递归`AuthoringJsonValue`用等价TS索引签名生成，避免`Record`递归别名被TypeScript拒绝；未修改实际schema。`src/contracts.ts`当前文件头指向外部临时03 artifact。
- 样式、说明：`src/styles.css`、`README.md`、`.prettierignore`；目录调整折叠、原件/技术身份在详情、移动端“继续编写本章”可聚焦正文。

本轮停止前最后两处轻量源码尚待恢复时定向核对：计划412后同时显示服务器计划与保留输入；目录名称/上级/位置/类型表单跨刷新保留并标出已变化的上级。不能拿之前145全测当这两处最新字节的最终检查。

## 3. 已做检查、原失败及未做项

`apps/web/qa-previews/word-authoring-12/`保留原日志，未覆盖失败为通过：

| 记录 | 实际范围 |
| --- | --- |
| `all-tests-final-pre-native.log` | **145 tests / 36 files通过**。早于最新03投影与最后轻量UX调整，不能宣称最终12全测已完成。 |
| `word-declaration03-tests.log` | **9项delta通过**：Word卡3、声明绑定2、原项目4；新GET约束、禁止旧PDF链、原件/转换分状态。 |
| `word03-final-affected-tests.log` | 后续10项通过，增加空文件不建批次反例；仍是受影响机制测试，不是原生OSS/Word浏览器链。 |
| `final-03-delta-tests.log` | 15项树/计划/模板/格式/Word/绑定机制通过。 |
| `format-check-pass02.log`、`lint-pass02.log`、`typecheck-pass02.log`、`build-pass02.log` | 02阶段通过；build3.42秒。产物早于后续03/UX源码，必须重建。 |
| `typecheck-03-pass02.log`、`lint-03-pass02.log`、`typecheck-03-latest.log` | 部分03源码增量通过；不是最终12质量总门。 |
| `contracts-verify-application02.log`、`generator-lint.log`、`generator-format.log` | 02实际契约精确重生、11冻结/08报价/09知识原字节保持、生成器检查。03最终组合仍待核差。 |

保留的首失败包括：递归类型被TS拒绝后修生成器；测试夹具给出不完整材料/模板投影导致异常/NaN警告后修夹具；测试fixture不完整`DocumentView`被build类型检查拒绝后改为组件实际所需的generated类型Pick；格式漏项；空文件测试在项目未加载前找input导致定位失败后加真实就绪等待。11早期ENOSPC日志仍在11目录，未删除旧资产换“通过”。

**没有12 native浏览器、实际DOCX上传/转换/采用、真实双模板双格式取件的前端通过证据；没有真实模型、收费评审、研究、助手运行或新容器。** 本轮只有离线合成测试文件（不到4KB）在12自测目录，未上传/转换；不复制到本交接文档，也不是用户原件。

## 4. Word03投影与不可放宽的语义

临时artifact：`docs/word-pdf-declaration-development-checks/actual-03.openapi.json`。PM已明确c2ac只作临时实际契约，后端最终freeze/组合/native窗口仍待。

`UploadView.word_pdf_declaration`为**可选、nullable、readOnly**；新GET upload/批次投影总应返回null或对象，旧成功Command ACK可能没有新增字段，原字节必须保留。对象含精确Word版本、原role、`required_target_kind=new_file`、`relation_kind=user_declared_same_draft`、`verification_status=unverified`。这处理本系统不可变命令历史，不是旧系统迁移。

前端按新GET约束恢复：声明PDF不提供旧逻辑PDF新版本选项；绑定前再读GET上传，缺字段不推断为无声明；已声明仍选旧目标则清楚拒绝、保留原因，不提交改链。后端Owner已实现single/multipart初始、verified rebind及closed-batch复用的同一守卫，须等最终组合和独立验证，不把UI禁选当后端已放行。

`WordOriginalView.original_saved`、conversion的state/coverage/attempted/verified、`word-materials`当前采用分别读取。失败保留“Word原件已保存／本次对应检查未完成”“Word交付未获对应检查资格”。受控转换成功不等于对应检查或Word正式交付资格；用户补PDF是独立文件且声明未核验；原始Word、转换PDF、当前受检PDF及编辑器正文不混身份。重试转换用Word单GET实ETag；不使用材料/Bid tag。历史转换、来源/头变化不得抢当前稿。

## 5. 独立用户/QA的13项真实任务清单（全部待12最终native执行）

以下不是已过列表。先绑定最终03源码、actual、冷启动进程和实载assets；使用全新自有合成项目，上传前明确`auto_review=false`，0收费。禁止绕过隐藏控件、手填UUID或用旧API404代业务空态。失败夹具/资源窗口由PM协调，不擅开容器/consumer。

| ID | 用户真实任务 | 必核结果/反例 |
| --- | --- | --- |
| W12-01 | 原生5186登录、创建自有项目、关闭自动评审，刷新 | live实际OpenAPI与最终artifact同对象；账号私下提供，页面/请求不含假数据；不是overlay，绑定源/JS/CSS摘要。 |
| W12-02 | 已有PDF直接上传→核验→明确入库 | 快速PDF路径独立存在，不要求先做目录、事实库或Word；空文件本地拒绝不留空批次。 |
| W12-03 | 选择DOCX用途和文件身份→原件核验→入库→下载原件 | 名称/精确SHA一致；只同格式新版本；415/隔离不说原件已保存；没有自动结构导入或评分资格。 |
| W12-04 | 实际转换关闭/失败/partial时从Word卡继续 | 原件仍可取件；attempted=false不说已运行后失败；范围/原因持久；主动作“上传此修改稿的PDF”，不重传招标或全批。 |
| W12-05 | 从失败Word卡补对应PDF，刷新并换第二会话恢复上传/绑定 | 同bid/role/精确Word来源、独立new_file、user_declared/unverified；新GET约束跨会话可发现，旧ACK缺字段不当null；不能重绑定旧PDF链，失败保留原因。 |
| W12-06 | 真受控转换成功→查看转换PDF→检查实际采用 | DOCX/转换PDF各自真实下载SHA；controlled关系与用户声明不同。当前采用仅按word-materials读回；Word检查资格仍未获。 |
| W12-07 | 同Word新版本/更换当前稿后回看旧原件与旧转换，刷新固定链接 | hash/实际版本不回退新头；source_is_file_head/当前采用区分；迟到旧转换不抢当前，原件和旧产物可还原。 |
| W12-08 | 创建草稿、写真实中文、保存ACK；两成员编辑制造412/失ACK | 未ACK不显示已保存；人工正文/来源/稳定node ID保留，恢复原body/key/tag，不以新稿冒原结果。 |
| W12-09 | 多级树新增/改名/移动/copy/附录/删除及恢复 | 先看before/after和正文/要求/来源/计划删除影响，再一次应用；稳定section ID；复制新ID不继承ready；原要求/风险不因删目录消失；失响应/412保留输入/差异。 |
| W12-10 | 保存编写计划目标/关键点/要求/来源/待核事实/页预算，两成员改计划 | draft与plan双CAS；不拿section revision充plan revision；冲突可看服务器当前计划并保留自己输入后明确对照；预算与实际总页/章页未知分开。 |
| W12-11 | 目录模板另存/企业新版本→明确匹配现有章→预览应用 | 保存模板不改当前稿，不按近名自动匹配；不隐删人工内容/引用/计划；family ETag/失响应意图正确，历史模板版本可定位。 |
| W12-12 | 版式另存/新版本、绑定已确认格式要求真实原页、核对范围、应用 | 两类模板独立；来源失效/未确认拒绑定；项目字段优先；format_report.review_digest原样ACK，未判明范围常驻；Action只一次应用，412不覆盖当前稿。 |
| W12-13 | 保存ACK后按双模板固定快照构建、双格式预览/下载、改稿重建/回旧产物；1440/390键盘 | 真实各格式状态/字节/文件名（项目＋快照），失败格式不抹已成功格式；旧快照不变、旧结果不自动采用；PAGE与TOC/章页未知分开；移动整页无横溢出，目录“继续编写本章”可聚焦，原页/关闭返回正常。 |

## 6. 未完成能力：必须持续明示，不能永久删需求

产品完整人工成稿包仍要求RICH表格（含合并/跨页）、图片及资产来源、Word结构预览/明确导入、真实目录页码、实际章节物理页范围、最终版面检查和含表图双格式守恒。它们未集成到当前12，不能用纯段落、alt文本、预算或总页数代替。

现页面边界：支持文字/标题/列表、树/计划/双模板；表图编辑、Word结构导入、真实目录章页仍待完整成稿包。`TOC_PAGE_NUMBERS_UNKNOWN`和`ACTUAL_SECTION_PAGE_RANGES_UNKNOWN`分别显示中文缺口。PAGE页脚成功只说明受控生成页码的对应子范围，不是TOC/各章页码全通过。转换完整也不代表Word检查/评审通过。

AI选区、多章批量、候选目录AI、建议差异应用及未知费用下“发送新问题”属后续独立组合；未调用/未解锁。助手unknown仍原样暂停。Scale7 API虽在应用02，却没有在12添加假评分/自动满分入口；技术总分、预测与正式资格不能推为可用。RAG来源参考不得替代正式评分的干净完整输入与三判断。

产品依据：

- `/workspace/tender-docs/04-验证与测试/a1-delivery-plan/current-implementation-review/A2完整成稿交接.md`
- `/workspace/tender-docs/04-验证与测试/a1-delivery-plan/next-product-handoff/完整A2与任务UI交接.md`
- `/workspace/tender-docs/04-验证与测试/a1-delivery-plan/current-implementation-review/助手未知费用下独立新问题协议.md`

## 7. 恢复顺序与命令（本次未执行）

1. 先核对本WIP inventory与11 frozen输入；不要把主目录旧dist当当前12。等待PM最终Word03/统一recipe/actual与资源窗口。当前`c2ac…`、`b651…`是来源链，不能擅自指定为最终部署通过。
2. 取得最终actual后，显式选择它生成；当前`npm run contracts:generate`默认共享快照可能旧，**不能盲用来覆盖12或08/09**。未来可在本片稳定后把默认脚本绑定最终输入。

```bash
cd /workspace/tender-workbench/apps/web
# 仅在PM提供最终冻结实际文件后设置，非凭据。
FRONTEND12_ACTUAL=/absolute/path/to/final-implemented.openapi.json
python scripts/generate-contracts.py --openapi "$FRONTEND12_ACTUAL"
npx prettier --write src/contracts.ts
npm run format:check
npm run lint
npm run typecheck
npm test -- --reporter=dot
npm run build
```

3. 一次最终质量门与受影响反例后，在新目录创建12 immutable manifest/源/215资产，不覆盖08—11；本轮没有创建12最终manifest。核新Origin/API/Worker/profile/Kafka和非付费窗口，再原生实走13任务。API8818与Origin5186只是计划；未就绪时不得用旧8816的新路由失败推产品失败，也不得在旧API伪造成功。
4. 普通运行命令（需新native就绪、准确核端口归属后，不能现在自动执行）：

```bash
API_PROXY_TARGET=http://127.0.0.1:8818 npm run preview -- --port 5186 --strictPort
```

最终验收应改为在12固定源根/固定dist运行，保持127.0.0.1；按manifest核实实载资产、依赖锁与精确进程。不得HMR边改边审。依赖由`package-lock.json`恢复，现锁SHA `240dcc9e8a081687a2395f7e04de78cbe7e71ae0897dd966e2743c620db17210`；node_modules不入Git。`npm ci`只在未来授权网络/资源窗口执行，本次没有install。

重建任一旧候选时先复制代码到新scratch根，排除`node_modules`、`dist`、`*.tsbuildinfo`，再依锁安装/构建。**不要在旧frozen-inputs直接build**：那里`dist`可能指向旧frozen-dist，重建会破坏不可变证据。静态资源保留本地PDF.js worker/CMaps/字体，不走CDN。

## 8. 11现运行、hold与unknown守卫

最后绑定：PID `3220759`、UID `1000`、会话 `92187`；argv `node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 5184 --strictPort`，显式启动cwd `apps/web/qa-previews/assistant-continuation-11/frozen-inputs`；代理8816固定task05。PID是交接记录，不是允许未来盲kill；必须重核当前PID/UID/argv和端口归属。旧10被准确替换，10全部文件保留。

11场景仍使用独立显式Mock设施和私有持久状态，control已由独立用户还原`hold`，前端12未更动。不得清global unknown账、换nonce补发、修改控制文件、启动付费consumer/真实provider或用Mock记录声称真实模型质量。若需再做正向，必须由PM分配唯一显式Mock窗口，仍走原API/Worker/publisher，结束核hold和原账。聊天“好的”不执行Action，Action仍一次明确确认，采纳不自动解决风险。

账号、Cookie、DSN、私有profile、对象票据、模型key以及任何用户原件均不在本交接文档；由PM通过私下配置/备份交接。仅有repo和compiled资产不等于恢复数据库/原件/会话。旧11与所有其他固定端口本轮保持，不为交接热升级。
