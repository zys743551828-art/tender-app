# 解析、生成物资格与部署接线验收

## 已接通

- 独立原件解析的四个实际方法已注册：读取条件、申请、目录、详情；实施版 OpenAPI 来自实际路由，前端五个 DTO 与能力目录已重新生成。
- `document-parse/1` 进入普通 Worker 的 document lane，`parse-document` 在同一既有租约、取消与发布围栏中计算和发布；不进入付费模型 lane。
- 当前执行策略为 `execution-policy-10.json`；旧策略文件保留。topic 初始化的默认协议与 Worker handler/lane 实际枚举一致。
- 全新库初始化包含独立解析表、不可变约束及 API/Worker 分离授权；Fusion 预览使用新的 `fusion_v10` 数据库身份及 v10 初始化/运行配置卷，v9 与更早卷保留，不原地修补旧库。
- 生成正文资格无法证明的独立 blocker 已加入预检、资格检查、执行准备共用的闭合枚举，并进入生成的 TypeScript 协议。
- Nginx 仅对精确图片登记路径开放 12 MiB JSON 请求预算，以容纳 8 MiB 原图的 base64；其他 API 的全局预算仍为 5 MiB。
- Compose 复核入口增加 `completion-pure` 与 `completion-api`，涵盖范围核查、人工记录、对比、报告、生成物采用和独立解析。后者仍只使用隔离检查库。

## 实际执行

| 检查 | 结果 |
| --- | --- |
| 实施版契约、M1 注册、应用装配、全新库计划、账号隔离、Compose 与 topic 协议 | 97 通过 |
| 生成物资格、独立解析、图片请求预算与 topic 边界 | 45 通过 |
| 解析路由、解析 DTO、解析 Worker、SQL 计划、topic 初始化的 mypy | 5 个实现文件通过 |
| 本轮修改 Python 的 Ruff 与格式 | 通过 |

上述两批 pytest 范围有部署/topic 重叠，不应相加为独立用例总量。真实 PostgreSQL、对象存储、Kafka、Office 转换和浏览器界面效果各自按集成主记录验收；本文件的装配检查不代表这些环境均已运行。

执行命令：

```sh
WORKBENCH_ENV_FILE=review-readonly PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  tests/test_actual_contract.py tests/test_authoring_m1_composition.py \
  tests/test_application_composition.py tests/test_initialize_database.py \
  tests/test_bootstrap_fresh.py tests/test_bootstrap_role_isolation.py \
  tests/test_fusion_compose.py tests/test_initialize_topics.py -q

WORKBENCH_ENV_FILE=review-readonly PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  tests/test_bid_package_generated_output_admission.py tests/test_document_parses.py \
  tests/test_fusion_compose.py tests/test_initialize_topics.py -q
```
