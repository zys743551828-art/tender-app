# B1–B5 作者能力：显式新建候选与原生权限验收

## 本阶段结果

现有 `deploy.create_check_environment` 现在接受独立的 `--authoring-candidate PLAN.json` 参数。该入口读取明确的候选计划，经原 `bootstrap_fresh.bootstrap` 在全新数据库安装 **37 份基础 SQL 与 8 份可选作者 SQL**，再使用实际新建的非 owner API、Worker LOGIN 分别读取目录与有效权限。它不是只保存清单的工具，也不接受已有数据库作为迁移目标。

本轮未修改 `BASE_SQL`、八份作者 SQL 或已发布的 B5 产品逻辑。没有安装材料评分或新版历史研究 schema，没有创建价格、预算、业务记录或启动消费者。权限检查通过只证明该候选的安装和作者权限范围；对象存储、队列、运行配置、实际内容正确性及生产资格仍由各自既有协议验证。

## 有序安装范围

计划版本为 `authoring-fresh-candidate/1`。`base_sql` 保存原 `BASE_SQL` 的完整有序路径及逐文件 SHA-256；`optional_sql` 按下表保存八份扩展路径及 SHA-256；`digest` 绑定整份计划。基础清单仍为 37 件，扩展仍为显式可选项。

| 顺序 | 文件 | 实际用途 |
| ---: | --- | --- |
| 1 | `packages/contracts/sql/authoring-package-inputs.sql` | B1 固定整包输入及事实范围 |
| 2 | `packages/assistant/sql/assistant.sql` | B2 所依赖的助手任务与候选存储 |
| 3 | `packages/assistant/sql/live-facts.sql` | B2 所依赖的既有事实绑定 |
| 4 | `packages/assistant/sql/intent-budget.sql` | B2 所依赖的意图与预算结构；不填入价格或预算 |
| 5 | `packages/contracts/sql/authoring-package-jobs.sql` | B2 固定输入与任务、候选的原生绑定 |
| 6 | `packages/contracts/sql/authoring-exact-revisions.sql` | B3 明确采纳与不可变修订资格 |
| 7 | `packages/contracts/sql/authoring-exact-builds.sql` | B4 固定来源构建及发布前核验 |
| 8 | `packages/contracts/sql/authoring-exact-text-edits.sql` | B5 保留来源链的明确人工文字修订 |

缺项、重复、错序、额外 SQL、不同的基础路径、计划摘要错误或任意一份文件的字节变化，都会在创建资源之前拒绝。此参数不能与 `--reviewed-sql`、旧单文件扩展参数或 `--model-purposes` 混用。原有逐文件新建入口仍保留。

`bootstrap` 仅增加可选的 `expected_sql_plan` 参数：先由原 `sql_plan` 一次性读取并冻结所有待执行字节，随后逐项比较预期路径与 SHA，比较通过后才读取私有配置并连接数据库。因此，计划校验与冻结之间发生 BASE 或扩展变化也会拒绝；冻结之后文件变化不改变实际执行的字节。安装返回后，作者入口还会将全部 45 项实际 `ordered_sql` 与计划再做一次完整比较。

## 实际账号与有效权限检查

核验连接使用新建业务配置中的 API 与 Worker DSN，分别建立实际 PostgreSQL 连接。查询在 `REPEATABLE READ READ ONLY` 事务执行，不使用初始化 owner 代替运行账号，也不补权限。

| 检查 | API LOGIN | Worker LOGIN |
| --- | --- | --- |
| 独立实际 LOGIN、无 superuser / BYPASSRLS / 建库 / 建角色 / replication 权限 | 必须通过 | 必须通过 |
| 完整递归成员关系 | 仅 `tender_api`，无 ADMIN OPTION | 仅 `tender_worker`，无 ADMIN OPTION |
| 用户 schema / 数据库 CREATE 或用户表、函数 owner 身份 | 拒绝 | 拒绝 |
| B1 两表、B2 两表、B3 候选修订表、B5 人工修订表 | 仅 SELECT、INSERT | 无表级或列级权限 |
| B5 联合资格视图 `authoring_exact_revision_records` | 仅 SELECT | 无表级或列级权限 |
| 作者私有验证、转换及触发辅助函数 | 无直接 EXECUTE | 无直接 EXECUTE |
| 原作者产品的 capability 查询 | 固定输入、采纳、构建和人工修订权限可用 | 仅固定来源构建权限可用 |

额外权限检查包含 PostgreSQL 17 的 `MAINTAIN` 以及列级授权，防止只检查表级 ACL 而遗漏权限来源。函数检查覆盖这批实际安装的 26 个作者函数；其中运行账号的允许列表保持为既有 SQL 授权：

- API：`authoring_package_digest`、`authoring_package_assert_job`、`authoring_exact_check_revision`、`authoring_exact_assert_revision`、`authoring_exact_snapshot_proof`、`authoring_exact_build_packet`、`authoring_exact_assert_build`。
- Worker：`authoring_package_assert_job`、`authoring_exact_snapshot_proof`、`authoring_exact_build_packet`、`authoring_exact_assert_build`。

若原生 ACL 核验失败，本次刚创建的业务配置文件会被撤回。新数据库与私有初始化恢复配置保留用于检查；入口不会回退到 owner、修复业务权限或声称候选可用。这个失败分支也有实际 PostgreSQL 反例覆盖。

## 可执行创建方式

从独立的干净工作副本运行。私有初始化配置文件须为普通文件、权限 `600`，按原 bootstrap 规则提供初始化 owner、独立对象前缀及所需基础配置；五个既有能力组也必须已经按原集群引导规则创建为安全的 NOLOGIN 角色。新入口不会为这些前置要求修权限。

首次创建私有目录时：

```bash
mkdir -m 700 .local
.venv/bin/python -m deploy.authoring_candidate \
  --write-plan .local/authoring-candidate-plan.json
.venv/bin/python -m deploy.create_check_environment \
  --base-init-file /private/tender-authoring-init.env \
  --name authoring_candidate \
  --authoring-candidate .local/authoring-candidate-plan.json
```

`mkdir` 仅用于首次创建新目录。若工作副本已有 `.local` 且并非私有 `700` 目录，生产入口仍会拒绝，不静默更改权限；应使用新的私有工作副本。候选文件使用独占创建，不覆盖同名计划。输出的 JSON 回执包含全部 SQL 身份、实际 LOGIN 的核验结果及新配置文件位置，不包含 DSN 或口令。

创建命令会生成新的数据库和独立应用账号，并沿用原 bootstrap 的私有配置管理。它不会启动 API、Worker、Kafka、S3 或模型请求。完成此切片后仍需按实际业务运行配置进行相应验收，不能把新建空库的 schema capability 当作完整业务执行成功。

## 本轮原生证据

使用第三个专用临时 PostgreSQL 17 实例，TCP 仅监听 `127.0.0.1`，所有实际账号使用随机 SCRAM 密码。测试将真实的 45 份 SQL 复制到临时源码根目录；子进程只将 bootstrap 的源码根目录指向该副本，仍执行现有创建入口、原 bootstrap、实际建库和独立认证。这样不依赖开发 checkout 的 `.local` 权限，也不修改或修复它。

本次成功安装回执的计划摘要：

```text
40d8fce48843b6f9dfd81c26c3a201412f6bf423db0a5aa17aa0542468436fe9
```

实际输出确认：45 项 SQL；8 项可选扩展；API 四项作者存储/权限能力均为 true；Worker 的输入存储、采纳、人工修订权限均为 false，构建权限为 true。原生 `SELECT` 人工修订表与联合资格视图被 Worker 拒绝。新库的价格、预算与 outbox 均为空，材料执行和新版历史研究 schema 均不存在。

| 验证 | 最终结果 |
| --- | --- |
| 新候选计划与入口单元反例 | 15 项通过 |
| 原 bootstrap 回归 | 48 项通过；与上述合计 63 项通过 |
| 实际 PG17 新建入口及权限反例 | 14 项通过，0 失败，0 跳过，26.59 秒 |
| Ruff、格式检查 | 5 个本阶段 Python 文件通过 |
| mypy | 3 个部署实现文件通过 |
| Bandit | 3 个部署实现文件通过 |
| 结束后的独立目录核查 | 本次合成数据库 0、LOGIN 0、能力组 0 |

原生反例覆盖缺项、错序、错误 SHA、BASE 与扩展文件变化、已有数据库保留、PUBLIC 表授权、Worker 列级 SELECT、API 人工表 UPDATE、私有函数 EXECUTE、递归角色污染、schema CREATE，以及核验失败时撤回新业务配置。首轮已有 13 项业务断言通过，但清理夹具对空列 `SELECT FROM` 结果的真值处理导致 teardown 错误；已改为明确 `SELECT 1`，完整重跑和独立清理查询均通过，不将首轮报告当最终成功证据。

原生套件需显式配置 `FUSION_AUTHORING_CANDIDATE_PG=1` 与 `FUSION_AUTHORING_CANDIDATE_ADMIN_DSN`，且必须使用独占、可销毁、无同名能力组的本机 PG17 集群。凭据从私有文件加载到进程环境，不应写入命令历史或公开报告。执行：

```bash
.venv/bin/pytest -q --tb=short tests/test_authoring_candidate_pg.py
```

这份证据验证的是安装与权限机制；本阶段没有产生真实模型费用、实际客户材料处理或生产迁移。
