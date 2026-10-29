# 扩展 schema 的离线恢复与角色隔离

日期：2026-10-26（Asia/Shanghai）。新协议为 `tender-extended-offline-recovery/1`。本阶段补齐 B1–B5 编制、完整材料评分及原生派发新增数据的备份恢复覆盖。验收范围是**独立合成环境中的完整数据恢复、只读隔离和资源回收**；整个产品、生产灾备或恢复业务流量并未因此达到 100%。

## 本阶段实现

`deploy.extended_recovery.frozen_plan()` 保留旧恢复计划的原有顺序，再显式加入 B1–B5 和完整材料链所需 SQL，去重后共 **74 份**。每项绑定仓库路径、原始字节和 SHA-256。执行前核对冻结计划；缺失、重排、多余、字节或摘要变化均拒绝。备份同时要求新增关键关系真实存在，不能拿缺少新能力的旧库生成相同范围的收据。旧 `completion_recovery`、两代通用备份格式和它们的历史验收记录保持原样。

新备份使用独立受限 LOGIN，在 `REPEATABLE READ READ ONLY` 事务中导出快照。在同一事务内记录全部非系统 schema 的表行数、规范化完整行 SHA-256、目录、函数/约束/索引/触发器/列/ACL/扩展/sequence 定义、blob 引用和角色依赖；真实 `pg_dump --snapshot` 使用同一备份 LOGIN。B5 的 `authoring_exact_revision_records` 是视图，因此另外保存和比对其结果摘要，避免把视图误当作缺失的实体表。

原件档案由该快照中的 blob 引用驱动，从显式本地 S3 服务 GET 并核对真实尺寸和 SHA。恢复数据库前先验证所有原件本地字节；原件损坏时，连新的目标数据库也不会创建。恢复使用全新的随机数据库，以实际 `pg_restore` 导入，先比对全部定义和 ACL，再进行离线隔离。源库及源对象不改写。

隔离从本库实际 ACL 依赖发现能力角色，并包含其非管理员继承成员，不再只依赖五个旧角色名称。目标库收回相关角色及 PUBLIC 的表、列、sequence、函数、schema 创建和数据库临时对象能力；只给选定读账号表 SELECT/schema USAGE。整组变更处在同一事务中，权限审计通过后最后才授予该账号 CONNECT。审计失败则回滚，目标库保持不能由运行时账号连接的状态。

审计集合包含快照发现的角色和本次指定的读账号，即使后者不在原快照名单中也必须核验。新建数据库前及隔离事务中都拒绝高权限读账号，包括具有任何 PostgreSQL 预定义全局能力、管理员属性或 owner 角色可达 membership 的账号；`NOINHERIT` 下潜在的 `SET ROLE` 能力也不能通过。隔离不修改集群全局 membership，源库权限保持原样。

原件恢复到本轮自建 S3 服务中的全新随机独立桶 `tender-extended-restore-…`，保留原数据库中的完整 object key 和所有不可变行摘要。写入前检查目标桶不存在，并再次核对待写字节。每次数据库恢复与对象恢复各保存独立尝试收据，绑定源桶、目标桶、数据库 manifest 和原件 manifest 摘要，失败后可准确定位本次资源。回收仅逐项删除该次清单中的目标 key，再删除本次目标桶，不使用 LIST 扩大删除范围。

恢复验证从目标数据库读取原 key，显式切换到目标桶及独立只读凭据，调用现有真实 `domain.storage.get`。观察实际 S3 `GetObject` 请求，确认每次 GET 均命中目标桶并核对 SHA/尺寸；同一读账号真实 PUT 和 DELETE 均收到 403。因此回执中的 `application_object_binding_verified: true` 仅证明离线只读对象绑定。恢复后的 API/Worker/材料派发消费者不启动；旧业务 profile 的库名/OID 绑定也不会被重新颁发，`full_application_restore_qualified` 仍为 `false`。

## 真实验证

最终完整入口成功退出 `0`：**6 passed，0 failed，0 errors，0 skipped**，证据目录为 `.local/extended-recovery-final-v5/`。各 case 使用各自新建的 PostgreSQL 17 集群；两个数据恢复 case 均包含全部扩展 schema，源库和恢复库是同一临时集群中的不同数据库。

| 验证 | 最终结果 | 实际证据 |
|---|---:|---|
| 全新完整 SQL 安装、未知角色权限、失败回滚及启动回执丢失 | 4 passed，5.07 秒 | 74 SQL 全部实际安装；未来新增角色的列 UPDATE、sequence USAGE、SECURITY DEFINER EXECUTE 及继承权限均被撤回；注入末尾审计失败后原 ACL 完整回滚且读账号不能连接；快照外新读账号持有 `pg_write_all_data` 时被拒且原 membership 不变；真实 PG 启动成功但工具报告失败时仍精确停止并删掉本次集群 |
| B1–B5 原生编制链 | 1 passed，13.11 秒 | 实际 API/Worker 建议采用、人工文字修改、Word 构建，再完成备份恢复；7 个相关实体表及构建输出均非空；B5 合并资格视图结果摘要一致 |
| 原生材料派发与一次发送账本 | 1 passed，35.76 秒 | 实际登记、核验、封存、报价、任务、Outbox、租约、一次发送许可、完整响应和用量账本、派发终态均有非空原生记录，再完成恢复；提供方仅使用明确的 `httpx.MockTransport` |

两条数据恢复链都实际校验 **24 个 schema、286 张表、410 个函数、1,970 项约束、587 个索引、308 个触发器、19 个 blob 外键**。其中：

| 数据链 | 非空表 | 被核对并隔离的相关角色 | S3 档案对象 |
|---|---:|---:|---:|
| B5 编制与 Word | 84 | 34 | 4 个，共 8,361 字节 |
| 完整材料与派发 | 93 | 65 | 1 个，共 1,814 字节 |

材料原生存储中的 PNG、请求、完整响应等 `bytea` 内容包含在数据库逐行摘要和实际 dump/restore 中；S3 对象计数仅指快照引用的外部 blob，不把数据库内字节重复计入。

每条数据链还实际验证：

- 导出快照后另一非 owner 连接提交审计行，源库可见、恢复库不可见。
- 原件被破坏时，在任何目标数据库创建之前失败。
- 目标读账号关闭 `default_transaction_read_only` 后，真实 UPDATE 仍得到权限拒绝。
- 已验证能连接源库的 Worker LOGIN 无法连接恢复库。
- 源库的完整定义/ACL、全局角色 membership、源表内容和原对象字节在恢复前后不变。
- 目标数据库原 key 经真实 `domain.storage.get` 从独立目标桶读取，GET/SHA/尺寸与档案逐一一致，只读对象账号的 PUT/DELETE 均被拒绝。
- 没有重新发送旧模型任务或校正 Kafka offset。

纯机制和相关回归合计 **64 passed / 0.98 秒**，其中新计划/工具/旧报告清理边界用例 11 个、旧恢复用例 25 个、当前 CI 汇总相关用例 28 个。8 个 Python 文件通过 Ruff 和格式检查，3 个实现文件通过 mypy 与 Bandit。已有 FastAPI 重复 Operation ID、Starlette 和 boto3 弃用告警仍记录在测试输出中，不将告警消失作为本阶段结果。

`temporary_object_store` 仅在显式 `recovery=True` 时提供本轮自建服务的临时 bootstrap 管理凭据和独立只读恢复身份，业务 API/Worker 仍使用原有源桶权限。默认关闭模式另做了真实 S3 烟测：返回字段仍为原 6 项、源桶 PUT/GET/DELETE 成功、其他桶创建被 403 拒绝、服务正常清理。该烟测不重复计入上面的 pytest 数量，回执为 `.local/extended-recovery-default-s3.json`。

## 运行入口与证据

在 `workbench` 下，使用事先校验过的本地 PostgreSQL 17/pgvector 和 SeaweedFS 二进制：

```sh
python -m deploy.extended_recovery_runtime \
  --pg-bin /usr/lib/postgresql/17/bin \
  --weed .local/ci/bin/weed \
  --report-dir .local/ci/recovery
```

该入口自行创建并停止 PG 与 S3，不要求既有业务 DSN；PG 明确使用 UTC，与原生材料 RPC 的摘要规则一致。普通 Linux 账号直接运行；以 root 运行时 PG 使用独立非 root 系统账号。解压式本地 PG 如需额外库路径，可显式传 `--pg-library-dir`，不会继承未审的 PG 参数或自动寻找业务 profile。任何选中 case 出错或跳过均使入口失败。启动任何服务前先删除所有 case 的确切旧 JUnit/proof 和汇总文件，包括本次未选择的 case 及 `reader-rejection-proof.json`；汇总仅列出本次实际运行的 case，防止复用报告目录时混入上次成功证据。

报告目录仅包含三个独立 JUnit 文件 `schema-junit.xml`、`authoring-junit.xml`、`material-junit.xml`，四个证明文件 `schema-proof.json`、`reader-rejection-proof.json`、`authoring-proof.json`、`material-proof.json`，以及 `summary.json`、`summary.md`、`cleanup.json` 和脱敏 `s3.log`。数据库/S3 口令和完整 dump/原件档案不进入报告目录。完整档案使用被 Git 忽略的私有目录与 700/600 权限，正常和失败路径默认清理；显式私有诊断开关保留的本轮 12 份调试档案已按格式和本轮 owner 标记逐一核验后清除，脱敏记录保存在 `.local/extended-recovery-debug-cleanup.json`。

最终 `cleanup.json` 已确认三个外层 PG 集群停止、监听关闭、私有数据和口令删除，S3 进程回收且私有状态删除。启动回执丢失用例还验证了一个嵌套 PG 集群的同样回收。早期一次 `/proc/<pid>/exe` 读取被宿主拒绝，工具保留了集群，没有删除运行中的数据；随后按精确命令、data 目录、UID 和 PID 核验停止，修正后的最终入口成功通过。另供本轮提交前复核使用的共享临时 PG，在确认无非默认数据库、无额外 LOGIN、无其他客户端后已停止并清除私有配置。

## 保留的交付边界

这些结果覆盖本次已实现能力的离线完整恢复。真实标书质量、真实模型费用/效果、生产原生 OSS、不同故障域的持久备份、静态加密/KMS、WAL/PITR、生产容量、RPO/RTO，以及恢复后重新颁发资格、废止旧 fence、Kafka offset/Outbox 对账和恢复写流量仍须各自独立验收。

因此 `old_queue_resume_qualified`、`native_oss_qualified`、`full_application_restore_qualified` 和 `production_rpo_rto_qualified` 均保留为 `false`。本轮没有支付模型调用、没有修改源生产库、没有将合成业务结果认证为真实投标通过。
