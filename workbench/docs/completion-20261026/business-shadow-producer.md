# 真实用途业务镜像 producer 与冻结证据版本

## 本阶段可执行调用链

1. 受控进程显式构造 `package_model_live.host.Host(transactions, enabled=True)` 和既有 `runtime.QualifiedPorts`，调用 `Host.deliver(actor, dispatch_connection, message, qualified_ports=..., expected_method_digest=...)`。默认 enabled=False 即拒绝，HTTP/Kafka 数据不能构造宿主或决定 transport。此包装器调用原有 `material_execution_runtime.deliver`；资格、预算、一次发送、未知计费和结算仍全部走既有实现。
2. 发送前在原生 `captures` 绑定尚无任何 attempt 的业务 job、成员、执行 profile、生产器方法、执行连接 PID/后台启动时间/LOGIN。`Sender.transport is None` 才登记 live；精确 MockTransport 只能登记 synthetic。新触发器只约束已捕获的 job，拒绝其他执行连接冒用该运行；旧历史、已执行任务不可补贴 live 标签。不会修改旧 sender/runtime/方法摘要。
3. 原 dispatcher 返回 qualified_completed 且账本所有槽位完成、held=0、无未知费用、每槽响应有效后，完成受控运行登记。billing_unresolved/blocked 不产生完成证明；镜像登记失败不改主任务 ACK/费用状态、不另发模型请求。重复同一运行可恢复，换 transport/连接/方法不能重新贴标。丢失执行连接后本次捕获不授予新发送权，已有结算仍可完成。
4. 在 final 曝光前，通过 `POST /api/v1/package-business-shadow/models/{model_id}/evidence-binding` 冻结 `score-business-admission-protocol/3`：完整引用已冻结 /2 数值门槛及摘要，另绑定明确 producer/material/observation/route 版本。无默认门槛，不改旧 /2，不允许曝光后补绑定，命令重放只恢复原记录。
5. 受控服务端注入 `app.state.business_shadow_service = Service(NativeTransactions(connection), Executor(private_store, artifact_index), enabled=True)`。`POST /api/v1/package-business-shadow/actions` 接收闭合 activate/observe/rollback 命令。未注入默认 503；没有用户端 enabled/mode/verified 字段。activate 固定两个不同登记模型、原业务 intent、已有完整 /3 私有引用及 evidence binding 摘要。引用不是资格：生产器会对照原任务 seal/input/context、原件、每个槽位的 native attempt ID、请求摘要、原始响应字节摘要和 response ID 逐一复验。
6. 两个短事务之间执行真实 /3 六维投影和既有岭模型推断，**不额外调用 DeepSeek**。提交事务重读当前资格/价格/profile/项目身份/原始来源、固定版本与账本，比较完整准备包摘要；写入既有 `package_model_observation.events`，并原子变更既有 `package_model_route.routes`、追加 `events`。rollback 实际选择并消费固定回退模型；随后 observe 选择回退模型，不允许调用者临时换目标。

本轮没有执行以上真实宿主、配置真实凭据或运行生产数据库。新增 API 的写操作沿用会话/CSRF、现有活跃成员/原生创建者权限，SQL 复用 tender_api，不创建角色或外部账户权限。

## 来源与信任边界

- 历史函数仍只能生成 retrospective_internal；旧事件与旧版本不升级。
- 新 source 的 mode 取自原生捕获记录，模型、输入、响应取自原业务任务和账本。客户端无法通过 CAS origin、上传 response 摘要或 verified 获得 live。
- synthetic 的运行、模型、模拟原生通道不能授予生产资格。测试的 live 分支使用明确的内存权威替身，不写原生 live 事件。最终回执始终 certification_issued=false/formal_eligibility=unavailable，不输出用户业务分数。
- 非 owner API-role 与受控进程代码是信任边界；直接掌握数据库 owner/服务端代码不是本协议要抵御的客户端。连接 PID 加后台启动时间防止旧 PID 复用；控制台不能靠模式枚举重标已经产生的 attempt。
- 真实用途 shadow 路由与正式 business route 不同：本阶段确实运行镜像选择/回退消费的代码，但不写 design.model_routes、不发布或认证模型。后续认证可直接使用已捕获 live 来源的观察事件、相应回退动作、/3 冻结绑定和既有原生 final 报告，不另建证明系统。真实效果仍必须由真实证据决定。

## SQL/部署边界

可选新库脚本 `deploy/sql/package-business-shadow.sql` 安装在 observation/route 与 material qualification/execution 之后、首次观察之前。既有观察表增加受约束的 intent 来源外键，历史 admission 与业务 intent 严格二选一；既有不可变事件链继续使用。新增捕获/完成记录是任务运行来源，新增 business_evidence_bindings 是不可变 /3 协议绑定，不是客户端声明的证明仓库。没有重封存旧 guard 或改旧方法含义。

原生 PG17 环境缺失，脚本没有执行；连接 fencing、锁竞争、数据库回滚/角色和真实账本联合验收必须在隔离 PG17 跑完后才能宣称通过。数据库代码检查不等于 native 验收。完整私有 /3 CAS 引用复用既有 handoff，不由本 producer 额外调用模型来补材料。

## 验证

定向用例覆盖实际 CAS/六维消费、native 槽位/原始响应匹配、模拟 live 正向计算与 synthetic 不升格、请求/响应/原件/版本篡改、默认关闭、HTTP actor/CSRF接线、宿主从 MockTransport 导出 synthetic、未知费用不完成捕获、双事务/撤销/丢 ACK、实际候选→回退→后续消费和旧 revision 拒绝。SQL 源码约束覆盖新旧来源隔离、before-exposure 冻结、连接约束、当前来源、原子事件及无正式资格写入。

剩余有限实现：认证生命周期直接消费上述事件和绑定；随后正式预测持久化/API/UI。缺真实材料不再作为停止编写这两项的理由。

补充约束：真实用途的捕获必须晚于该模型证据协议冻结，拒绝用旧运行事后补证。原生登记还校验 profile 的数据库 OID/名称；已登记的隔离测试数据库由 SQL 强制归为 synthetic，即使宿主配置了无 MockTransport 的 sender 也不能产生 live 来源。生产 source 不从文件里的 origin 推定。

最终验证：首轮后端 4544 passed/2424 skipped/0 failures/errors；补严冻结时间和测试环境归类后，冻结代码最终全量 4545 passed/2424 skipped/0 failures/errors（684.92 秒）。初轮定向 24 passed，API 组合定向 32 passed；新增时序反例已纳入最终全量。前端 192 文件/1944 tests 通过；Ruff/format（1186 文件）、mypy（741 源文件）、Bandit 及前端 format/lint/typecheck 通过。实际 OpenAPI 与前端契约已再生成。所有测试中没有真实模型请求、真实认证或生产访问。2424 skip 和新增 SQL 未执行分别保留为未验收，不算通过。

前端 build 通过（既有 chunk-size 提示保留）。补丁 `/workspace/scratch/tender-business-shadow.patch`，测试日志、完整 skip 原因与文件清单 `/workspace/scratch/tender-business-shadow-validation/`。本阶段没有工具拒绝或未确定的生产操作。
