# F11 章节任务 B1：固定整包编写输入与准入验收

## 阶段与交付边界

B1 提供独立的输入生产者：用户明确选择两个完整包、要求清单、章节快照和事实集，服务端核验后保存不可变记录。该记录可供审阅、列举、查询当前匹配状态，并可撤回其单项事实的编写用途声明。

本阶段没有接通模型执行、候选发布、正文采用或文件构建。输入清单中的 `generation_available`、`publication_authorized`、`apply_available`、`build_available`、`formal_decisions_allowed` 均为 `false`，数据库也检查这些值。后续 B2/B3/B4 必须分别取得实际 job、action、section revision 和 build 的受保护绑定，不能把 B1 清单或 Python 类型作为执行许可。

新增 schema 为 `packages/contracts/sql/authoring-package-inputs.sql`。它不在 `BASE_SQL`、默认预览或默认恢复计划内。只安装 BASE 时，能力返回 `capture_available=false` 和 `AUTHORING_PACKAGE_INPUT_NOT_CONFIGURED`；新 router 的实际主应用挂载、共享 OpenAPI 与类型生成由集成负责人统一处理。

设计依据为同目录 `exact-package-authoring-design.md`。本次实现的关系是 `draft_using_package_context`：使用明确选择的完整包上下文，为指定草稿章节提供后续编写基础；它不声称章节属于所选包，也不推定草稿与包的对应关系。

## 实际输入身份

| 范围       | 保存与核对内容                                                                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 两个完整包 | target/authority 的 package ID、revision ID、digest、实际类型、完整 manifest、身份快照和全部逻辑成员                                                    |
| 明确解析   | 每个成员指定 parse ID、parser/config/evidence digest、原件 SHA256 与大小、全部物理页、全部证据块及 PostgreSQL 精确几何文本                              |
| 原件资格   | 实际 verified upload 与文件用途、摘要、大小一致；`bid_body` 标签本身不表示生成物；真实 `build_outputs` 成员在 B1 明确不支持                             |
| 要求清单   | 指定 inventory ID/digest、规则集、全部规则/决定、原生抽取输入/操作/结果/效果回执；支持既有更正链的核对                                                  |
| 事实       | 显式 fact set ID/head revision、五项身份事实、明确选用的业务事实、原确认 basis/沿用链、证据与完整来源闭包                                               |
| 事实用途   | 新协议 `authoring-package-fact-scope/1`，目的固定为 `authoring`，绑定本输入、事实内容和证明摘要、工程/标段/轮次/投标主体之一，以及 actor/command/reason |
| 章节       | draft/snapshot/section revision 的真实关系、内容/schema/digest、稳定目标节点与 before digest；快照中的所有章节和结构身份                                |
| 来源与时间 | 确定性 parse source → original source 的实际边；所有祖先、状态、政策、known_at/valid_from/valid_until，以及最终事务的再次核验                           |
| 方法       | 明确协议、32 MiB 完整上下文保存上限、全量策略、禁止隐式选源，以及准入相关 Python/SQL 的 SHA256                                                          |

事实声明不证明事实为真；原确认依据、证据完整性、来源效力和主体对应仍须同时核验。既有 `prebid_compliance` 事实声明不会被转换成 `authoring` 声明。五项业务身份按既有 `intent_identity.association_key` 规范化，便于后续继续使用同一费用防重边界。

完整性是读取并保留明确包内的全部成员、页和块。输入不经过 RAG 排名，不取前若干条记忆，也不从当前资料或最新 parse 补足。超过保存容量时整体拒绝，不产生截断后的输入。

## 保存事务及数据库约束

保存步骤为只读 REPEATABLE READ 观察 → 关闭事务 → 实际 S3 原件流式 SHA256/长度核验 → 新只读快照重读并比较 → READ COMMITTED 最终提交。最终事务先核对原幂等命令，再锁 bid、draft、来源图及按顺序排列的祖先 head，重新读取同一组明确 ID，最后重查登录资格，原子写入输入、事实声明、审计和成功回执。

原件读取不持有数据库事务。PostgreSQL 负责数据关系和当前状态核对；它本身没有读取 S3 字节。原件核验结果不会被当作无限期许可，后续执行阶段仍须重新核验。

两个表仅给 API 角色 SELECT/INSERT，禁止 UPDATE/DELETE；Worker 在 B1 不获得新表读取或写入权。延迟约束在提交时检查实际 package/parse/upload、全部页块、当前 inventory/rule decision、事实头与内容、五项身份、主体、章节节点、来源闭包、计数、命令请求摘要、actor、ACK 和审计。重复或遗漏的事实、来源祖先不能凭相同总数通过。

`VerifiedPackageInput` 是服务内部编程接口，不是数据库权限。验收明确绕过该 Python 对象的可信假设，伪造上下文并重新计算所有外层摘要，确认普通 API 数据库角色仍被 SQL 约束拒绝。对象存储核验则由受控服务承担，不能从 SQL 插入记录推导其真实性。

## 已实现接口和契约接线清单

独立 router：`apps.api.authoring_package_inputs.router`，prefix `/api/v1`。

| Method | Path                                      | 行为                                                                                     |
| ------ | ----------------------------------------- | ---------------------------------------------------------------------------------------- |
| GET    | `/authoring/package-input-capabilities`   | 返回独立存储是否配置；B1 其余能力均为 false                                              |
| POST   | `/bids/{bid_id}/authoring/package-inputs` | 严格显式选择、实际原件核验、保存与幂等回执                                               |
| GET    | 同上                                      | 有界、签名游标分页                                                                       |
| GET    | `.../{input_id}`                          | 读取不可变输入清单                                                                       |
| GET    | `.../{input_id}/context`                  | 读取完整业务上下文；移除对象 locator，并明确列出 redacted fields 和原存储 context digest |
| POST   | `.../{input_id}/check`                    | 仅核对当前数据库身份与资格，不重新读取原件，不授权执行                                   |
| POST   | `.../{input_id}/fact-withdrawals`         | 只追加该输入的事实用途撤回事件；项目结束后仍可撤回                                       |

建议实际契约生成器加入以下根类型：`PackageAuthoringInputRequest`、`PackageAuthoringInputCapabilities`、`PackageAuthoringInputView`、`PackageAuthoringInputPage`、`PackageAuthoringInputContext`、`PackageAuthoringInputCheck`、`PackageAuthoringInputStatus`、`PackageAuthoringFactWithdrawal`、`PackageAuthoringFactScopeView`。

`check.current_input_matches=true` 只表示数据库观察仍匹配。响应始终带 `original_bytes_reverified=false`；不能把它显示成“原件再次核验成功”或“可生成”。`context` 返回的内容已经移除了 locator，不能对该展示内容直接计算完整存储摘要；响应将 `stored_context_digest` 和 `redacted_fields` 分别列明。

## 验收环境和证据性质

最终本机运行结果为 **30 passed，0 failed，0 error，0 skipped**，测试耗时 **110.796 秒**；PostgreSQL **17.11**。原生回执确认源码与 SQL 在运行期间保持一致，已关闭本次创建的 PG/S3 服务，付费模型调用为 **0**。

复现入口为 `deploy.authoring_package_input_acceptance`。运行器要求明确的本地 PG17 和 SeaweedFS 二进制，每次创建新私有目录、新库、新 API/Worker LOGIN、新随机 loopback 端口和仅合成的凭据。退出时关闭自己启动的服务，删除数据库与凭据；不会连接旧库、旧对象存储或付费提供者。

上游文档字节、parse、规则和抽取结果是明确的合成测试数据。测试通过真实 API 角色创建命令和任务，通过真实 Worker 角色记录原生抽取完成关系，但没有运行真实模型抽取，也不证明业务语义相关性、抽取质量或文本正确性。原生抽取回执中的 `quality_status` 为 `not_measured`。本次证明的是输入身份、存储、真实原件 HTTP、事务边界与拒绝机制。

认证使用实际登录、cookie、CSRF 和独立 API LOGIN。原件字节通过真实 SeaweedFS S3 HTTP 读写；没有将 `storage.get` 或 `original_verification.verify` 换成内存成功适配器。竞态测试包装真实核验函数，在核验过程中提交实际来源/事实/规则/项目变更。

运行示例：

```bash
python -m deploy.authoring_package_input_acceptance \
  --pg-bin /absolute/local/pg17/bin \
  --weed /absolute/local/seaweedfs/weed \
  --receipt /absolute/new/authoring-package-input-receipt.json
```

最终结果与文件指纹见 `authoring-package-input-receipt.json` 和 `authoring-package-input-checks.json`。每份原生回执保存实际 PG/Python 版本、S3 二进制指纹、源码指纹、有序 SQL 指纹、逐项测试结果，以及源码/SQL 在执行期间未变化的判定。

### 用例覆盖

- BASE-only 不可用；API/Worker 非 owner 及最小新表权限。
- 完整上下文保存、所有物理页/证据块、五项身份事实及 authoring 声明。
- 原件读取在事务外；保存不新增 operation、outbox 或 model call。
- 原件缺失、同长度错摘要、多一个字节均拒绝且不留半份输入。
- 相同 key 丢 ACK 后原样重放；同 key 不同请求冲突；并发相同 key 只产生一个输入。
- 最终登录资格失效导致整体回滚。
- 核验期间撤源、事实变化、规则决定改变和项目终止，均阻断保存。
- 保存后的上述变化可被 check 识别，历史清单仍可读。
- 没有 revision 变化的自然到期仍阻断保存。
- 新 parse 的出现不会替换或使仍有效的指定旧 parse 失效。
- 用途声明按 input 隔离；关闭项目后仍可追加撤回；不改变原清单。
- 有界目录分页、游标防篡改、错误 bid/digest、CSRF 和无登录访问拒绝。
- 重新计算摘要仍不能伪造少块、错误 parse/节点、事实值、来源、抽取覆盖、重复事实/祖先或隐式选源策略。

## 明确未支持状态

B1 仅支持纯文本稳定 paragraph/heading 节点。富文本表格/图片、导入来源、含章节计划或版式依据的结构、系统构建生成的包成员，会返回具体不支持状态并保留原草稿与原始记录。本阶段不声明这些场景具备 exact 采用或构建资格。

旧 `source_version_ids` 章节任务路径保持其原语义，不会因安装 B1 变成固定整包路径。B2 将通过独立的受保护 job binding 接入原生 `authoring-generate/1`、费用账本和候选发布；B3、B4 再分别证明真实修订采用和后续构建/包追加。输入生产者只是中间检查点。
