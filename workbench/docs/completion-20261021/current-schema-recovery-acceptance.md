# 当前完整 schema：本地备份与恢复验收

## 结论与证据身份

2026-10-21 对本轮实际 schema 完成了一次独立的 PostgreSQL 17 与原件对象恢复演练。候选包含当前 `BASE_SQL` 的 33 项，以及显式审定的 14 项可选扩展，共 47 项 SQL；F04 人工规则更正、F05 整包实际提交、Word、知识、助手、预算、多章节生成和研究相关 schema 均在其中。结果为 **239 张表、11 个 schema 的定义、ACL 与快照行数据一致，2 个原件对象的长度和 SHA-256 一致**。

本次证明本地数据库与原件两个组件的恢复能力。完整应用启动、旧队列继续执行、云 OSS 连接、异机灾备和生产 RPO／RTO 均未因此取得资格。没有调用付费模型，没有启动 Consumer，也没有读取真实业务资料。

机器可读证据为 [current-schema-recovery-receipt.json](current-schema-recovery-receipt.json)，其文件 SHA-256 为 `c1fdd0e9bd7a71b085a7e3f05d82563bb9f04167855ca30de6a8b1877d615443`。记录时间为 `2026-10-21T03:38:06.098542+00:00`。收据冻结了 47 项 SQL、9 个实现／测试文件、原生 PostgreSQL 工具和归档的摘要；归档之后再次核对这 56 项源码／SQL 摘要均一致。

收据只包含版本、数量、状态和摘要。数据库归档、原始 JSON、合成账号数据和对象字节留在被 Git 忽略的私有目录，不进入公开证据文件。

## 实际覆盖

| 对象 | 本次结果 |
| --- | --- |
| PostgreSQL | 原生 PostgreSQL 17.11；`pg_dump` 与 `pg_restore` 均为真实进程 |
| 扩展 | `plpgsql 1.0`、`vector 0.8.0` |
| SQL | 33 项当前基础 schema ＋ 14 项可选扩展，顺序及每项摘要见收据 |
| Schema | 11 个：`design`、`historical_backtest`、`historical_input`、`model_governance`、`model_release`、`public`、`retrieval`、`retrospective_research`、`score_basis`、`score_execution`、`technical_scale` |
| 表与数据 | 239 张表；49 张有数据；全部表逐项核对快照行数和内容 SHA-256 |
| 定义与权限 | 724 个 relation、2,743 列、292 个函数、1,652 个约束、480 个索引、244 个触发器及全部收据列出的 ACL／类型／序列等 |
| 原件 | 2 个对象，共 5,324 字节；真实 loopback S3 的上传、读取、长度及 SHA-256 核对 |
| 新业务记录 | 真实 F04 服务创建的增补、替换、撤销及 v2→v3 派生链；真实 F05 服务创建的 `offline_fact` 和不可变整包 binding |
| 恢复后的历史读取 | 使用非 owner API 角色调用 F05 历史读取，返回值与备份前完全一致 |
| 并发快照 | 备份快照之后另一个 API 事务提交的审计记录留在源库，未混入恢复结果 |
| 备份账号 | 专门的非 owner 只读账号；覆盖各应用 schema 和序列读取，不拥有表或列写权限 |
| 恢复后的权限 | 定义／ACL 比较完成后执行现有离线恢复加固；禁用运行时写权限和函数执行权限 |
| 源环境保护 | 源库行数据、原件字节及运行时权限均保留；源桶与目标桶不同 |

测试在自建的临时 PG 集群中创建两个不同数据库，并在本次自建的 SeaweedFS loopback S3 中创建两个不同桶。没有复用协作测试端口 `55441`，没有触碰业务数据库或已有对象桶。运行结束后原生 PG 和 S3 进程正常停止，临时集群和对象目录清理完成；私有归档继续保留。

实际数据由现有 F04 合成夹具经正常领域服务生成，并进一步执行 F05 登记。可选扩展已安装且全量比较定义、ACL 和表数据；这不意味着每一种可选业务都在本次演练中产生了非空业务记录。

## 恢复过程及失败控制

数据库备份复用 `deploy/backups/generic.py` 的 catalog、导出快照、全表清单和恢复流程。新工具只提供显式本地 PG 可执行文件传输，以及与该数据库归档严格绑定的原件归档。对象清单来自备份快照，恢复时不重新枚举当前业务源来替换清单。

目标数据库由恢复器新建，目标对象桶必须为空且与源桶不同。所有归档、清单和原件在接触恢复目标之前核对身份、文件类型、私有权限、长度和摘要；缺项或损坏导致失败。

这次真实 S3 反例包括：

1. 错误的合成 S3 密钥返回 HTTP 403。
2. 归档中的原件损坏被拒绝。
3. 归档中的原件缺失被拒绝。
4. 已恢复目标对象损坏被摘要核对发现。
5. 已恢复目标对象缺失返回 HTTP 404。
6. 源原件损坏阻止完整归档生成。
7. 源原件缺失返回 HTTP 404，并阻止完整归档生成。

这些反例期间数据库列表没有额外变化，不会把未完成对象校验的情况写成恢复成功。纯测试还覆盖数据库绑定不符、公共文件权限、符号链接、源目标同桶、目标桶非空以及 CHECK／ACL 被修改等情况。

对当前 ACL 增长还做了一项实际写操作检查：恢复后的非 owner API 账号关闭会话只读设置后，尝试对 `retrieval.knowledge_index_heads.desired_index_id` 执行无命中行的 UPDATE，仍得到权限拒绝 `42501`。因此表级及列级写权限都已被现有加固移除，无需更改旧备份实现或放宽权限。

## PostgreSQL CHECK 文本重解析边界

真实 `pg_dump`／`pg_restore` 会对部分同义的 CHECK 表达式重新输出括号。现有比较模块已经认可 `historical_input.chapter_payloads_raw_content_check` 的精确重解析形式。本轮另外遇到两个已知约束：

| 约束身份 | 唯一认可的变化 |
| --- | --- |
| `score_execution.current_chapters_raw_content_check` | 相同 JSON 类型与 1–2,097,152 字节范围的 AND 括号重排 |
| `technical_scale.evidence_supported_fields_check` | 相同 1–3 元素范围与固定三项字段集合的 AND 括号重排 |

新辅助模块仅对这两个完整约束身份及两种精确 SQL 字符串做等价比较。没有修改源 SQL、归档或恢复后的约束，没有通用地删除括号或忽略约束；操作符、边界、字段、约束身份、重复项及 ACL 的变化均有拒绝测试。旧冻结恢复协议及已有比较模块保持不变。

## 可复现命令与验收结果

在 `workbench` 目录使用项目虚拟环境运行。以下原生演练命令不包含连接串或口令；它只接受显式的本地工具目录，自建独立临时资源，并要求收据路径尚不存在：

```bash
/workspace/scratch/31e56f630f51/review-venv/bin/python \
  -m deploy.completion_recovery_runtime \
  --pg-bin /tmp/tender-completion-runtime/pg17/bin \
  --weed /tmp/tender-completion-runtime/seaweedfs-4.48/weed \
  --receipt /tmp/tender-completion-runtime/completion-recovery-current-final.json
```

重跑时使用新的收据文件名。原生演练最后一次结果是 **1 passed / 9.29s**，运行器随后退出码为 0。该用例包括数据库、对象、权限、新业务历史读取和上述真实失败控制；没有把多次重跑的数量累加。出现的 33 条警告为现有 Starlette BlockingPortal 别名及 botocore `datetime.utcnow` 的弃用提示。

配套定向命令：

```bash
python -m pytest -q \
  tests/test_completion_recovery.py \
  tests/test_backup_generic.py \
  tests/test_application_recovery_definitions.py
```

结果为 **37 passed, 1 skipped**。跳过项是既有、需显式外部配置的旧真实 generic 备份演练，不是本次独立原生演练。新增两个部署模块及两个测试文件的 Ruff／format、两个部署模块的 mypy／Bandit、`git diff --check` 均通过。

新增实现与测试文件：

- `deploy/completion_recovery.py`
- `deploy/completion_recovery_runtime.py`
- `tests/test_completion_recovery.py`
- `tests/test_completion_recovery_pg.py`

## 仍需单独验收的边界

本次恢复对象为同一个临时 PG 集群中的不同空数据库，不是不同主机、不同版本或多节点复制集。S3 为真实本地服务，不是生产 OSS 账号、网络和权限配置。默认 fusion 预览仍只装配 API／Web／PG；本次安装可选 schema 不会自动配置或启动 Kafka、S3、转换器、索引器和 Worker。

现有 164 表的历史恢复成绩继续属于其原候选。本轮使用当前 239 表证据，不能把旧成绩冒作新候选通过；同样，本轮也不改写旧候选的资格。

完整应用恢复后的任务冻结与恢复操作、Kafka 旧消息与新环境隔离、实际容器镜像、转换隔离、异机恢复、故障持续时间和生产容量仍要分别验证。收据中的 `old_queue_resume_qualified`、`native_oss_qualified`、`full_application_restore_qualified`、`production_rpo_rto_qualified` 全部保持 `false`。
