# 完整材料评分：原生发件箱、独立 Kafka Worker 与生产前置门禁

本阶段把原 `material_judgment_job.start` 同事务创建的任务发件箱，接到独立的中继、Kafka 消息消费、准备与执行链。生产任务会在打开材料 reader、取用原件字节、预留费用或构造模型客户端之前经过资格门禁，并保存可回读的阻断回执；具备显式合成配置的隔离测试任务可以走完原生恢复、完整请求预检、单次请求与费用持久化。保存回执仍会核验数据库中的原任务、来源与费用状态。

生产发送资格仍未取得。`production_send_authorized`、`formal_prediction_eligible` 和 `automatic_model_retry` 始终为 `false`。没有调用付费模型。

## 已实现的闭环

| 环节 | 实际行为 | 边界 |
| --- | --- | --- |
| 任务来源 | 读取原 `material_judgment_job.outbox`，保留既有任务与 outbox 的原子创建 | 不另造合成任务来源；不修改原任务资格 |
| 中继 | 专用 LOGIN 原生领取有 fence、token、时限的发布租约；提交事务后向 Kafka 发布；收到 broker delivery 确认后写入原生 ACK | broker 或数据库 ACK 丢失时只会重发原事件 |
| 消息 | 专用 topic `tender.material.judgment.v1`，闭合四字段：`version`、`event_id`、`job_id`、`generation` | 无正文、请求、引用、URL、口令、模型参数或资格自报字段 |
| 消费 | 专用 LOGIN 领取独立处理租约；只在原生终态结果已提交后手动提交 Kafka offset | 活跃的其他投递不能借用旧 token；不提交 busy 或异常消息 |
| 生产准入 | 先调用既有 `material_execution_attempts.execute_attempt` 的硬拒绝门禁，再原生保存 `blocked` 或既有费用未决状态 | 不打开材料 reader、不预留钱包、不构造供应商客户端 |
| 隔离机制 | 专用 profile 绑定合成 origin、测试数据库、原 prep/exec profile 与方法摘要；真实 native recovery → 原 `/3` 全材料预检 → 每槽原 once-only execution | 只允许精确 `httpx.MockTransport` 类型；未开放任意执行器或网络客户端注入 |
| 费用不明 | `unknown` 或 `in_flight` 在新准备、恢复或发送之前停止，保存 `billing_unresolved` | 不释放未决占用，不把异常转换成零费用，不自动补发 |
| 终态 | 结果与状态同事务持久化，并终止本任务、绑定准备 profile 的当前准备租约 | 已有发送权仍可晚到结算；提交终态后，旧准备租约不能取得新槽位发送权 |
| 回读与重放 | 原 actor/OID 可读不可变结果；终态重复消息先核对原 outbox，再直接回读 | profile 后续过期或撤销不会把已完成消息重新送入准入和费用链 |

没有把 material handler 加入普通 `ORDINARY_HANDLERS`、`design.outbox` 或普通失联任务 reconcile。普通重试策略不能接管这些评分请求。

## 代码入口

- `deploy/sql/material-execution-dispatch.sql`：原生 profile、领取/心跳/ACK、原任务恢复引用、终态回执和准备租约终止；13 个受审函数。
- `packages/model_governance/material_execution_dispatch.py`：独立目的 LOGIN 审计、固定 native RPC、严格消息与回执验证、自有事务。
- `packages/model_governance/material_execution_runtime.py`：Kafka producer/consumer、真实发件箱中继和完整处理入口 `deliver`。
- `deploy/material_execution_worker.py`：独立进程启动入口；生产 worker 只接受自己的 dispatch DSN 和 Kafka bootstrap。
- `tests/test_material_execution_dispatch.py`：消息协议、门禁顺序、ACK 顺序、重复消息与私有启动配置。
- `tests/test_material_execution_dispatch_pg.py`：真实 PG17、独立 LOGIN、原 outbox/材料恢复/费用账本及可选真实 Kafka 验收。

已发布的 preflight 与 execution 源文件不变；原 serializer、provider parser、judgment checker 及资格协议不变。新增 dispatch 方法摘要覆盖自身 SQL、facade、runtime、launcher 和既有 execution 方法链。

## 终态与费用的准确含义

`blocked` 表示本次运输处理已终止，且没有取得生产准入。`mechanism_completed` 只表示隔离合成任务的所有逻辑槽位已按既有判定规则完成。`billing_unresolved` 表示终态事务观察到既有 `unknown` 或 `in_flight` 费用状态。

回执的 `observed_send_grants`、`financial_state`、`held_minor`、`estimated_minor` 是 `recorded_at` 时刻的原生账本快照，不是供应商发票终局。终态后已经发出的响应仍可能到达；原 execution 的结算接口保留这类费用，并在准备租约已结束时拒绝把晚到结果当作当前有效判断。后续费用依据 execution 的原生账本读取，不覆写历史 dispatch 回执。

### 两个必须区分的次序

1. **发送权先提交**：原 begin 在相同 job advisory lock 下提交 `in_flight` 与资金占用。随后 dispatch finish 看到该发送权与占用，保存未决回执并终止准备租约。晚到 usage 仍被估算入账，结果不再具有当前资格。
2. **终态先提交**：finish 在相同锁序中终止准确绑定的准备租约。旧 Worker 即使先前已完成两次 heartbeat，恢复执行时也无法通过原 heartbeat 或 begin 当前租约校验。

锁序保持 `governance → bid → graph → execution job → dispatch profile head → preparation inputs → preparation state → dispatch state`。终止操作显式核对 state 的 job、lease 的 job 和 dispatch 绑定的 preparation profile；终态重放不再次改写准备状态。

本阶段没有提供跨数据库与 HTTP 的分布式原子承诺。资金和发送权必须在 HTTP 之前独立提交，故请求是否发出不确定时仍保留占用，并由原 once-only attempt 约束阻止补发。

## 运输恢复语义

- Kafka Producer 开启 idempotence、`acks=all`；消息 delivery 回调未确认时不写原生 ACK。
- broker 已确认而原生 ACK 丢失时，原 relay 租约到期后可再发同一原 outbox 事件。消费者按 native event/job 幂等；重发事件不会增加模型发送权。
- 终态已提交而 Kafka offset ACK 丢失时，重复消费读取终态。SQL 快路径仍要求消息与原 outbox 完全相同，且当前 state 关联的原 lease actor/OID 与调用者一致。
- 消费者关闭自动提交和自动 offset 存储。busy、无效消息、原生错误、offset 确认丢失都会 rewind 当前分区位置；后续成功消息不能越过未处理消息提交 offset。无法 rewind 时要求重启 consumer。
- 同步 `commit` 的返回还必须确认唯一分区、准确的 topic/partition/下一 offset、以及该分区无 error；仅没有抛异常不能认定确认成功。此检查遵循本地安装的 `confluent_kafka.Consumer.commit` 官方 docstring，其明确提示分区级失败需要单独检查。
- 无效消息不作为已处理消息 ACK；运行入口返回固定错误码。没有把可能含私密内容的 broker、PG 或供应商异常写入结果与日志。

## 独立部署入口

新 SQL 是已有 material judgment/preparation/execution 安装后的独立扩展，必须由初始化 owner 在隔离安装流程中装配。运行角色只有专用 NOLOGIN 组的固定函数执行权，不授予表读取/写入，也不复用 owner、API、准备、执行或普通 Worker LOGIN。

配置文件为权限 `0600` 的普通文件；符号链接、额外变量、重复变量均拒绝。启动器以固定解释器和 `-I` 启动自有脚本，子进程环境由白名单构造，`WORKBENCH_ENV_FILE=/dev/null`，不会继承环境中的模型凭证。

生产 worker 的配置仅有：

```text
MATERIAL_DISPATCH_DSN='该专用非 owner LOGIN 的 DSN'
MATERIAL_DISPATCH_KAFKA_BOOTSTRAP='该部署的 broker 地址'
```

relay 另需当前原生注册的 `MATERIAL_DISPATCH_PROFILE_ID` 和 `MATERIAL_DISPATCH_PROFILE_DIGEST`。此处不包含实际凭据。

```bash
.venv/bin/python deploy/material_execution_worker.py --profile /private/material-worker.env --purpose worker
.venv/bin/python deploy/material_execution_worker.py --profile /private/material-relay.env --purpose relay
```

`--once` 用于一次 poll/relay 检查。生产 CLI 没有 fixture 开关、reader DSN 或模型 key 参数。合成完整执行通过独立的显式 `MechanismPorts` 装配，并受真实原生合成 profile、账户和精确 MockTransport 类型共同约束。

## 验证记录

状态：验收完成，七个文件作为独立阶段提交。独立审阅发现并修正了终态后 profile 撤销导致无法确认旧消息、以及旧 Worker 在双 heartbeat 后暂停仍可能获得发送权两个窗口；终态的准备租约终止已经过真实原生交错验证。

| 检查 | 结果 |
| --- | --- |
| 闭合协议、生产前置门禁、ACK/offset顺序、私有 launcher | 最终 **41 passed，16.74 秒**，0 skipped/failed |
| Ruff check / format | 三个运行源文件与两个测试文件通过；5 files already formatted |
| mypy / bandit | 三个新增运行源文件全部通过 |
| PG17.11 原发件箱、独立角色、租约、生产阻断、恢复、费用和真实 Kafka | 完整 **13 passed，357.67 秒**，0 skipped/failed |
| 最后对同步 offset 返回的收口及真实 ACK 丢失重放 | 加强原 Kafka 两项并定向复验：**2 passed，11 deselected，47.72 秒**，0 skipped/failed；这是原 13 项中的两项复验，不重复计为新增用例 |
| 数据库与权限清理 | 两次套件结束后，最后只读核验测试库、`fusion_*` 角色、新 dispatch 组均为空；测试服务交由主任务统一关闭 |
| 付费供应商调用 | 0 |

PG17.11 使用单独临时集群，Kafka 为真实 Apache Kafka4.1.2 KRaft，只绑定 loopback、独立临时数据目录，归档 SHA512 经基础设施阶段核验。Kafka 用例先通过真正 Producer 发布原 outbox 事件，在 broker delivery 成功后注入原生 ACK 丢失，再发布同一事件；消费者完成原生终态及真实同步 offset commit 后，注入本地 ACK 丢失，由实际 `seek` 重放；此时撤销 dispatch profile，重复消息仍只回读原终态并提交确认。生产模式没有模型请求，合成断流模式全程只有一次显式 MockTransport 发送且费用占用不释放。

两种真实交错都走原运行入口和原生账本：终态先赢时旧 heartbeat 与原 checked begin 都拒绝，发送权和预留数保持 0；发送权先赢时终态观察到已有 `in_flight` 占用，晚到 usage 按原价格估算入账，`source_current_at_settlement=false`、`valid_slot=false`。全槽正例走原生五连接恢复与原 serializer，并核验每条规则三个槽位请求字节相同、全部槽位完成后释放剩余预留。

完整原生 13 项在收口前已全部通过；最后唯一实现变化是 Kafka 同步 offset 回执的严格验证，随后重跑全部 41 项纯测试、两项加强的真实 Kafka 用例和静态门禁。SQL、原生租约、费用和交错逻辑没有在该次收口中修改。全程只有既有 Starlette/AnyIO 的弃用提示，没有新增运行告警。

复验命令：

```bash
.venv/bin/pytest -q tests/test_material_execution_dispatch.py
FUSION_MATERIAL_DISPATCH_PG=1 \
FUSION_MATERIAL_DISPATCH_KAFKA_BOOTSTRAP="$ISOLATED_KAFKA_BOOTSTRAP" \
FUSION_REQUIREMENTS_ADMIN_DSN="$ISOLATED_PG_ADMIN_DSN" \
.venv/bin/pytest -q -x tests/test_material_execution_dispatch_pg.py
```

最后两项定向复验在相同配置的命令末尾增加 `-k real_kafka`。原生开关缺失会明确跳过原生测试；Kafka 地址缺失会明确跳过两项 Kafka 测试，不能把跳过项报告为通过。测试会创建并清理自身隔离数据库与 LOGIN，Kafka 使用固定专用 topic 和随机测试 consumer group；专属 broker 的整体临时数据销毁负责 topic/group 清理。

## 尚未取得的产品完成条件

本阶段接通的是独立后台运行链，尚未扩展公开执行 API，也没有把旧 `package_scoring_profile` 描述符的资格用于新完整材料输入。账户实际价格/可用余额证据、模型上下文容量证明、图文可读性验收、生产发送资格仍缺，生产入口对此逐项阻断。真实效果验证、人工评审一致性、发票对账、费用未知的运营处理，以及面向用户的评分聚合/展示仍需后续阶段。

这些条件没有被转换成配置开关或外部自报布尔值，不能据本机制验收宣称整个正式评分产品已经 100% 完成。
