# 精确章节历史读取与显式恢复验收

日期：2026-10-21。范围：检查点 14 的独立章节历史增量；基线为检查点 13 `318ee83b95b4871dadb91a01d7d31aafe02fe4c1`。

## 已闭合的用户流程

用户展开章节历史目录，明确选择一条保存记录，读取该项目、草稿、章节、原修订及正文摘要共同绑定的完整历史原稿。确认前可展开与当前已保存正文的文字变化及完整当前稿；展开、读取和比较均不写入。用户显式恢复时先处理未保存稿，再沿用既有恢复接口、当前 CAS 与原请求幂等机制，追加新的修订并保留全部旧版本。

原实现请求的 `/sections/{section_id}/revisions/{revision}` 实际没有后端路由。本批新增受约束的历史 GET，替换前端该读取路径；既有恢复 POST 的业务语义未改。**恢复旧版本的正向路径已通过真实非 owner PG 与真实主应用 HTTP 验证，并非仅凭 GET 存在推定恢复完成。**

本批不表示整包历史恢复、全部 F12 或全部 UI 39 点完成。

## 精确读取协议

入口：

```text
GET /api/v1/bids/{bid_id}/drafts/{draft_id}/sections/{section_id}/revisions/{revision}?expected_digest=<64 位小写十六进制>
```

`expected_digest` 必填、只允许单值；未知 query、重复 query、空值或格式错误均拒绝。没有“未传则取最新”的语义。路由的修订范围为 `1..2^63-1`；浏览器仅接受可安全表示的正整数。错误项目、草稿、章节、修订或不存在的原记录不会回退到当前头。正文摘要与所选目录记录不一致返回 412。

闭合 DTO `AuthoringHistoricalSectionView` 提供原生保存的项目、草稿、章节、章节修订 UUID、修订号、schema 摘要、正文摘要、完整正文、保存成员 UUID、保存时间，以及所有图片的确切版本绑定。正文 schema 复用实际 authoring 富文本/文本 schema，独立命名为 `AuthoringHistory*`，不覆盖已有契约。响应不含原件对象路径、幂等键、请求体或规范化证明细节。

三个固定字段明确读取边界：

| 字段 | 固定值 | 含义 |
| --- | --- | --- |
| `read_only` | `true` | 当前结果是历史原稿读取 |
| `source_qualification_assessed` | `false` | 历史读取没有核准当前来源用途 |
| `restoration_authorized` | `false` | 恢复须另走既有命令及当前有效性核查 |

保存成员显示实际 UUID，不猜姓名。历史读取不发当前草稿 ETag，不把旧版本身份当成当前 CAS。

## 原生关系、事务与权限

读取使用同一 `REPEATABLE READ READ ONLY` 事务。原章节修订通过原生 `section_revisions → sections → drafts` 的全部项目/草稿/章节关联定位，之后核对完整正文的原生 digest 与实际 schema；不改写原稿、不补齐缺失字段、不从最新头合成历史内容。

图片按原稿中的 asset、asset revision、asset version 读取不可变旧版本，核对原生 asset 关系、版本摘要、原始及规范图片 blob 摘要、PNG 类型、长度、尺寸与规范化证明。当前图片头已变更或后来撤回，不会替换旧图。响应中的 `version_digest` 与 `normalized_sha256` 由此前原生关系给出，供浏览器约束二次图片元数据和实际规范字节。

读取前核验实际运行账号为非 owner LOGIN，具备 `tender_api` 能力，且无 superuser、建库、建角色、bypass RLS 或业务对象所有权。最低 SELECT 依赖：

| 情形 | 原生表 |
| --- | --- |
| 所有历史读取 | `design.drafts`、`design.sections`、`design.section_revisions` |
| 原稿包含图片 | `design.authoring_image_assets`、`design.authoring_image_versions`、`design.blobs` |

本批没有新 DDL、权限修复、owner 回退或运行时授权。已有新库部署权限足够；缺表/SELECT 返回不可用，不自动补权限。`python -m deploy.authoring_history_readiness` 是只读部署检查，额外验证图片依赖。

完整原稿外层读取预算为 16 MiB；实际 authoring schema 自有更小的原稿大小限制。超过预算或存储格式损坏时返回错误，不返回截断正文。该外层预算不表示当前编辑器支持保存 16 MiB 的有效单章。

## 撤回与恢复边界

历史读取保留原记录事实：项目关闭、祖先来源撤回或图片后来停用时，合法旧正文仍可读取。它们不会因此获得当前用途或恢复资格。

恢复仍使用：

```text
POST /api/v1/bids/{bid_id}/sections/{section_id}/restore
If-Match: <flush 后当前草稿 ETag>
Idempotency-Key: <既有命令键>

{ revision, base_draft_revision, base_section_revision }
```

已有服务的来源、图片、项目生命周期和 CAS 条件继续生效：来源撤回返回 `AUTHORING_SOURCE_STALE`，图片失效返回 `AUTHORING_IMAGE_STALE`，关闭项目返回 `PROJECT_WORK_CLOSED`，过期 CAS 返回 412。所有拒绝均验证没有追加修订。前端不把读取成功或差异展开显示为恢复成功。

## 前端确认与范围隔离

- 历史目录懒加载，未选择修订时不读取历史正文；目录与原稿均做闭合结构验证。
- 原稿完整渲染保留段落、表格合并和图片；正文中的旧 `ordinal` 不被展示顺序覆盖。
- `AuthoringRichSnapshot.expectedImages` 始终传入所选历史的保存绑定。二次元数据的版本 digest、规范字节 SHA、实际 PNG 字节及浏览器解码未核验完毕时，恢复保持禁用。
- 文字变化复用 `TextChangePreview`；完整当前正文仍可展开查看，文字差异没有替代富文本原稿。
- 项目/草稿/章节变更重置历史读取实例；修订切换的迟到结果、异步正文验证和历史分页不能进入其他选择。flush 中离开原章节不发出旧恢复请求。
- 恢复开始后本地同步 guard 防止重复 flush；flush 拒绝、网络不确定、来源拒绝或 CAS 冲突保留所选历史供继续核对。
- 网络不确定后的显式重试保留既有 `useCommand` 的原请求键、ETag 与请求体。该共享 hook 未修改。

## 验证结果

### 原生后端与真实主入口

最终隔离候选由检查点 13 加本批 11 个 Python 文件，以及 root 所有的 `apps/api/main.py`、`apps/api/export_openapi.py` 两个最小接线构成。未混入并行的 B2、模型或整包任务增量。

- 候选树清单摘要：`f41c3b55352a3eb089fbc93b749ac88fa061b73be9f08ad19fcfdd09c01fc54c`。
- **36 项通过、0 失败、0 skip**：14 项纯协议/真实 main 挂载检查，22 项原生 PG/API 参数化检查。
- PostgreSQL 17.11；全新临时库、随机 loopback 端口与新非 owner API/Worker LOGIN；库与 HTTP 服务已停止。
- 主应用使用实际 `apps.api.main.app`、`lifespan=on`，没有重复测试路由 overlay。确认精确 scoped GET 仅挂载一次，实际 `/openapi.json` 返回该闭合 DTO。
- 真实 TCP HTTP 覆盖无会话拒绝、合法会话读取、成员停用拒绝（独立路由 HTTP 用例）、必填单值 digest 和未知 query 拒绝。
- 明确旧修订 2、当前修订 3，恢复后生成修订 4，正文与旧修订逐值相同；旧记录不变；同键重放 ACK 相同且仅增加一个章节/草稿/命令记录。
- 140,000 字符原生历史正文、原 ordinal 7、合并表格和旧图片版本完整保存/读取；后来停用旧图后仍可查看旧保存绑定，恢复被现有服务拒绝。
- 错项目/草稿/章节、缺修订、错 digest、坏 native schema/content/digest、来源撤回、项目关闭、过期 CAS、缺 SELECT，以及同 RR 快照内并发保存均有反例。
- 实际事务 UPDATE 被 `ReadOnlySqlTransaction` 拒绝；读取不调用存储或模型。

最终 PG 收据：`/tmp/tender-review-authoring-history-main/authoring-history-pg-9x3o4s1u-receipt.json`。早期独立路由 34 项通过的候选与收据保留在 `/tmp/tender-review-authoring-history/`，最终结论使用增加主入口验证后的 36 项结果。

### 前端回归与静态检查

**43 项通过**：本批 19 项 protocol 与 13 项 History 组件测试，加复用富内容 renderer 的 10 项与文字变化组件的 1 项回归。实际生成的操作目录包含新 GET，测试未虚构 `supportsApi` 能力。

本批 7 个 Python 产品模块 mypy/bandit 通过；11 个 Python 文件 Ruff/format 通过；全部 6 个前端源码/测试/浏览器脚本 ESLint 0 error、0 warning，Prettier 通过。本批 5 个 TS/TSX 文件与其实际传递依赖的独立严格 TypeScript 检查通过。

首次共享全量 TypeScript 检查曾遇并行整包任务联合类型拓展在 `TaskPackageTriggers.test.tsx` 与 `TaskTemplateEditor.tsx` 的缩窄错误，已交 root 处理；本批不改这些共享文件。随后对更新后的开发树执行 `tsc -b --pretty false` 已通过。最终检查点全量测试与生产 build 仍由检查点负责人对整合候选执行。

### 浏览器

最终独立前端候选为 `/tmp/tender-review-authoring-history-web-candidate`，文件清单摘要 `211026fdb27b27bfe70f5d0560c9aac8984db1fcdb9f283be1bc0e5e9b884156`。**6 组通过、14 张截图、0 页面错误、0 外部请求**：390px/1280px × 浅色/深色四组，以及图片绑定错误、来源撤回两组。还覆盖桌面缩放到窄屏后原选择保留、未保存稿拒绝 flush、比较不发 POST、显式恢复只写一次且保存原旧版本。

浏览器原稿为 108,016 字符合成正文，实际 DOM 全文核对、合并表格断言、真实 PNG SHA 与浏览器尺寸解码通过。图像目检包括手机完整原稿末尾/图片/合并表格、手机比较入口和桌面深色增删变化；布局检测确认操作控件与页面无横向溢出。

最终收据：`/tmp/tender-authoring-history-browser-20261021-c/receipt.json`。结果和每张图片摘要嵌入同目录 `authoring-history-checks.json`。脚本编译一次后验证固定 bundle，并记录实际输入源码摘要；最后确认这些源码未变化。浏览器使用合成响应；真实数据库/主 HTTP 的证据来自上一节，未声称本次浏览器直连真实数据库。

保留两次先前未通过的验收事实：首轮脚本误用主题存储键，浅色通过后在深色检查失败；已修正为实际 `bid-workbench:theme`。第二轮六组交互走完，但并行 B2 生成使共享 `contracts.ts` 摘要变化，被源码一致性门拒绝，不计固定候选通过。最终复制独立源码候选重跑后全部通过。没有为通过验收修改产品行为或降级图片绑定核验。

## 重跑入口

```bash
# workbench；仅显式隔离的新 PG 环境，禁止指向业务库
python -m pytest -q --tb=short tests/test_authoring_history.py tests/test_authoring_history_main.py tests/test_authoring_history_pg.py

# workbench/apps/web
node_modules/.bin/vitest run src/AuthoringHistory.test.tsx src/authoringHistoryProtocol.test.ts src/AuthoringRichSnapshot.test.tsx src/TextChangePreview.test.tsx
PLAYWRIGHT_MODULE=/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright node scripts/check-authoring-history-browser.mjs /tmp/authoring-history-new-evidence-directory
```

原生测试需显式 `FUSION_REQUIREMENTS_ADMIN_DSN`；本次安全 harness 位于 `/tmp/tender-review-authoring-history-main/run_pg.py`，只创建新集群并校验固定候选摘要，凭据不入收据。浏览器必须使用新的输出目录，保留旧失败及成功证据。

## 集成与交付边界

root 已接 router `apps.api.authoring_history_routes.router`、OpenAPI 扩展 `packages.contracts.authoring_history_api.extend_openapi` 及生成 `AuthoringHistoricalSectionView` 类型。本批 manifest 只列我所有的文件；主入口、生成契约和此前已冻结的 work_context A/B/native 证据不在其中。

验收清单记录实际命令、候选及依赖摘要、收据路径与限制。没有真实招标资料、真实用户回访、付费模型、原件转换效果或手机软键盘验收；这些不阻塞本次软件路径闭合，也不被合成资料测试替代。
