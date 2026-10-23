# v14 当前完整 schema：真实本地恢复复测

日期：2026-10-21。本轮是检查点 11 候选的独立增量证据，保留 [前次恢复验收](current-schema-recovery-acceptance.md) 的原始身份与成绩。本轮使用最新 37 项 `BASE_SQL` 和 14 项明确可选扩展，共 **51 项 SQL**；包括整包手动任务、精确事件／定时触发和当前整包复盘，已移除旧 WIP `retrospective-research.sql`。普通恢复范围不含隔离技术评分的 `package-score-execution.sql`、`package-score-reconciliation.sql`。

## 实测结果

使用独立 **PostgreSQL 17.11** 与真实回环 **SeaweedFS S3**，在两个不同空数据库和两个不同合成对象桶之间完成备份、原件归档、恢复与反例验证。原生用例 **1 passed，12.62 秒**；运行器随后退出码为 0。只创建本次临时目录与随机回环端口，合成口令文件权限为 `600`；自建 PG、S3 均已退出，临时服务目录已删除。未操作旧服务、旧库、业务配置或远端。

机器收据：[current-schema-recovery-v14-receipt.json](current-schema-recovery-v14-receipt.json)，SHA-256：

`0cd91e4ec1f8b09337b69f2a862c653dfe95b0dddb4b478eb64ffd1d2dd6736c`

| 恢复面 | 实际结果 |
| --- | --- |
| schema／表 | 10 个 schema、228 张表，其中 57 张有数据；每表行摘要与导出快照一致。 |
| 定义与权限 | 加固前核对完整定义、ACL 依赖、2696 列、311 个函数、1633 个约束、483 个索引、245 个触发器、1 个序列等；只有已审的精确 CHECK 重解析二串允许等价。 |
| 扩展 | `plpgsql 1.0`、`uuid-ossp 1.1`、`vector 0.8.0`。 |
| 原件对象 | 2 个真实 S3 对象，共 5324 字节；源对象、归档、恢复对象的 SHA-256 与大小一致。 |
| 并发快照 | 导出快照建立后的真实提交仍留在源库，未进入归档和恢复库。 |
| 恢复只读 | 非 owner API 登录默认只读；表与列级写权限均移除。即使关闭会话只读设置，实际 UPDATE 仍被权限拒绝。 |
| 源环境不变 | 源表行、原件字节与运行账号权限保持原状；失败控制期间没有额外数据库变化。 |

表数与前次成绩不同，源于本次明确 SQL 组合变更，不能将旧 WIP schema 的表数加回本候选，也不使用旧恢复结果代替本次结果。

## 新任务与复盘记录往返

新增 `tests/completion_recovery_native_records.py`，在既有 F04/F05 合成材料场景内通过实际非 owner API／服务建立以下记录，随后纳入同一次导出快照：

1. 用本次已登记人工更正后的清单，调用实际预检、冻结输入、执行准备和依赖计划服务，保存一个 `exact_package_trigger` 模板。十个确切输入字段来自真实保存结果，没有手工拼造不存在的 ID 或伪造 task 记录。
2. 使用既有明确合成的资料生产者夹具持久登记 `materials.committed`，让实际协调器建立意图；一次经真实取消 API 进入 `cancelled`，另一次保留 `pending`。意图、resolution、命令、审计均由原生产代码及 SQL 守卫写入。
3. 对已有原生实交记录，通过实际复盘预览／保存 HTTP 接口建立 `pending_review` 复盘。官方结果、业务结果与成对核查尚缺，保持相应缺失原因和空值，没有创造评分结论、企业知识候选或正式样本。

恢复后以加固的只读 API 登录，采用与运行连接相同的 `design,public` 搜索路径，调用同一领域读取函数逐字段比较。固定模板响应、pending／cancelled 意图的当前历史视图、不可变复盘全文与摘要均与源记录相同；知识关联仍为空。既有 F04 更正记录和 F05 实交绑定、实交历史服务读取也保持通过。

本场景 **未建立 task run、未启动 Worker、未请求模型**，因此不声称验证了运行中任务续跑、原生模型核查完成状态或 Kafka 历史消息恢复。它验证的是本批新增持久模板、意图与待核复盘能被完整恢复，并保留原语义。

## 新增 CHECK 重解析反例

首次原生恢复发现新增约束 `design.package_retrospective_knowledge_links_reason_check` 的括号由 PG 重解析为相同 AND 联合形式。集成负责人核对原始差异后，只为完整 schema／约束名／表名／第四字段身份添加两条精确 SQL 字符串：

```sql
CHECK ((((length(reason) >= 1) AND (length(reason) <= 4000)) AND (reason ~ '\S'::text)))
CHECK (((length(reason) >= 1) AND (length(reason) <= 4000) AND (reason ~ '\S'::text)))
```

没有改变实际 SQL 约束、恢复库约束或进行通用去括号处理。参数化反例同时核验边界、操作符、身份、ACL 和重复项变化均不被归为等价。后续原生运行完整通过定义比较。

## 故障控制与静态检查

本次继续执行真实故障控制：错误 S3 secret 返回 403；归档对象损坏或丢失被拒绝；恢复对象损坏和 404 缺失被拒绝；源对象损坏或 404 缺失阻止生成完整原件归档。整个过程始终先核验数据库与对象绑定，不把数据库组件成功解释为完整应用恢复成功。

配套纯检查 **43 passed，1 skipped，0.33 秒**。唯一跳过项仍为旧的、必须另行显式配置的 generic 外部恢复演练，不是本次真实 PG／S3 用例。新增 helper 与修改后的原生测试 Ruff、格式和 diff 检查通过。收据所记录的源码和 51 项顺序 SQL 在最终校核时均无变化。统计、源文件摘要和原始纯测试报告摘要见 [current-schema-recovery-v14-checks.json](current-schema-recovery-v14-checks.json)。

重现命令在 `workbench` 下运行；收据必须选择尚不存在的新路径：

```sh
python -m deploy.completion_recovery_runtime \
  --pg-bin /absolute/path/to/pg17/bin \
  --weed /absolute/path/to/seaweedfs/weed \
  --receipt /tmp/new-current-schema-recovery-receipt.json

python -m pytest -q tests/test_completion_recovery.py \
  tests/test_backup_generic.py tests/test_application_recovery_definitions.py
```

本次沿用已有运行器，不添加第二套启动机制。只修改 `tests/test_completion_recovery_pg.py` 并新增上述 helper 与本批独立证据文件；共享恢复模块的精确重解析修正由集成负责人完成。

恢复目标仍是同一临时 PG 集群中的不同数据库；S3 为真实本机协议服务。生产 OSS、跨主机恢复、模型供应商、Kafka 消费、旧队列安全续跑、完整应用重启与生产 RPO／RTO 均不在本轮资格内。收据对应资格标志保持 `false`；模型与付费调用均为 **0**。
