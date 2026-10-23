# 真实传输进程故障与自然恢复验收

日期：2026-10-21。结论：本轮在新的本机 PostgreSQL、Kafka 和私有 S3 上执行了三类真实进程故障，**4 项用例通过，202.73 秒，0 失败**。其中三项为故障流程，第四项汇总并核对原始收据；不能把它描述为四类故障。模型及付费调用均为 0。

## 故障及观察结果

| 实际故障                                                     | 故障发生时                                                              | 正常机制恢复后的证据                                                                                                     |
| ------------------------------------------------------------ | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Relay 收到 Kafka broker ACK 后被 SIGKILL，尚未提交数据库 ACK | broker 回调已到达；outbox 的 published 字段仍为空，发布尝试为 1         | 等待原 30 秒认领自然到期，再启动正常 relay；发布尝试变为 2，实际后续 Kafka offset 的重复消息被消费者提交，计算尝试仍为 1 |
| Worker 完成真实 S3 原件读取与 PDF 计算后被 SIGKILL，尚未发布 | step 保持 running、尝试 1；结果表为 0                                   | 原 120 秒租约自然到期；旧 fence 在恢复前后均被拒绝；独立 reconcile、relay 和真实消费者产生第二代投递，第二次尝试完成     |
| 私有 S3 服务进程被 SIGKILL                                   | 真实连接失败；数据库保存可重试的 `OBJECT_STORE_UNAVAILABLE`，结果表为 0 | 使用原参数、原目录和原身份重启 S3；原件 SHA 保持一致，正常后续投递的第二次尝试完成                                       |

三种流程最终均只有 **1 份 document parse result、1 份 effect receipt、1 份 step receipt**，没有重复业务结果，没有模型调用。这里核对的是实际数据库与消费者 offset，未用“进程重新启动”代替业务一致性验证。

Relay 从故障后的检查点再等待了 26.145 秒，连同前面的实际运行时间达到原 30 秒认领期。Worker 在对应检查点等待了 119.801 秒，达到原 120 秒租约期。测试没有缩短租约、修改数据库时钟或回填过期时间。

## 运行方式及隔离

本轮使用 `deploy.fusion_full_native` 的固定 `transport-faults` 套件。入口为每次执行建立独立私有目录、新 PostgreSQL 集群、新 Kafka 集群、新 S3 凭据与 bucket，并且不占用共享 PG 55441。业务使用独立非 owner API/Worker 角色，relay、reconcile 和 Worker 各以普通业务入口的环境白名单运行。

源数据是合成 PDF 和通过非 owner API 角色登记的合成来源元数据。原字节实际写入 S3，消息实际通过 Kafka，解析使用普通 Worker。此套件没有重复执行完整浏览器上传流程；带 Cookie、CSRF、授权修订及下载核对的实际 API 上传主链见 [完整运行配置验收](full-runtime-acceptance.md)。

故障注入只针对本轮创建的子进程。S3 停止前核对真实 `/proc` 进程命令行、可执行文件、私有数据目录、配置路径和 UID。Relay 与 Worker 用有界的测试屏障停在确定的提交边界，屏障记录以临时文件、fsync 和原子改名写入；没有替换真实 Kafka producer、对象读取、PDF 计算或数据库发布算法。子进程及私有环境由 finally 清理。

运行命令（各二进制必须已经存在，收据路径必须是新文件）：

```bash
python -m deploy.fusion_full_native \
  --suite transport-faults \
  --pg-bin /absolute/path/to/pg17/bin \
  --weed /absolute/path/to/weed \
  --kafka-dir /absolute/path/to/kafka \
  --receipt /absolute/new/path/transport-faults.json
```

此入口只接受预定义套件，不接受任意脚本或现存环境作为故障目标。正常 `pytest` 没有显式本机运行配置时跳过这组集成测试；跳过不表示通过。

## 冻结证据

- [原始机器收据](real-transport-fault-recovery-receipt.json) SHA-256：`d0dea67f2d37a42a0c1826b6d84d5056db986e9e88b5488d906cc85f40d41bd0`。
- 真实运行日志 SHA-256：`467bd05bf860fdc3c35352fe6cc85cd23ce71fd9e4e5226a7fbb33c174e90601`；末行 `4 passed, 31 warnings in 202.73s`。31 个警告来自 botocore 的 UTC 时间 API 弃用提示。
- 收据时点：`2026-10-21T04:23:23.381224+00:00`。
- 实际初始化 40 项 SQL，完整有序路径和 SHA 存于收据；初始化计划摘要：`12c9369959af127e4ef4ccb59613725ed00839f29024dd4a7939b12c603ef2d9`。
- 9 个直接被测源码/SQL 的 SHA 在运行前后相同，并在收据复制入仓时再次核对。包括普通 Worker engine、document handler、来源/解析策略、存储、worker SQL，以及两个故障测试模块。
- 收据保留实际 CPython、Python 包、libpq、librdkafka、PDFium 与图片编解码器身份。公开文件不含口令、DSN、Cookie、票据或私有原文。

初始化时精确任务 SQL 为 `f40b53242cbe73d7425ce0b07c1428c041f2dd79735701b3829aafbb17dee3be`。此后该 SQL 的另一条任务 ACK 比对表达式修正为最终版本 `2e1c9ae9b24533402c0a8e5da43f6c5098539b6d8697098be2e2f14dc4e7e1f2`。本故障流程没有执行该任务触发器，不把本收据改写为最终任务 SQL 的通过证据；最终任务绑定由独立真实 PG 任务流程验收。

## 本结论的适用范围

本记录证明合成原件的真实本机运输路径在上述确定故障边界下能自然恢复、拒绝旧 fence 并保持业务结果唯一。它不证明多 broker 丢失、跨机网络分区、生产峰值容量、生产 RPO/RTO、收费模型未知账单或容器镜像部署通过。当前没有 Docker 运行证据，正式评分、模型准确率和投递资格也不由这组机制测试授予。
