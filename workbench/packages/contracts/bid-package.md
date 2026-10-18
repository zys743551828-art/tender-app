# 整份标书资料包领域契约

本契约对应融合任务 F01-01—05 的首批领域实现，版本 `bid-package/1`。纯模型位于 `packages/domain/bid_packages.py`；结构契约位于 `schemas/bid-package.schema.json`，其中 `$defs.requirement`、`$defs.coverage` 可独立引用。首批存储已接入真实主数据，稳定标段身份目录／关联 API 与受限非 owner 存储已在独立 PG17 验证；整包创建、追加修订、当前与历史读取 API 已接入该存储，资料页已接整包发现与明确选择原件／解析／逻辑范围的编辑组件。**整包上传编排／评审／实交 API、Worker 业务编排及全流程前端联动尚未完成，不能据此宣称 F01-08 全链验收通过。**

## 整包存储 API 首切片

实际接口与请求／响应 Schema 位于 `apps/api/bid_package_routes.py`、`packages/contracts/bid_package_api.py`，均在现有 `/api/v1` 登录会话内运行：

| 方法 | 路径（省略 `/api/v1/bids/{bid_id}`） | 语义 |
| --- | --- | --- |
| POST | `/packages` | 明确选择已提交文件版本，建立新包首修订，返回 201 与当前包 ETag |
| GET | `/packages/{package_id}` | 当前 head、冻结 manifest、冻结身份与 head ETag |
| POST | `/packages/{package_id}/revisions` | 完整替换成员选择的新修订；必须精确 `If-Match` 当前 head |
| GET | `/packages/{package_id}/revisions/{revision_id}` | 包与业务范围限定的不可变历史及当时冻结身份 |
| GET | `/packages/{package_id}/revisions/{revision_id}/manifest` | 保存 manifest 的规范 UTF-8 JSON 字节；SHA256 与 `X-Manifest-SHA256` 相等 |
| GET | `/packages` | 以包 ID 稳定分页列当前 head 摘要，可按 kind 筛选 |
| GET | `/packages/{package_id}/revisions` | 按修订号倒序分页查历史入口，不重造历史内容 |
| GET | `/package-documents` | 按 kind 列本项目所有已提交原件版本，不限当前资料快照／单正文指针 |
| GET | `/package-documents/{document_version_id}/parses` | 分页列精确 run 身份、时间、页数、coverage 和 gaps，不推断最新 run |

发现接口均需登录，以 `limit=1…100` 和不透明 `cursor` 分页。签名游标绑定目录种类、bid、包／文件范围及 kind 筛选，错用或篡改返回 `422 INVALID_CURSOR`；不存在的范围返回 404。目录只返回已存记录，不建立替代包、不写单正文指针。文件目录的 `verified_upload` 只说明当前已匹配核验上传依据，不能代替正式来源资格；parse 的 complete／partial／failed 是原记录 coverage，complete 不证明实际页完整性或正式冻结资格，保存仍执行仓储核验。

写入请求必须有 `Origin`、`X-CSRF-Token`、`Idempotency-Key`；追加缺少 `If-Match` 返回 428，ETag 已过期返回 412。同一 actor／命令／目标／幂等键的相同内容重放返回原 ACK 与 `Idempotent-Replayed: true`，不同内容返回 409；重放不回退当前 head。新包和追加修订均复用现有生命周期写入守卫，closed／terminated／archived 拒绝新工作，旧 ACK 与历史仍可读取。此处沿用当前应用会话权限，不引入新的工作区或多租户权限体系。

请求只能提交 kind（新包）、有序 members；每个成员只允许 `member_id`、`document_version_id`、可选精确 `parse_run_id`、`purposes`、`parts`。服务端从真实 profile 与 `bid-identity/2` 派生工程／稳定标段／轮次／主体，派生已提交文件的角色、字节摘要与来源引用，并匹配已有 verified upload 的角色／摘要／大小。权威包仅允许 tender／supplement／drawing／boq 的 source_original；本方包仅允许 body 的 bid_body。official_result、other、非原件、未提交版本、未核验上传以及已知包含 official_label／post_outcome／derived_mixed 的来源或祖先均拒绝。当前效力与发布授权的新评审资格仍由后续来源门禁决定，不能从这里的存储成功推导。

新 API 的开放文本（成员 ID、用途、逻辑部分 ID 与分类）在 Schema 与实际请求校验中均拒绝 NUL 和孤立 Unicode 高／低代理码位；返回非 retryable 的 `422 INVALID_REQUEST`，在登记命令／包之前失败。合法中文与非 BMP 字符可原样保存。此输入边界不改变冻结的旧纯模型／评审 hash 或历史协议。

新写沿用来源模块的事务锁 `sources.lock_graph()`；顺序为 bid／生命周期 → 来源图 `90127,1` → 成员文件／解析。来源图先写时 API 等待锁释放后以 READ COMMITTED 新快照检查新增祖先，不使用等待前的政策判断；只保护已知来源政策隔离，不代替正式来源效力资格核验。

未提供 parse_run_id 时明确保存 `not_frozen`、未知页数与空 parts，即便已有其它成功解析也不推测选择。指定解析时核真实 run、完整物理页与证据身份；失败／缺页解析不可冒充正式精确冻结。完整合订本可指定多个逻辑页段，分册以多个明确成员保存；不会自动选择最后一个 body，也不改 `current_body_id`。不同主体／标段／轮次必须建立新包；旧包当前 head 和历史身份仍按原冻结值读取。API 的 `storage_eligible` 只表示纯模型存储条件，`review_ready` 固定 false，不表示效力、合规、评分或实交就绪。

manifest 端点不读取当前资料或当前身份重造历史，而是验证持久化 manifest 并按同一 canonical 协议编码，摘要与原冻结摘要相等；JSONB 不承诺保留上传请求的空格和键顺序。历史 identity 响应使用严格 v1／v2 union，不给旧 v1 快照补 stable lot 或改摘要。`tests/test_bid_package_api.py` 在专用临时 `fusion_package_api` 上执行完整 BASE_SQL，使用只继承 tender_api 的 `fusion_package_service_api` LOGIN 与真实登录／CSRF／ASGI；合成库记录不等同于真实 OSS 上传、OCR 准确率或整包评审验收。本切片无新 DDL，也不改变已记录 SQL 指纹。

资料页独立组件 `apps/web/src/BidPackages.tsx` 提供两类包目录、当前／历史重开、文件版本与精确解析分页发现、用途／逻辑页段／共享范围编辑及规范 manifest 下载。默认不冻结解析；选择明确 run 后才可划逻辑范围，切换 run 清空本地旧页段而不改服务器历史。用途支持中文资格／商务／技术／报价／附件及自定义，输入原文保留分隔符。旧历史编辑明确重读当前 head，不把旧历史 ETag 当当前基线；412 保留本地选择，读取并展示最新记录后需用户明确采用其基线，再另行保存。网络结果不明的相同请求沿用原幂等键，不自动重试。切项目后旧异步响应不能覆盖新工作区。已归档／结束项目仍允许历史读取，新写由界面与服务器生命周期守卫共同阻断。组件行为测试为明确合成 HTTP fixture，不代替真实浏览器、上传或评审链验收。

## 身份与现有结构

现有 `contracts/sql/domain.sql` 的 `engineering_projects`、`bid_rounds`、`bidders`、`bid_profiles` 保留业务概念；原 `bid_rounds.lot` 是文本，`bid_profiles.current_body_id` 仍为单正文。新 `BidScope` 显式冻结工程、稳定标段 ID、轮次 ID、`bid_id`、本方 `bidder_id` 及其核验状态。新增 `sql/bid-packages.sql` 给真实工程增加 `engineering_lots`，真实 `bid_rounds` 以复合外键绑定 `lot_id`，并以工程＋稳定标段 ID＋轮次号唯一；同标段换显示别名不能重复造同轮次，不同稳定标段可以同名。原文本唯一仅保留为 `lot_id` 为空的过渡部分索引，标签不作新身份主键。身份 API 已支持显式登记工程／标段／轮次与按 ID 选择；未明确标段的草稿仍允许 `lot_id=null` 并保持 pending，不生成假标段。存储入口核对真实 profile／轮次／主体及绑定依据，整包新写拒绝未登记稳定标段的轮次。领域检查与外键都不能替代服务器授权。

权威包是在此本方投标范围下选择的招标文件、补遗等依据，不表示招标文件的发布主体是投标人。`source_kind=authority` 与本方 `source_kind=own` 在不同包中；成员携带 `source_ref`，来源发布者、效力和当前授权仍由来源效力模块校验。模型不会从最后上传时间或最后一份 body 推断整包成员。

`bidder_status=pending` 允许记录待核范围，`require_formal()` 拒绝正式新用。相同显示名称不会消除主体、标段、轮次、工程 ID 差异。

## 不可变修订与解析

- 一个包修订持有有序成员元组。成员冻结文档版本、字节 SHA256、用途、来源、范围、原物理页数、逻辑部分与解析身份。成员、文件版本和逻辑部分 ID 分别唯一；共享附件只保存一次物理成员，多条要求可引用同一逻辑部分。
- `next_revision()` 使用新修订 ID，增加修订号，并冻结前修订摘要。替换成员、改变用途、顺序、逻辑范围或解析证据都产生新摘要；原值对象与旧报告摘要不变。防止跨请求重用 revision ID、保证父修订真实存在与 CAS 前进等约束已由仓储及整包 DDL 执行。
- 精确解析身份包含 `parse_run_id`、`parser_digest`、`config_digest`、`evidence_digest`。同字节订正必须产生新的解析身份和新包修订，不能改写旧解析输出。
- 同一包内 `parse_run_id` 不可重复绑定不同文件版本；文件版本本身也不可重复。`next_revision()` 保持已有 run 的文档版本、字节摘要、原页数、解析器／配置／证据摘要一致，订正必须使用新 run ID。跨任意包和全部历史修订的全局 run 唯一约束已由解析存储及数据库注册表执行；值对象不能替代持久化身份注册表。
- `not_frozen` 仅记录缺失原因，其他解析字段必须为空。它不是 `pending_parse` 的同义词，不能根据时间猜一个旧 parse ID；也不能正式使用。新包摘要不冒充旧协议的历史摘要，旧 manifest 原文及其哈希必须原样保存，历史兼容读写与证据取回仍属于 F01-07/F03-05 后续工作。
- 摘要复用现有 `review_identity.digest()` 的规范 JSON 子集；不更改 `review-content/1` 固定向量。数组顺序有效，浮点数不进入包协议。
- 所有整数取值不得超过 `9007199254740991`（`2^53−1`）：包修订号、原件页数、逻辑页段两端、标题路径的每个数字、要求最低数量及受检页段两端。构造时即以相应 `PACKAGE_*` 错误拒绝越界／布尔值，Schema 同步 maximum，避免先接受值对象、直到计算摘要才出现底层 `unsafe_integer`。

## 合订本、分册与受检范围

逻辑 `DocumentPart` 用开放的项目自定义 `category`、`part_id` 及一基物理页闭区间定位；不强制五册。一个 PDF 可以有资格、商务、技术等多个部分；同类别多个文件共同覆盖一项要求。解析 `heading_path` 是无固定深度上限的正整数元组，与手工编辑树六层限制分离。

同一物理文件内逻辑部分重叠，只有重叠双方都显式声明 `shared_attachment=true` 时允许；该声明是可核验的人工划分，不能绕过要求范围核验。边界超过原件页数、倒序、页零和布尔页码均拒绝。

加密、损坏或待解析原件可以记录 `page_count=null`、`parts=[]`、`parse.status=not_frozen` 及具体原因，不能补假页码或假逻辑部分。原页数已知但尚未划分逻辑范围时，同样可保留空 parts 与未冻结解析身份。这些成员可以进入不可变包清单，但阻止正式使用和整包覆盖完整；未知页数时不允许提供任何 part。覆盖结果 `member_gaps` 返回原成员及 `page_count_unknown`／`parts_unassigned`／`parse_identity_not_frozen`，能力不支持可返回 `unsupported`，不会因没有 part 而从缺口清单消失。

要求可显式选择多个 part ID，或选择类别下的全部部分。页面子范围通过创建明确的逻辑部分表达；页码不是屏幕滚动位置或打印页标签。核验结果返回每项实际受检的文档版本、part ID 和原物理页段。只有所有目标页段都被覆盖才能标记 `verified`；跨页断口不能通过。

## 要求、适用性和覆盖

要求区分 `authority`、`company`、`manual`，均保留依据引用。可登记最低材料项数（`null` 未知，`0` 是明确的零）、条件、核对项目、适用时点与范围。`checks` 可记 `quantity`、`expiry`、`signature`、`format` 等检查声明；具体数量、期限、签章／格式的证据判定由后续检查器负责，不能以文件数量代替材料项数。

适用性为 `applicable`、`unknown`、`not_applicable`。不适用要求必须有适用性依据；核验结果另有依据引用。未解决的适用性不能输出 `verified`。

每条要求另有不可变规范 manifest 和 `bid-requirement/1` 摘要，覆盖结果同时冻结 `package_digest` 与 `requirement_digest`。要求 ID 相同而来源补遗、检查项目、最低数量、适用时点／条件／范围变化，也不能复用旧 verified；`PACKAGE_COVERAGE_REQUIREMENT_STALE` 明确要求重核。结果返回每条要求实际摘要，旧要求的值对象、摘要及核验结果可照原身份复查。后续规则包存储负责固定完整要求清单及其来源效力，不能仅凭调用者送一个现时要求 ID 作为历史证明。

| 覆盖状态 | 含义 |
| --- | --- |
| `not_provided` | 未提供，尚未认定应提供的缺件 |
| `missing` | 已有适用要求但缺件 |
| `pending_parse` | 文件在场，尚待解析 |
| `parse_gap` | 解析存在缺页或质量缺口 |
| `unsupported` | 当前检查能力不支持 |
| `verified` | 声明的要求目标范围已经核验，有依据 |
| `not_applicable` | 有依据不适用 |
| `conflict` | 范围或依据冲突 |
| `unknown` | 未有足够结论，包括未返回该项结果 |

`assess_coverage()` 仅判断覆盖是否完整，不是材料合规／废标风险通过，更不是投标平台接受。完整覆盖同时要求：非空要求清单、调用方显式声明要求清单已完整核实、正式包身份、每项有核验或不适用依据且范围充分。默认要求清单完整性为 false；空检索／空清单不会自动绿灯。结果绑定确切包摘要，新包拒绝旧结果。

结构 JSON Schema 拒绝额外字段和未知枚举；跨对象 ID、顺序、范围包含、来源隔离、完整性和摘要等关系必须执行纯领域校验。后续 API 需要同时完成 DDL/OpenAPI/前端类型与错误响应，不得仅通过结构校验绕开领域约束。`PackageError.code` 为稳定 `PACKAGE_*` 码；当前不替旧 API 选择 HTTP 状态。

## 本批验证和后续边界

`tests/test_bid_packages.py` 覆盖单 PDF、多册、缺册、共享附件、跨主体／标段／轮次、补遗追加、同字节解析订正和旧包重开九类，并增加未知枚举、不适用、空清单、深标题、重叠和结构契约反例。独立评审发现的同 ID 要求偷换、parse run 跨文件重用／跨修订改写、未知页数／已知页数待分段及全部整数边界均有正反例。测试不连接业务库，不读取密钥、不调用模型。

下一步依赖：正式角色与接口授权、来源效力及所有发布入口重核；F01-06 去单正文中心；F01-07 旧 manifest 原样保留与新摘要影响链；F01-08 实际接口、前端类型与错误码一致验收。业务通过、分数和提交闸门仍由各自领域规则判定。

## 首批持久化协议

`save_revision(connection, package, expected_digest=...)` 使用调用方连接与事务，不读取业务配置或另行连接库。写入限定 `READ COMMITTED`，先按既有身份模块顺序锁实际 bid，再检查真实 profile、工程、稳定标段、轮次和主体；不新增可写的身份确认状态。身份模块、仓储与数据库守卫共用 `identity_association_v2()`／`identity_snapshot_v2()`，`confirmed` 必须由最新 `identity.bound` 标明 `identity_version=bid-identity/2`、其 `after`（包含真实 `lot_id`）与当前 association 全量一致，且有原主体登记审计支撑。旧绑定缺稳定标段身份只保持历史可读，新用 pending，不按当前轮次补造当时的精确冻结。包修订额外冻结 `identity_snapshot`、`identity_authority_id`、`identity_digest`；pending 快照也保留当时实际名称和范围，不能只靠旧 authority 或当前 profile 重建。

一个包固定其工程、标段、轮次、本方主体和类型；当前 profile 改绑后，旧包可读和同键历史重放，新写须重新建立相应范围的包。头表以锁与 `expected_digest` 做 CAS，修订号、前修订摘要与头同时前进；同 revision ID 与相同内容重放返回原结果，不把当前头回退。相同 ID 不同内容拒绝。修订、成员、逻辑部分、解析绑定与工程标段为不可变记录；数据库检查成员／部分必须逐项对应 manifest，延迟约束要求提交时所有成员／部分齐全。规范 JSON 和 SHA256 由数据库独立核算，字段缺失、JSON null、错误类型不能靠 SQL CHECK 的 UNKNOWN 通过；数据库行 ID 与 manifest ID 必须一致。

精确解析取指定 run，不按最新时间选择。冻结前核真实文件字节摘要、run 的文档版本／解析器／配置、实际原页及证据文字 SHA；以 `package-parse-evidence/1` 将排序的 pages／blocks 构成证据 manifest。几何、结构及缺口 JSONB 使用 PostgreSQL 原文字符串进入规范协议，避免浮点数进入身份摘要。SQL 与 Python 使用同一规范 JSON，新增绑定的直接 SQL 同样核实际解析与证据摘要。run 冻结后禁止迟到追加原页／证据；订正用新 run，新包修订引用新身份。

该存储切片只接受 `coverage=complete`、原页 1…N 齐全、每页 usable 且没有解析／页缺口的正式 frozen 输入。failed／partial／缺页原件仍可通过 not_frozen 加原因保存；“精确冻结 partial 身份同时保留不完整资格”需要后续扩展模型，不能把现有身份精确误当解析完整。纯模型构造本身不能核数据库解析质量，实际业务必须经存储及后续输入资格核验。

`load_revision(connection,bid_id,revision_id)` 校验保存的结构及摘要后恢复原值对象，损坏数据返回 `PACKAGE_STORED_MANIFEST_CORRUPT`；`load_frozen_identity()` 返回保存时的完整身份快照及摘要。两者不以当前 profile 覆写历史。API 对新用／重用仍须重核当前身份与来源资格，不能把历史重放当作新用授权。

首批仓储在专用 `fusion_package_repo` 临时库按以下已审依赖初始化。真实非 owner／身份 API 验证还在专用 `fusion_package_acl`／`fusion_identity_api` 库按 `bootstrap_fresh.BASE_SQL` 加载检索、运行权限等基础 SQL，见[运行权限说明](../../docs/bid-package-permissions.md)；没有运行归档 WIP SQL，也未修改业务部署：

| 顺序 | SQL | 首批验证时 Windows 原文件 SHA256 |
| --- | --- | --- |
| 1 | `sql/core.sql` | `accb37248ba097d0992924b4977786932f167b04c105031b4e6acc3be698e098` |
| 2 | `sql/domain.sql` | `c8a1a595b6b855bdfe80671dd5719ed9c7f752d5f7b7f7d9ae8f153d286e115a` |
| 3 | `sql/bid-packages.sql` | `f18cbd9a22cdcb3f1d3229d0e43b3ad4b0ff3568f4b160787e0c4572b6f9c319` |
| 4 | `../identity/sql/stable-lot-identity.sql` | `3d4775a72daa3fd1c813aab72212e9aefdf5e5ef5aa22eb0c83db2cd580b3738` |

上表保留当时执行输入的 Windows 原文件字节摘要；当前活跃 SQL 已锁定 Git LF。Git 规范字节摘要与原 Windows 字节摘要的映射见 [`docs/fusion-sql-input-bytes.json`](../../docs/fusion-sql-input-bytes.json)，不把换行规范化当成 SQL 行为修改或重写旧验证预期值。

`tests/test_bid_package_repository.py` 使用真实既有主体登记／绑定函数与原始 core／domain 主表，覆盖两类包、跨范围、历史重放、身份更正、pending 快照、同字节新解析、未知页数、直接 SQL 伪造、延迟完整性、数据库不可变守卫、双连接 CAS 及撤销后的旧隔离快照。测试账号为专用临时库 owner，用于关系／事务机制验证，不代表正式非 owner 权限、实际 API 或整包业务已验收。

`tests/test_stable_lot_identity.py` 另用真实 API LOGIN、main ASGI、登录／会话／Origin／CSRF、幂等、关联 ETag 与 SQL 双连接阻塞反例，核对“工程→稳定标段→轮次→profile→binding v2→资料包”的闭环。读取函数采用 VOLATILE，使触发器等待 bid 锁后重新取得当前数据库快照；不能以旧 INSERT statement snapshot 通过新身份校验。身份更正保留旧绑定和旧包，历史实交及知识引用的冻结身份响应使用显式 v1/v2 union，旧摘要与旧字节不变。API 目录身份登记不代表资格核验，收费模型消费者与整包业务另按其验收门放行。
