# 精确工作上下文 B：四阶段目录与已保存原稿验收

日期：2026-10-21。本批完成三个独立只读 GET、原生身份核验、部署权限检查及测试。基于已冻结的 A 批关联／核查／实交后端新增 11 个文件，不修改 A 的 14 个冻结文件。主应用和前端接线由根代理负责；本收据覆盖固定后端候选，不代表全应用浏览器或 F05-05 六级主要业务动作已经完成。

## 1. 稳定入口与返回边界

公共前缀为 `/api/v1/bids/{bid_id}/work-contexts`。所有入口复用真实 session 认证；业务读取在同一个 `REPEATABLE READ READ ONLY` 事务中完成，返回 `Cache-Control: private, no-store` 与 `Vary: Cookie`。

| GET 路径                        | DTO                     | 明确选择                                                                                                                 |
| ------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `/choices?kind=…`               | `WorkContextChoicePage` | `kind` 必填，仅为 `draft_snapshot`、`build`、`package_review_run`、`package_submission` 四种之一；没有自动选首项或最新头 |
| `/draft_snapshot/{snapshot_id}` | `AuthoringWorkContext`  | 固定草稿、草稿修订、snapshot UUID 和 digest；完整历史章节和富内容                                                        |
| `/build/{build_id}`             | `AuthoringWorkContext`  | 固定构建、build input、operation input digest、manifest digest、snapshot、writer；真实输出状态                           |

目录支持 `limit=1..50`、`cursor`，以及可选 `draft_id`、`package_id`、`revision_id`。草稿筛选只适用于原稿／构建阶段；包及修订筛选只适用于核查／实交阶段。标识必须属于当前项目，包修订必须属于指定包。重复、未知、错阶段参数返回 422，明确不存在或错项目对象返回 404。GET 不新增业务写权限；仍沿用应用既有成员会话访问规则。

目录按原生创建时间和 UUID 排序，返回实际标题／草稿修订或诚实的“整包核查／实交登记 · 包修订”标签、创建时间、状态、完整 selection 和 selection_digest。签名游标绑定项目、阶段、筛选及本次完整原生目录观察；新增记录或构建状态变化后返回 409，请从首页重新读取，不能续接旧观察。错阶段／筛选游标返回 422。返回的第一页不表示已选中其中任何对象。

`complete_observation=true` 明确限定于 `directory_basis=native_record_identity_and_state`。它不是对所有历史正文、来源资格或任务质量的合格声明；页面中的每个对象仍需以确切 resolver 再次核验。完整目录最多 1000 条原生记录，超过返回 413；不截断后称“全部”或“没有记录”。

两个 resolver 接受可选 `expected_selection_digest`，不一致返回 412。选择身份与当前观察分开，刷新后仍是原来明确选择的对象。

## 2. 已保存原稿与构建语义

原稿读取先核对 snapshot manifest 摘要、每条原生 snapshot-section 绑定、bid／draft／section／revision UUID、修订号、schema digest、正文 digest 和顺序，再复用现有封闭正文验证。重新计算摘要后篡改 section ID、revision ID、修订号，或增加重复／未知字段，仍不能变成可信原稿。缺少原生章节绑定返回错误，不静默丢章。

返回完整 ProseMirror 内容，保留表格合并和固定图片资产版本；活动目录节点独立返回，旧删除节点不冒充活动正文。原生允许所有章节均删除，因此零活动章节快照明确返回 `section_count=0`、空正文和空目录。单次完整快照预算为 16 MiB，超出返回 413，不用摘要或当前正文替代。

图片核对确切 asset/version、历史状态、版本 digest、规范化证明及原图／规范图 blob 身份，公开 DTO 仅包含固定资产标识和规范图 digest，不输出对象存储路径。旧图片撤回后，历史正文仍完整可读，当前资产观察变为 changed；这不是新的图片使用许可。接口不下载或重新核验原图字节，`original_bytes_reverified=false`。

构建核对所选 snapshot、原生 input manifest 和 operation input digest；成功 Word／PDF 输出必须具有确切原生文件记录与发布凭据。PDF 还须对应同次 Word 的受控转换关系。未完成输出为 pending，终态失败／取消且未发布为 not_published，格式失败为 failed。只有 succeeded 才有 document；失败或缺失输出的 document 恒为 null。另一次构建即使使用相同 snapshot，也不能补入其输出。

`current_observation` 分开陈述草稿头、来源和图片资产。普通保存快照只冻结直接来源引用，没有完整历史来源祖先图；即使直接版本仍匹配，来源观察也是 `unknown / REFERENCES_MATCH_QUALIFICATION_UNASSESSED`。不能以当前来源图代替当时资格。明确来源版本变化或失效显示 changed。

所有原稿／构建响应保持 `qualification_assessed=false`。正式数值预测、整包阻断风险数和整包通过结论均为 null；summary 仅 `navigation_only`。官方结果不进入投前摘要。目录中的核查／实交选择复用 A 的完整原生解析，实交仍只使用原来明确绑定的可选核查。

## 3. 数据库依赖与接线

没有新增 SQL、数据回填或运行时提权。使用 A 已冻结的 SELECT／只读函数依赖，原稿和构建附加检查以下实际表：

- `design.drafts`
- `design.authoring_image_assets`
- `design.authoring_image_versions`

核查／实交目录复用 A 对应依赖；原稿／构建复用 A 的构建关系依赖。完整表／视图／函数列表见 `work-context-catalog-checks.json`。现有全新 bootstrap 权限足够；原生测试撤销 `design.drafts` 的 SELECT 后实际返回 503，恢复仅发生在测试夹具中，产品路径不自动授权或 owner 回退。

只读部署检查：

```sh
python -m deploy.work_context_catalog_readiness
```

该命令逐阶段使用正常配置的非 owner API 连接，检查 RR 只读、角色和所需读取能力，只打印依赖名称与布尔状态，不打印连接口令或业务正文。

根接线最小操作：include `apps.api.work_context_catalog_routes.router`（路径已含 `/api/v1`），在实际 OpenAPI 扩展流程调用 `packages.contracts.work_context_catalog_api.extend_openapi(document)`，再按既有生成器生成真实 TS 契约。富文本 schema 复用现有 editor 的封闭定义但以 `WorkContextReadOnly…` 独立命名，避免改写现有编辑契约。

## 4. 固定候选及真实验证

固定基底：`ebe7e80b05cec1699eb0ce449cbda1406f4dc5d2`。候选只覆盖 A 已验证的 14 个文件及本批 B 的 11 个新源码／测试文件，没有混入并行 UI、历史研究或 authoring package-input 修改。冻结程序逐一复核 A 的 SHA256 未变。

- 候选：`/tmp/tender-review-work-context-catalog/candidate/workbench`
- 候选 manifest SHA256：`f5f18b1c6d7ff6f3b2e86e57ea894602330a7f00e74505c4364b9dcb94454b36`
- 原生收据：`/tmp/tender-review-work-context-catalog/work-context-pg-rkxib8dv-receipt.json`
- 原生日志：同前缀 `-pytest.log`

| 验证                                              | 结果                                                                                                                                                          |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ruff check、format --check                        | 本批 11 文件通过                                                                                                                                              |
| mypy                                              | 8 产品文件通过，无类型问题                                                                                                                                    |
| bandit                                            | 8 产品文件通过                                                                                                                                                |
| 封闭协议／纯规则                                  | 7 通过                                                                                                                                                        |
| 原生 PostgreSQL 17.11、非 owner API／Worker、HTTP | 21 通过；合计 28 通过，1 条既有 Starlette/AnyIO 弃用警告                                                                                                      |
| 实际环回 HTTP                                     | Uvicorn 随机本地端口：无 cookie 401，真实 session 200，确切 snapshot 身份及 no-store；结束停服务                                                              |
| 只读与并发                                        | 实际 RR READ ONLY 拒绝 UPDATE，主要业务／命令／operation／模型／审计／来源／实交计数不变；读取后并发保存不会混入同次观察，下次读取才显示 changed              |
| 原稿反例                                          | 24 万字符合成长正文完整相等、原生合并表格、确切图片版本、来源与图片撤回、零章、旧稿不被新稿代替、错项目 ID、缺章节绑定、重封假身份／重复／未知字段            |
| 构建反例                                          | 实际 Worker 生成 Word；无转换配置时 PDF 明确失败；另一构建不补文件；原生 writer 变化失败显示 not_published；错 snapshot／错输出／缺原生发布凭据全部拒绝       |
| 目录反例                                          | 四阶段真实选择与 resolver 一致、多个运行、旧核查选择、单正文实交不混入整包、无关联为空、签名分页无重复、分页新增和 operation 变化拒绝续页、预算和参数明确拒绝 |
| 官方数据边界                                      | 存在官方技术总分 0 时撤销相关官方表 SELECT，整包实交目录及精确解析仍成功，响应没有官方记录或分数口径                                                          |

首轮真实候选为 21 通过、3 失败。三个失败来自两条目录 SQL 错把 `bid_id` 放在 `bid_package_revisions`；该归属实际在 `bid_packages`。已改成明确项目包到修订的原生 JOIN，再补缺绑定／错误发布证明反例，最终固定候选 28 全过。未以测试替身替换 SQL，也未放宽校验。

只创建全新的临时 PG 集群、随机回环端口及新非 owner 运行账号，结束已停库；没有连接旧业务库。合成原件和模型响应只用于建立真实原生历史，产品读取被禁止访问 storage／模型入口。没有外部付费调用。该证据验证软件机制，不代表真实标书、Word/PDF 视觉质量或正式预测效果通过。

复现测试：

```sh
python -m pytest -q --tb=short tests/test_work_context_catalog.py tests/test_work_context_catalog_pg.py
```

PG 用例仅在显式的 `FUSION_REQUIREMENTS_ADMIN_DSN` 一次性新集群配置下运行，未配置时的 skip 不算通过。本次 runner 在 `/tmp/tender-review-work-context-catalog/run_pg.py`，启动前后均校验 `candidate-manifest.json` 全部固定源码摘要。

## 5. 冻结范围与未覆盖项

本批 11 个源码／测试文件及 SHA256、复现命令、权限列表、收据引用均在 `work-context-catalog-checks.json`。本验收文档和该 JSON 为独立新增证据文件。没有修改 A 的冻结文件、主 router、实际导出生成器、共享 UI 或已有域模块；没有 Git stage／commit 或远端操作。

主应用／前端完整集成、真实浏览器四阶段选项操作、可访问性与迟到响应恢复由根批次验证。本批不把后台目录等同前端完成，也不把只读摘要等同六级主要业务动作完成。原图字节重核、真实受控 PDF 成功及真实资料效果均不属于本次只读后端验收；产品能如实返回现有记录和限制，不因缺这些外部材料而省略可实现的软件路径。
