# 本地真实 Kafka、S3 与普通 Worker 运输验收

## 实测结论

`tests/test_real_transport_integration.py` 已在真实隔离服务执行：**1 项完整集成用例通过，6.47 秒**。它包含以下连续路径，未用内存消息队列或对象存储替代实际网络端口：

1. 实际 boto3 S3 签名 PUT、GET 同一份合成 PDF，核对全部字节与 SHA-256；错误合成密钥的读取返回 HTTP 403。
2. 用实施版 `execution-policy-10.json` 与真实 Kafka AdminClient 创建/核对 9 个 topic，校验集群 ID、6 分区、复制数 1、保留时间等配置。
3. 独立非 owner API 事务创建精确解析申请、operation、step、outbox、命令回执及审计。
4. 实际 `engine.relay(once=True)` 使用 Worker 角色 claim outbox，经 confluent-kafka producer 投递，收到 broker ACK 后标记 `published_at`。
5. 实际 `engine.consume("document")` 消费消息，运行现有普通 Worker；通过真实 S3 HTTP 读取原件，由实际 PDFium 提取两页，事务发布不可变结果。
6. 再次向 Kafka 投递完全相同的任务，等待实际消费组提交到该重复消息之后的 offset。计算只调用一次，step receipt、effect receipt、解析 result 均只有一条；结果保持两页、`partial`。
7. 该 operation 的 `model_calls` 为零。未启动模型、自动协调器或付费消费者。

输入是约 1.9 KiB 的合成技术 PDF。测试中的项目、上传凭证和编写依据由隔离数据库夹具播种；这里证明的是实际运输、字节一致性和重复投递处理，不代表真实业务标书或大文件已验收。

## 环境与隔离

| 服务 | 实际版本 | 范围 |
| --- | --- | --- |
| PostgreSQL | 17.11 + pgvector 0.8.0 | 既有一次性检查库；独立 API/Worker LOGIN；owner 只负责 fresh schema 与技术夹具 |
| Kafka | 4.1.2，commit `c82fd9b934b4c1e6` | 单节点 KRaft，broker `127.0.0.1:59093`，controller `127.0.0.1:59094` |
| SeaweedFS | 4.48，commit `530be3e37337488ecc34d58441e0bc476e121c93` | S3 `127.0.0.1:58333`；master/filer/volume 及 gRPC 全部只绑定 loopback |
| 客户端 | 项目已安装 confluent-kafka、boto3、PDFium | 直接执行项目生产端口及 Worker 代码 |

Kafka 和 Seaweed 使用独立临时目录与 `nobody` OS 用户；未加载业务 `.env`。S3 合成身份文件为 0600，密钥不写入仓库或测试输出。Seaweed 遥测关闭，Iceberg/Lance 监听关闭，S3 自动创建 bucket 关闭，未使用嵌入 IAM/STS。测试自行创建并清理合成 bucket。

验收后已正常停止这两个临时服务，并实际核对十个 HTTP/gRPC/Kafka 监听端口全部关闭；既有 PostgreSQL 检查服务保持不变。

首次配置只允许 4 个 volume，少于 Seaweed 默认一次增长的 7 个，实际 PUT 因没有可写卷失败。检查配置改为 32 个可用 sparse volume 槽、每卷 32 MiB 后通过。此调整仅作用于临时技术服务，不修改生产代码或扩大数据库权限。

## 复跑方式

测试不会自行启动或安装外部服务。先准备全新的隔离 PG、Kafka 和 S3，并通过私有 JSON 文件显式指定技术环境：

```json
{
  "only_synthetic": true,
  "kafka_bootstrap": "127.0.0.1:59093",
  "cluster_id": "由隔离Kafka生成的准确集群ID",
  "s3_endpoint": "http://127.0.0.1:58333",
  "credentials_path": "/absolute/private/s3-identity.json"
}
```

`s3-identity.json` 采用 Seaweed 的 `identities[].credentials[]` 结构，包含 `accessKey` 与 `secretKey`，文件权限必须是 0600。测试在初始化检查库前限制三种服务到 loopback，拒绝远端地址；PG 管理入口必须是 `postgres` 数据库。固定检查库 `fusion_package_requirements_api` 需要空闲，不能与其他使用该 fixture 的 PG 测试并行。

```sh
WORKBENCH_ENV_FILE=explicit-isolated-transport-test \
PYTHONDONTWRITEBYTECODE=1 \
FUSION_REQUIREMENTS_ADMIN_DSN='postgresql://LOCAL_TEST_OWNER@127.0.0.1:55441/postgres' \
FUSION_TRANSPORT_PROFILE='/absolute/private/transport-profile.json' \
python -m pytest tests/test_real_transport_integration.py -q --tb=short -x
```

未提供这两个显式环境变量时，该用例跳过，不把 skip 计为运输通过。复跑使用同一 Kafka 时必须保证之前的合成消费均已完成；失败运行留下的消息需要在专用技术集群内清理或重建，不可在业务集群执行此测试。

## 尚未证明

本轮未验证多 broker 容错、网络分区、进程崩溃后自动恢复、生产容量、S3 云厂商差异、真实 OCR、模型效果或部署到生产的可用性。任务本身使用真实数据库和运输，但这不等于完整生产恢复验收；执行策略中的 `production_recovery_validated` 保持 false。
