# 手工编写、精确构建与原件解析检查点

本记录描述 `work/bid-workbench-completion-20261021` 的软件实现与已执行验证。统一提交号、真实 PostgreSQL 和转换器结果由集成检查点补充；这里不把待执行的环境验收计为完成。

## 当前动线

1. 项目资料页明确进入章节编写；编写页可回到包与原件。导航偏好保存失败不阻断工作区。
2. 既有章节计划、目录与格式依据继续使用原保存队列和修订 CAS。Rich 能力由实际注册路由提供，编辑器保留表格、合并单元格、图片资产身份、稳定节点与引用，不把富文档降为纯文本。
3. 用户明确保存并确认当前 draft revision，选择目录/样式模板及格式，再建立精确构建。历史和详情共用构建身份：draft、revision、snapshot、input、manifest、writer 和原请求。
4. 构建申请先保存恢复记录。网络不确定、幂等冲突、未知或不匹配 ACK 保留原 key/body；读取构建失败不能抹去已发送请求。结果区按实际 operation/output 状态展示，DOCX 与 PDF 分别下载。
5. 用户选择一个成功输出、包、用途与分册，明确采用。追加以刚读取的包 ETag 为前提，保持全部旧成员，写入新 revision；原正文、资料头和评审头不变化。
6. 已采用的 PDF 或包成员可展开独立原件解析。读取条件、填写理由、申请均由用户明确触发。完成只刷新解析目录；仍须用户明确选择可用的精确 parse 和物理页范围后保存包新修订。

## 关键资格与一致性

### 生成文件采用

`packages/authoring/package_outputs.py` 核对成功构建、`export/1` operation、固定 snapshot/input、同项目输出和提交文件身份、唯一输出发布 audit、实际字节长度与 SHA-256。PDF 还要求同次 DOCX 的精确受控转换关系、冻结 renderer identity 和两端摘要；不凭 `artifact_kind=bid_body` 放行。

生成来源闭包包含全部编写依据；PDF 再经过精确 Word 节点。撤回、自然时效、当前正文依据、规则/事实/计划/格式确认和图片资产版本继续约束新用途。采用先读快照，再在事务外核对原件字节，最后持原锁重新捕获并发布资格、包修订、ACK 和 audit。

`observe_admission` 是只读 RR 观察，复用完整当前 authority 计算。`lock_sources=False` 只用于只读观察，既有默认锁保持；发布与无锁组合明确拒绝。包冻结、准备和新评审用途由共享 `read_member`/observations 再核对资格；历史 ACK 和历史下载不被新状态冒充或改写。

### 独立解析

`packages/domain/document_parses.py` 和 `apps/worker/document_parse_handlers.py` 不改变材料或正文头，不调模型、不自动评审。仅接受已提交且具精确核验凭证的 PDF，或已通过生成资格的 PDF。

- 输入固定原件 SHA/长度/文件修订/用途、资格摘要、来源观察、解析器与实现摘要。后续配置变化不会悄悄改用新方法。
- 字节读取、PDFium 或配置解析器调用在事务外；前后 RR 快照及最终 graph/bid/lease 锁内重核阻止撤回、项目关闭、取消和迟到发布。
- 长度上限 100 MiB、物理页上限 1,000、证据块上限 100,000、规范结果上限 64 MiB。完整几何与表格结构保留，非有限数、无效摘要/页序/覆盖声明、任意嵌套字符串或键中的 NUL 明确拒绝，不修剪成“有效”数据。
- 默认 PDFium 方法始终是部分文字覆盖，不能宣称 OCR、表格、图片或版式完整；Word 覆盖声明恒为 false。
- 请求、结果及 receipt 为追加记录；完成结果形成后，即使包尚未选用该 parse，数据库也拒绝追加页或证据。页/证据插入和结果封闭以同一 parse 行锁串行化；写事务明确要求 READ COMMITTED，旧 RR 快照不能绕过后来提交的结果封闭。
- 旧命令 ACK 在当前解析器探测和项目新写门禁前恢复。同精确 context 的活动/成功申请可复用；跨成员复用保留原申请者与理由。

SQL 对请求的文件身份、source 形状/状态、方法枚举、上传 receipt hash、生成资格 audit、operation/outbox/command/audit 原子关系进行独立检查。完整生成依据的当前资格仍由应用和 Worker 共同检查，不在 SQL 中复制整套编写领域授权。

## 已执行的软件验证

| 检查 | 实际结果 | 限制 |
| --- | --- | --- |
| `tests/test_document_parses.py` | 18 通过；真实内存 PDF 字节经 PDFium 提取两页及旋转；4 个 NUL 反例先失败后通过 | PDF 是合成技术样本，不证明真实扫描件、OCR 或外部 Word 转换质量 |
| `tests/test_authoring_package_outputs.py` | 29 通过 | 受控资格观察与字节端口，不替代实际 DB 事务验收 |
| `AuthoringBuilds`、`AuthoringRichEditor`、`AuthoringOutputAdoption`、`AuthoringImagePicker`、`richTableTools`、`BidPackages` 前端回归 | 6 文件 36 通过 | HTTP/存储和编辑器合成回归，不是浏览器视觉或真实 Office 验收 |
| 独立解析前端 | 4 文件 41 通过；详见 `frontend-document-parse-acceptance.md` | 使用正式字段的合成回执；PDF renderer 在原页边界测试中替换 |
| 新实现静态检查 | 限定 Python ruff 通过；7 个实现模块 mypy 通过 | 全项目生成类型与注册完成后再进行集成检查 |
| 真实 PostgreSQL 17.11：采用、生成资格新用途、独立解析 | 同批串行 21 通过：采用 5、生成物资格 2、独立解析 14 | 实际非 owner API/Worker、SQL 约束与 PDFium；对象存储为显式内存端口，原件为合成技术样本 |
| 集成前再次复跑 | M1 与独立解析前端合并 10 文件 77 项通过；采用与解析纯后端 47 项通过；7 个实现模块 mypy、Bandit 通过 | 不替代实际 PG、对象存储或渲染器验收 |
| 既有编写回归 | 144 通过、6 个环境门测试跳过；明确使用仓库 `renderer-profile-02.json` 作为拒绝路径的固定配置夹具 | 未执行 Docker 转换或模型调用；skip 未计为通过 |

图片登记测试包含异步字节读取期间离开页面、卸载后迟到 ACK、丢 ACK 刷新以及存储配额不足：前两项先暴露失败，再以挂载身份守卫修复。表格合并/拆分测试核对全部单元格正文、稳定节点和空段落保留，以及越界/重叠/空洞拒绝。构建历史以明确展开的一条记录加载详情和轮询；20 条历史挂载引发 20 个详情请求的反例先失败，修复后目录不会自动读取全部任务。

章节先按纯文字打开、随后取得表图能力并插入图片时，编辑器现在按 schema 与项目重新建立视图，避免旧图片视图和粘贴处理器继续引用文字 schema。新增真实编辑器组件回归在修复前无法显示精确版本图片，修复后显示正确版本且粘贴仍保留原文字和图片；与富编辑器、编辑 schema 相关的 3 文件 7 项回归通过。

采用、生成资格后续用途、解析的真实非 owner PG 用例分别位于：

- `tests/test_authoring_package_adoptions_pg.py`：5 项，真实 DOCX writer、memory object store、非 owner API/Worker、精确包修订和旧 ACK。
- `tests/test_package_generated_output_admission_pg.py`：同伴提供的生成物新用途资格回归。
- `tests/test_document_parses_pg.py`：14 项，真实 PostgreSQL/普通 Worker/PDFium；包括取消、关闭、IO 期间撤回、错误字节、结果内容封闭、旧 RR 快照追加，以及故意绕过正确 capture 后 SQL 仍独立拒绝伪造观察。

上述 PG 文件已在统一集成流程同批串行执行，21 项全部通过（5.76 秒）。检查库使用独立 API/Worker LOGIN；生成 Word 及 PDFium 解析实际执行，未调用外部模型。此前两个 fixture 错用 autocommit owner 注册来源，现改为真实 Worker 事务，未扩大生产权限或放松来源守卫。模块内各技术样本的原件摘要保持独立，避免全局不可变 blob 去重约束掩盖待测行为。

四个实际解析方法、实施版 OpenAPI、五个前端 DTO、Worker document lane 与发布分派已接通，fresh-schema 和分离 grants 已纳入初始化；详见 `registration-acceptance.md`。

## 尚需真实验收及明确限制

1. 实际转换器、冻结字体供给、CJK 字形与分页结果需以真实部署环境验收。仅 Word 成功、PDF 部分或失败时仍可下载成功文件；不宣称已具完整受控 PDF 资格。字体隔离修复和渲染测试由独立集成检查点记录。
2. 本检查点之后已补齐外部 Word 到可编辑 Rich 章节的独立导入路径，新增候选、映射预览、转换限制确认与原子追加，见 [后续导入验收](word-rich-import-acceptance.md)。当前支持明确的文字／列表／原生表格／内嵌图片子集，修订与复杂对象等仍显式阻断，不承诺任意 Word 完整保真。
3. 默认文字提取的 partial parse 不能选成包的完整冻结解析。若要进一步开展依赖完整原页的准备/审查，须部署并验证配置解析器，或补足已有明确的原页覆盖机制；本轮没有把 partial 改为 complete 绕过该门槛。
4. 首次解析会把原件来源从 unregistered 登记为 published。随后 fresh context 与首次 context 不同，新的明确申请可能再计算一次；同一稳定 context 才复用。当前没有宣称跨来源登记状态的语义去重，也没有修改旧 ACK 的精确绑定。
5. 新 SQL 走显式 fresh-schema 初始化。旧库升级必须由受审的迁移流程处理，不能用重复执行完整 DDL 或静默清库替代。
6. 不存在本轮真实外部招标样本、收费模型评估、专家评分或可提交性证明。构建成功、包保存成功、解析运行结束分别表示自己的阶段完成。

## 针对性复核命令

```sh
WORKBENCH_ENV_FILE=review-readonly PYTHONDONTWRITEBYTECODE=1 python -m pytest -q \
  tests/test_authoring_package_outputs.py tests/test_document_parses.py \
  tests/test_authoring_m1_composition.py
```

在 `apps/web`：

```sh
./node_modules/.bin/vitest run src/AuthoringBuilds.test.tsx \
  src/AuthoringRichEditor.test.tsx src/AuthoringOutputAdoption.test.tsx \
  src/AuthoringImagePicker.test.tsx src/richTableTools.test.ts \
  src/BidPackages.test.tsx
npm run typecheck
```

`test_authoring_m1_composition.py` 还检查采用和四个独立解析方法确实注册到应用及实施版 OpenAPI；仅有 schema 或未接线的模块不会让该验收通过。
