# F06 精确整包技术范围、资格与满分接线验收

日期：2026-10-21。源码基线为 `65433caebe5385c4bb0c6546fe53479c2cdefd86`；本记录描述该基线上的本轮未提交检查点，最终交付 SHA 由总集成人员记录。产品计划以 tender-docs `13bfcf194f997c68216179bec72ab657d517d734` 的 F06 为准。

## 结论与实际边界

已形成可运行路径：选择确切技术章节及全部已识别评分条款 → 查看完整原页和缺口 → 原件逐一核验 → 冻结不可变范围和命令回执 → 重读当前资格 → 显式关联有据满分或实际提交／官方标签。范围 API、SQL 守卫和两类上下文在真实 PostgreSQL 与真实认证 ASGI 中通过；素材和对象运输为显式合成。可选量尺扩展提供实际登记、确认及失效重查；没有借条款和或官方分数填满分。

该检查点不关闭整个 F06。范围声明仍缺规则穷尽、完整图表阅读和全部必要范围的独立权威；专用整包评分生产者、正式数值预测、严格研究样本准入与训练资格尚未开放。完整性和执行字段在闭合协议及数据库中固定为 `false`。三判断要求已在资格上下文明确，但此检查点没有创建判断任务、判断成功记录或费用。

| 已验行为 | 关键反例／限制 |
| --- | --- |
| 确切包、权威包、清单、技术子范围及方法共同冻结 | 不拿最新解析、首个包成员、聊天摘要或检索片段替换正式输入 |
| 全部成员、已声明章节、物理页、原块、表格结构、未选范围和排除条款保留 | 数量／字节超限整件拒绝，不截断正文或分页漏分母 |
| 全部直接原件和来源祖先核验，外部读取时无数据库事务／锁 | IO 失败、字节变化、并发来源变更及实交状态变化不落范围记录 |
| 原成功回执幂等优先，范围／审计／回执同事务 | 同键换请求冲突；缺审计、假回执、篡改范围和自授资格被 SQL 拒绝 |
| 当前评分上下文重新核对身份、包头、清单、生成稿及来源 | 已实交、撤回或改版后不显示可继续评分；旧 scope 可原样读回 |
| 量尺显式选择、完整原文与冻结权威 parse／来源 revision 精确绑定 | 不选则未知；未装扩展则 `not_configured`；权威改变则满分 `null` |
| 实交、官方技术零分及原核验可准确关联 | 零分保留为零；综合分／未知不作为技术标签；结果不能反推分母 |
| 历史输入检查原冻结早于实交及来源当时效力 | 当前转换、晚登记范围不冒充当时已存在；研究冻结／分割／标签截止不补默认值 |

## 集成点与协议

共同基址为 `/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}`。

| API | 响应契约 | 用途 |
| --- | --- | --- |
| `GET /technical-scope-context?inventory_id=...` | `PackageTechnicalScopeContext` | 选择上下文及强 ETag |
| `POST /technical-scope-previews` | `PackageTechnicalScopePreview` | 全量只读预览 |
| `POST /technical-scopes` | `PackageTechnicalScopeApplied` | 原件核验后的 201 命令回执 |
| `GET /technical-scopes` | `PackageTechnicalScopePage` | 分页历史摘要 |
| `GET /technical-scopes/{scope_id}` | `PackageTechnicalScopeView` | 不可变完整记录 |
| `GET /technical-scopes/{scope_id}/scoring-context?scale_id=...` | `PackageTechnicalScoringContext` | 当前用途，不读取官方标签 |
| `GET /technical-scopes/{scope_id}/sample-context?submission_id=...&outcome_id=...&scale_id=...` | `PackageTechnicalSampleContext` | 独立历史关联；输出始终 pending，不创建样本 |

`scale_id` 和 `outcome_id` 可省略，服务不会暗取某个最新版本。所有身份参数使用 UUID。只读响应带 `private, no-store` 和绑定当前资格的 ETag；观察时钟单独展示，不因每次读取时间不同产生假版本。范围预览和历史使用 RR／RO；资格上下文为协调现有量尺 `current_version` 只读 RPC，按治理→项目→来源图顺序使用短 READ COMMITTED 锁，没有业务写入。

两个路由分别是 `apps.api.package_technical_scope.router` 与 `apps.api.package_technical_eligibility.router`。OpenAPI 扩展分别为 `packages.contracts.package_technical_scope_api.extend_openapi` 和 `packages.contracts.package_technical_eligibility_api.extend_openapi`。实际主装配、生成 TypeScript 与浏览器验证由根集成任务负责。

## SQL 与权限

`packages/contracts/sql/bid-package-technical-scopes.sql` 已接 BASE，顺序为统一整包实交之后。SHA256：`06d17e3cb0833177585a3d08252b0d8717494eef843fc1225ffcc97df599ea46`。需要官方 `uuid-ossp` 1.1 安装于 `public`，API 仅使用所需 UUIDv5 函数与最小表／列权限。Worker 无该范围表读写权，没有新增评分或研究执行权。

可选 `deploy/sql/technical-scale-package-identity.sql` 置于 `technical-scale-authority.sql` 后，不放进默认 BASE。SHA256：`432f123552b6f7033a8e3fa88b83b38b697d5406e9b3c4a2ea60b533176b1691`。它修复原量尺 v1 完整身份比较缺少 `lot_id` 而拒绝所有新 v2 项目的问题；用 `identity_snapshot_v2` 对含 lot、主体、轮次、工程、权威记录、版本及摘要的完整快照做全等比较，并要求明确 confirmed。旧值不回填、旧记录不改写、历史单正文分支保持原条件，未授整包历史资格。`scale_contracts.py` 保留旧身份只读分支并增加完整 v2 分支，避免真实响应与 OpenAPI 不一致。

## 验证命令与结果

Python 使用 `/tmp/tender-review-venv` 的既有环境，没有修改旧环境依赖。每套原生测试使用新的本地集群、随机端口、独立 API／Worker 非 owner LOGIN；owner 仅初始化和合成夹具准备。实际对象内容为测试字节，模型调用与付费次数均为零。

| 检查 | 结果 |
| --- | --- |
| `pytest -q tests/test_package_technical_scope.py tests/test_package_technical_eligibility.py tests/test_scale_authority.py` | 117 passed，3.11 秒（42 + 30 + 45） |
| `tests/test_package_technical_scope_pg.py`，最终 BASE 安装与方法摘要 | 29 passed，84.07 秒 |
| `tests/test_package_technical_eligibility_pg.py`，BASE-only | 4 passed，18.04 秒 |
| `tests/test_package_technical_scale_pg.py`，必要可选登记权威 | 5 passed，20.03 秒；4 个真实 PG 场景和 1 个历史分支不放宽核对 |
| 10 个实现源文件 mypy，`--follow-imports=silent` | 无问题 |
| 15 个实现／测试文件 Ruff + format check | 通过 |
| 10 个实现源文件 Bandit | 通过 |

原生测试均有同一个第三方 Starlette／AnyIO 弃用告警，不影响断言。第一次旧夹具运行暴露附表 category 与清单映射不一致；已修复合成夹具为 technical，未放宽产品映射规则。真实业务质量、真实供应商执行、外部独立验收和 GitHub CI 不由这些结果证明。

可复现原生测试需要显式 `FUSION_TECHNICAL_SCOPE_PG=1` 和指向独立临时 PG17 的 `FUSION_REQUIREMENTS_ADMIN_DSN`。不得把测试连接指向业务库。范围原生套件默认 BASE；资格套件保留量尺未安装的反例；量尺套件在自身新库内额外安装 model-governance、historical-backtest、technical-scale-authority 和本轮 v2 适配，不安装 retrospective SQL、不启动消费者。

原生 receipt 的内容和源码指纹汇总在 [technical-scope-checks.json](technical-scope-checks.json)。实际 HTTP 回执输出到 `/tmp/tender-review-current/technical-scope-http-final.json`、`technical-eligibility-http.json`、`technical-scale-http.json`；它们含合成材料及真实本地 UUID 命令／响应，未含会话口令、对象凭据或私有对象键。先前 `technical-scope-http.json` 保留原样。

## 后续专用生产者与严格样本工作

下一片应建立独立的整包方法和 owned-job 输入／输出权威，沿用既有预算、发送状态、lease／fence 和当前来源复核；不得给旧单正文 producer 填伪 body_version_id／parse_id。每条适用规则必须接受同一完整冻结输入的三次独立有效判断；失败、无效输出及重试是 attempt，不能充作独立 replicate。未知发送／费用必须阻断自动重发，原判断和账本追加保留。

正式发送仍须真实服务端权威证明规则清单和必要范围穷尽、全部文字／图表阅读完整、当前原字节及祖先有效、方法与供应商能力相符。范围字段中的人工选择不能作为这些证明。缺证明时应该登记拒绝／未发送事实，零模型调用；显式合成端口只验证机制，不把形式化训练资格改为可用。

严格历史样本还需要整包历史主体与每个原件／祖先的存在、本方知晓、生效证明，以及独立研究冻结的历史截止、实交分割、标签可用截止和训练冻结时间。当前上下文只从原记录显示已证实的时间，其余为 `null`。官方标签只在独立关联检查可见，不能进入当前输入、普通 RAG、摘要、缓存或模型请求。

数值评分还缺有据可执行的官方聚合与受控模型发布资格；有据最高分本身不会授权条款求和、三次平均、占比或所谓预测精度。真实配对资料及外部验收单列未验收，不阻塞这些软件机制继续实现。
