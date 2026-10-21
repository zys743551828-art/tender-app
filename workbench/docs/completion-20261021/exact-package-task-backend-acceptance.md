# 精确整包手动任务：后端验收

日期：2026-10-21。此记录限定于 F11 的一条实际业务路径：用户明确选择整包及已经保存的冻结输入、执行准备和依赖计划，保存手动 `denial_check` 模板，再显式运行。保存模板或自然语言草案不运行任务、不读取原件、不调用模型。

## 实际交付范围

- `source_selection.mode=exact_package_review` 必须显式提供。输入绑定 `package_id`、`revision_id`、`inventory_id`、`frozen_input_id`、`execution_input_id`、`dependency_plan_id` 及四个对应摘要／方法摘要，不查询“最新”输入来替换用户选择。
- 模板继续使用原 `task_definitions/task_definition_versions`；运行继续使用原 `task_runs`、原生整包核查 operation、Worker、费用账本、通知和 SSE。新增的 `task_package_review_bindings` 只建立不可变关联，不新增并行的任务头或核查结果。
- 运行分为只读观察、锁外原件字节核验、最终授权及锁内原子发布。最后阶段重新检查模板、项目、来源、确切输入与方法。原件 IO 期间发生变化时，不留下半个任务、原生工作、出站消息或回执。
- 最终状态通过实际原生 operation 投影。已完成的原生核查可被新模板明确复用；同一模板、相同真实输入不会因换幂等键或并发点击重复建工作。同一实际模型输入的保留／未知费用阻断新尝试，换模板或准备复检记录不能绕开。
- 同一原 key、body、If-Match 的重试首先恢复原 ACK，即使模板随后修订、来源撤回或项目关闭。原排队 ACK 保持排队快照；当前完成状态由单独 GET 返回。取消调用实际原生 operation。通知在 coordinator/runs.notify 链路去重，并支持 SSE 和离线目录补读。
- 旧 `current_project`／`selected_versions` 路径保持原验证语义。旧 SourceSelection 省略 `mode` 时仅补旧默认 `current_project`，仍拒绝非空额外版本或冒充整包的字段。

## SQL 与权限

新增 SQL：`packages/contracts/sql/task-package-reviews.sql`。

```text
sha256 2e1c9ae9b24533402c0a8e5da43f6c5098539b6d8697098be2e2f14dc4e7e1f2
```

DDL 经独立架构复核后才在全新隔离 PG17 执行。API 仅获得关联表的读取与追加能力；Worker 无该表写入能力。延迟约束同时检查真实模板版本配置、实际 operation 种类、子命令原 ACK 及父命令的固定结果投影。将 manifest 的 schema/mode 伪装成旧任务，或篡改父／子回执，不能绕过关联完整性检查。

最初两次 SQL 验证发现 CASE 和 JSONB 运算符优先级错误，修正后重新在 fresh fixture 验证。失败轮次不计入下面的通过数。独立运输故障套件冻结过另一版 SQL 输入，不能把它的结果当成本文件最终 `2e1c…` DDL 的验收。

## 已观察的验证结果

| 范围                                           | 结果                                                         | 证据性质                                                                                          |
| ---------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| 23 项新增整包任务 PG 用例，加 4 项原生核查回归 | **27 passed，94.00 秒**，退出码 0；仅既有 Starlette 弃用提示 | 隔离 PG17、真实非 owner API/Worker 角色、实际 HTTP 与 Worker、合成原件、MockTransport；零付费调用 |
| 精确输入、草案、调度、实际契约与入口守卫纯回归 | **109 passed，4.40 秒**，退出码 0                            | 39 项新路径用例及 70 项旧路径用例；包含 4 项缺省 mode 兼容边界                                    |
| 单独导出真实 HTTP 前端夹具                     | **1 passed，5.76 秒**，退出码 0                              | 同一次真实合成流程的 18 份完整 HTTP 请求／响应及来源说明                                          |

PG 用例覆盖真实模板→任务→原生核查→Worker→结果→通知/SSE、原 ACK 恢复与当前 GET 区分、原生结果复用、同 key／不同 key 并发、锁外 IO 期间模板／来源／项目／会话改变的整件回滚、坏原件、隐式 rerun 拒绝、HTTP ReadTimeout 后未知费用禁止重发、取消零调用、直接 API-role SQL 篡改及原单稿路径回归。测试结束后隔离数据库与临时 LOGIN 已清理，55441 窗口已释放。

原 PG 完整 stdout 没有另存为独立日志；此前工具会话观察到的结果摘要保存在：

```text
/tmp/tender-completion-runtime/exact-package-task-backend-observed-results.json
```

该文件明确标记为 **工具输出摘要**，不声称是完整原始日志。真实 HTTP 原件位于 `/tmp/tender-completion-runtime/task-package-ui-fixture/`，目录内 `index.json` 记录合成来源、确切选择与文件清单。可复核的测试副本为 `apps/web/src/test-fixtures/task-package-http.json`，共享读取入口为 `taskPackageFixtures.test-support.ts`。保留服务原摘要、原时间和原 ACK，不为通过客户端校验重算。夹具不含 cookie、CSRF、连接口令、私有存储路径或生产原件。

## 可复跑命令

工作目录为仓库 `workbench/`；使用评审环境 Python。PG 命令需先由运行方设置隔离测试库的 `FUSION_REQUIREMENTS_ADMIN_DSN`，不能指向业务数据库。以下为精确测试选择；不依赖再次运行未列入本范围的套件。

```bash
WORKBENCH_ENV_FILE=review-readonly PYTHONDONTWRITEBYTECODE=1 \
/workspace/scratch/31e56f630f51/review-venv/bin/python -m pytest -q \
  tests/test_task_package_runs_pg.py \
  tests/test_package_review_runs_api.py::TestPackageReviewRuns::test_launch_records_one_atomic_job_ack_and_does_not_change_preparation \
  tests/test_package_review_runs_api.py::TestPackageReviewRuns::test_exact_ack_replay_survives_failure_source_withdrawal_and_unavailable_objects \
  tests/test_package_review_runs_api.py::TestPackageReviewRuns::test_different_request_key_reuses_exact_existing_run_without_another_job \
  tests/test_package_review_runs_api.py::TestPackageReviewRuns::test_real_worker_publishes_bound_result_and_duplicate_delivery_has_no_second_call

WORKBENCH_ENV_FILE=review-readonly PYTHONDONTWRITEBYTECODE=1 \
/workspace/scratch/31e56f630f51/review-venv/bin/python -m pytest -q \
  tests/test_task_package_inputs.py \
  tests/test_task_draft_interpreter.py \
  tests/test_task_scheduling.py \
  tests/test_task_actual_contracts.py \
  tests/test_task_guard_entrypoints.py

WORKBENCH_ENV_FILE=review-readonly PYTHONDONTWRITEBYTECODE=1 \
FUSION_TASK_PACKAGE_UI_EXPORT=/tmp/tender-completion-runtime/task-package-ui-fixture \
/workspace/scratch/31e56f630f51/review-venv/bin/python -m pytest -q \
  tests/test_task_package_runs_pg.py::TestExactPackageTasks::test_actual_template_task_worker_result_notification_and_original_ack
```

Ruff 检查及格式、Mypy、Bandit 与 `git diff --check` 定向通过；最终共享树的全后端、前端、部署和发布门禁由根验收记录单独汇总，不与上述用例数相加。

## 保留的边界

本路径只支持明确输入的手动 `denial_check`。整包定时、事件触发，以及 `scoring_review`、`supplement_impact`、`chapter_suggestion` 三类任务尚未获得这条整包输入接线；不能由旧单稿实现推定为整包能力。产品调度器仍须独立启用，和本对话的自动接续无关。

结果是已声明范围的核查，`overall_coverage=partial`、`formal_scoring_eligible=false`、`submission_eligible=false`、`formal_decisions_created=false` 保持不变。模板说明不能授权自动确认、评分、提交、发布或修改原文。`rerun:true` 不会自行换输入；用户须先保存带明确复检理由的新执行准备，再保存新的模板版本。模拟模型传输验证的是协议与故障恢复，不能作为模型效果或完整语义质量达标的证据。
