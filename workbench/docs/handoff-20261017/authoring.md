# A2 编制开发无损交接（2026-10-17）

用户要求整理全部工作提交 GitHub，Owner 已停止开发、测试、渲染、Docker及复制运行根。当前源码全部留在仓库工作区，尚未形成正式候选的代码明确按 WIP 交接。本文不表示 M1 完整人工成稿已验收。

## 从哪里接手

- 当前代码：`packages/authoring/`、`apps/api/authoring.py`、`apps/api/authoring_structure.py`、新增 `apps/api/authoring_rich.py`、`tests/test_authoring*.py`。
- 当前逐文件摘要见同目录 `authoring-source-state.json`。它是停工时工作区清单，不是假定测试时依赖不曾变化的证明。
- 原始候选及原始证据根：`/workspace/tender-docs/04-验证与测试/authoring-complete-development-checks/`。目前位于仓库外，GitHub交接需由PM统一收录公共档案或提供该外部目录的完整备份；不能只提交本文就声称原始证据已上传。
- 当前产品完整成稿协议：`/workspace/tender-docs/04-验证与测试/a1-delivery-plan/current-implementation-review/A2完整成稿交接.md`，SHA256 `c16bf6b093025f20b44bd42498959193df379241ebcc4e2aee6b40d3aeb0460f`。
- 原有快速PDF主流程、手工保存、历史快照、已有生命周期守卫都保留；这是全新系统，无旧系统迁移。

## 已冻结与未冻结的准确区别

以下路径均相对于上述外部证据根，摘要均为 SHA256：

| 输入 | 路径 | 摘要与范围 |
|---|---|---|
| TREE/PLAN/双模板首片01 | `candidate-01/candidate.json` | `f6fd639040d592256e89ee9291b3e513374aab9181d072842e5eca6328297587`；329固定输入，56过/3跳过，真实DOCX；不冒真实PDF |
| PAGE/双模板构建02 | `candidate-02/candidate.json` | `5cb2bd6f9c205bace488158d3b9656222b3e9a54aa215d1c6bf2d834f11773e9`；335固定输入，80过/3跳过，另固定根4实际PG/受控转换/Worker链；不覆盖RICH |
| RICH具体端口静态01 | `rich-port-static-01/candidate.json` | `e2f15d90940acb10e31cfb85331d22844cce47575fd12855cfb8821d9d08fa31`；12 own/338 deps，58离线过；随后独立架构发现RP01图像可见性阻塞，不能据58过授完整资格 |
| RP01最小修复静态02准备根 | `rich-port-static-02/inputs.json` | `afc796516aa64c52e6cdfdf182958181f36f05269610eb86e6fc4930ee2f4cba`；13 own/338 deps共351个精确字节，**尚未创建candidate.json/最终HANDOFF，不是正式冻结候选** |
| 02派生公开profile文件 | `rich-port-static-02/evidence/public-derived-profile.json` | 文件摘要 `d59a6737e19be3c14a555c92be068a9affdb513a11b20139481b9fb9302bdf2e`；内部profile_digest `4d28d762cffbbf96efcd02b1e1e4674c48ac41dd957e48568306b1a2db95948e`，仅纯生成、未真实安装/运行 |

02准备根只复制三个小增量文件共32170字节，其余348文件硬链接到01不可变档案，没有34MB大数据复制。禁止对任一固定根执行formatter或原地编辑（硬链接会同时改变旧档案）；修改必须在工作区另做新候选。01候选和架构反例原字节仍保留。

## RP01及实际已做验证

独立架构反例在 `/workspace/tender-docs/04-验证与测试/authoring-rich-port-architect-review/static-01/`：规范原图是白底小数字9，原图RGB和尺寸仍正确，但25×25白色矩形完全盖住数字；旧全图均值0.4小于阈值3，错误标complete。它阻塞图片完整可见资格，不表示OOXML sandbox逃逸。

已保存修复为 `rich_pdf.isolated_reference`：使用同一PDFium像素网格独立绘制冻结原图，再逐像素核最大通道误差≤2及均值≤0.5；白边大小不再稀释小前景。累计实际/参考页栅格6400万像素后明确partial。精确原图RGB、尺寸、版心和不透明性仍需同时满足。`rich_renderer` profile新增该像素预算和新对应策略摘要。

- 原58项在修复后实跑仍过，`rich-protocol-01/visibility-delta-first-junit.xml`，摘要 `502468298d46de29d79164d9af4df484f042e5c6701c91382b96e9688f8855e5`。
- 8新增真实合成PDFium项：原尺寸/更大白边、黑数字/浅灰数字/单黑像素、分数坐标及缩放正向、栅格预算关闭；`visibility-sparse-first-junit.xml`，摘要 `7cc7f3c127cd8bf60dc51c3465ce968dbf5296f9ed63a772e7bdfecd4190f9ca`。
- 02准备固定根66项实过（58+8），`rich-port-static-02/evidence/fixed-junit.xml`，摘要 `a8d787899fea4d3646ce85705c8cc7da1af571b3d9d444dab690075bc0f28ae7`；同目录ruff/format/mypy9源/Bandit0日志均已保存。
- 同一份架构原PDF字节重核：baseline complete、白块覆盖 partial，最大误差176；`exact-original-counterexample-delta.json` 摘要 `2b91ea2d3f94ef4565b5a2101b4a03b159a4d1b136fdc0c5b1780524638f04b4`。原反例PDF/脚本/JSON也逐字保存于02 evidence。
- 这是开发自测，**RP01修复尚未独立架构复验；真实新RICH Docker/LibreOffice转换次数仍为0**。合成PDFium、显式mock-adapter循环和旧PAGE02转换均不能替代它。

## 当前RICH API/Worker WIP

这些在工作区，**不在static01/02准备根的完整API范围，也没有全量正式候选**：

- `rich_assets.py`、`rich_uploads.py`：受限PG两表，PNG/JPEG实际Pillow12.3解码/规范PNG、原件/规范图双摘要、exact asset/revision/version、同bid锁/CAS、withdraw追加版本。复用blobs对象库，不伪装成业务document version。短资格事务→关DB CPU/对象PUT和回读→最终会话/生命周期/来源重核；unknown有audit恢复记录且只接受明确同输入重试。
- `rich_snapshots.py`、`repository.py`：v1/v2内容摘要分离，保存冻结精确图片版本、双blob/proof/source_refs；历史快照在撤回后仍可读，新用拒绝。附加来源只说明用户附加依据，不能证明图片来自那份Word的像素提取。
- `rich_build.py`、`build_repository.py`：复用现有export/1，无新handler；`generated_rich/3`冻结双模板、图片digest、pagination_mode、generator/writer/profile。compute在DB关闭后读取精确PNG、重生成DOCX、可运行最多3次布局测量（未实际执行）；每次实际DOCX/PDF应保全私有blob。最终Worker fence中重核生命周期/来源/双模板authority/图片head后才登记产物及辅助blob。不移动current_body，不自动评分。
- `apps/api/authoring.py`：POST build通过`pagination_mode`显式选RICH；rich正文不能被旧text生产器静默拍扁。`follow_up=review`必须明确请求PDF。GET build增加`layout`只表示navigation，不授完整视觉资格。历史恢复用对应内容schema摘要而非强塞v1。
- 新独立router `apps/api/authoring_rich.py`：图片上传/状态/目录/版本读取/撤回/原件与规范图下载、rich-capabilities。测试只在进程内include；**共享main/composition未注册它**。
- `rich_schema.py`、`rich_contracts.py`：实际v2闭合节点/资产与RICH构建/布局只读projection；实际schema扩展尚未由共享exporter集中收口。frontend必须等待正式actual，不可猜UUID或使用moving类型。
- 仍需PM/backend集中改动：main/composition注册独立router；exporter在structure扩展之后调用`rich_contracts.extend_openapi`；`apps/api/history_routes.build_view`通过同一个`rich_build.layout_view(c,build_id,manifest)`给列表也追加layout，确保单读/历史一致。Owner未改这些共享文件。

### 真PG/ASGI机制证据

均显式Memory对象、真实非ownerAPI/Worker PG/ASGI；HTTP真实transport/provider from_env硬阻；新构建测试另硬阻所有Docker函数，richprofile环境删除。没有真OSS/收费/消费者/Kafka演练声明。

- 资产/保存/历史13项：`rich-protocol-01/http-save-pg-junit.xml` SHA `cf76c670b288b863367916d211c706bed92d8e19676948f57bd04118befda1bf`。其后增加了上传来源用途标记；新7项包含了带该标记的实际上传链，但没有重新宣称旧13覆盖全部后续源码。
- 首构建4项通过：`build-memory-second-pg-junit.xml` SHA `cbb16abf6093f46a501ee11f99e33b811ce8f64a73c6f96cdd3917af9e14c00f`：真实native合并表/内嵌PNG/书签DOCX成功，未配renderer的PDF独立失败，TOC与章页unknown；图片计算后撤回拒全部发布；错误snapshot身份拒；明确模板/模式/followup字段校验。
- 后增为7项通过：`build-memory-third-pg-junit.xml` SHA `9fa7ccd994e466c5b19c2f21145d52343535b9112cf87a00d720e9672959851f`：再含实际HTTP取消迟到fence、rich历史恢复/withdraw后新恢复拒/旧ACK重放、实际response与扩展schema校验。此7项在RP01最终像素修复前执行，未绑定最终全部组合依赖。
- 首构建失败3/通过1原始 `build-memory-first-pg-junit.xml` SHA `51d37e9a858eb98a38225acc66ba7457e33aba01a27346c9d3ccd86a4506948f`：新测试fixture误读不存在的outbox.created_at，产品HTTP受理已202，未到compute；`build-memory-first-fixture/`保留当时源码与说明，修测试查询后过，不是业务权限补丁。
- 更早fixture事务顺序/Memory去重及未patch storage.client造成原生OSS GET404，见 `rich-protocol-01/pg-fixture-observation.json`、`save-preflight-transaction-order/`、PAGE02原始preflight，均未抹掉首失败。

## 未完成事项（必须继续，不得用声明缺口代交付）

1. 首先完成static02正式manifest/独立RP01复验；静审和PM具体资源窗口均通过前禁止运行新RICH容器。最后窗口被独立恢复QA占用，PM要求0Docker/大build/大复制；新接手者不可据旧窗口擅自恢复。
2. 当前含任意表格始终 `AUTHORING_TABLE_PDF_GEOMETRY_UNVERIFIED`。真实LO合并单元格/跨页/行列边界/尺寸溢出需实际PDF几何与代表稿复核，不能仅比cell text就complete。
3. 实际LO是否保留direct内部Dest、原始PNG RGB、页脚PAGE以及rich正文所有数字守恒均未知。若出现GoTo action/重编码像素/丢锚点，保存首失败后另交精确策略，不临场绕过白名单。
4. 导航模块只在真实小PDF验证，真实RICH三轮TOC固定点/父章包含后代实际范围/改稿重建仍待。每章另起页是明确构建选项，前端须呈现页数影响；连续排版章末页仍unknown，后续需求不能删除。
5. 外来Word结构预览→明确缺口→选择导入稳定章节/表图/引用由解析Owner并行，受控转换不等于内容导入；精确image part/blob/version/digest来源不能用手工source_ref伪装。当前RICH上传仅本地PNG/JPEG。
6. 正式API/actual/frontend/发布新环境集成与全候选源码依赖冻结未完成。新SQL已审fresh，但旧release不得owner热补；旧快速PDF/历史仍应回归。
7. M1完整人工成稿代表稿仍待：多级目录/跨页合并表/图片/分页/引用→编辑或导入→树/计划/双模板→双格式/真实章页/格式预览→改稿重建→历史还原/资产撤回/CAS/取消。后续M2选区AI/多章批量应用必须继续复用同Action消费、账本预算/fence，不提前用AI按钮代M1；0真实付费约束继续。

## 复现入口（交接后授权窗口内执行，本文写成时没有运行这些命令）

纯离线66项，可在已保存02准备根执行：

```bash
cd /workspace/tender-docs/04-验证与测试/authoring-complete-development-checks/rich-port-static-02/frozen-tree
/workspace/tender-workbench/.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_authoring_rich.py tests/test_authoring_rich_renderer.py tests/test_authoring_rich_visibility.py tests/test_authoring_page_navigation.py
```

PG机制从当前仓库源码执行；只用PM fresh的rich01业务profile，勿拿static准备根的旧PAGE2 repository跑RICH集成。环境文件是标准shell赋值，加载时不要echo或xtrace：

```bash
cd /workspace/tender-workbench
set +x
set -a
source .local/authoring_rich01-runtime.env
set +a
RUN_AUTHORING_RICH_INTEGRATION=1 .venv/bin/pytest -q tests/test_authoring_rich_integration.py tests/test_authoring_rich_build_integration.py
```

实际运行RICH前，由安装Operator按准确新运行根/已审Word03 runner/镜像/字体路径生成base_profile，再调用`rich_renderer.profile_for(base)`，写600私有文件，通过`AUTHORING_RICH_RENDER_PROFILE_PATH`注入API。必须实际build_profile验证同一mount/digest；不能把本包公开旧路径base或手改profile_digest作为运行资格。缺失/变化配置保留真实DOCX，PDF明确失败。新RICH专用端口与外来Word03/PAGE2分离，禁止扩外来Word字段准入。

## 文件归属与私有状态（只列路径，不含内容）

- 本Owner：authoring模块/三个authoring API/对应测试/新增authoring SQL；不改main/engine/exporter/shared history。`packages/authoring/page_navigation.py`、`PAGE_NAVIGATION.md`及导航测试由解析Owner独占；其候选SHA `390c428faee2afbe088e7b8397647a7bced4f5ea0ab6bac148fb72c8a0f9e14e`，module SHA `1413dcbd1de59db949c602da9f913fe9b31ece0f2976fc47c678baecc3765054`。
- Word03候选路径 `/workspace/tender-docs/04-验证与测试/word-intake-development-checks/candidate-03/candidate.json`，SHA `b12e2e456ead217296510ae6fde3f7747198d75adffe42706bb3692c28406fa6`。外来Word03全部动态域仍拒；其源由解析Owner独占，不能用RICH白名单放开外来Word。
- 私有业务profile：`.local/authoring_complete01-checks.env`、`.local/authoring_rich01-runtime.env`；rich01是20已审SQL的全新库，4业务角色无owner/purposeDSN、provider剔除/Kafka空。只供本地受限机制，不能入Git或用于旧库修权。
- 私有旧Word安装profile：`.local/word-render-profile-dev06.json`（当前具体新运行根需重新建）；PAGE专用profile通过`AUTHORING_GENERATED_RENDER_PROFILE_PATH`配置，RICH专用新profile尚未真实安装。私有文件必须600，禁止公开值/口令/签名URL。
- 原生对象存储凭据位于PM私有配置，本文和组件证据不含内容；旧模拟S3 19000/19002已停保卷，不能假设仍可用。高频用例用Memory；业务私有blob/本地PG数据卷完整备份由PM统一处理。

本交接没有启动消费者、模型调用、Docker，也没有发布/修改bucket配置。GitHub提交由PM统一完成，本Owner没有单独提交或推送。
