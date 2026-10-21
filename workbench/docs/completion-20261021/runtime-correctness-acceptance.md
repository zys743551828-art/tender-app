# 旧运行缺陷修复：实现与验收证据

范围：证据列表/详情来源状态、公平对账扫描、独立入口任务输入守卫。基于 `work/bid-workbench-completion-20261021` 的共享工作树实施；提交号由统一提交步骤记录。没有扩展正式评审权限或调用外部模型。

## 变更及通过场景

| 问题 | 实现 | 回归证据 |
| --- | --- | --- |
| 文档证据列表硬编码 published，详情又按整份文档的任意解析判断撤回；列表每块再查一次 DB | `apps/api/views.py` 共享批量投影，按精确 `parse_source_id` 查询完整祖先：任一撤回显示 withdrawn，未知/缺头/候选显示 candidate，其余 published。列表直接批量读取块和页面；详情复用同一投影 | `test_evidence_status_projection.py`：普通原件撤回、Word 祖先撤回、旧解析撤回不影响新解析、候选/缺头/未登记来源、缺失证据 404、未解析文档 pending、301 块固定 4 次查询。修复前 7 失败、2 通过；修复后 9 通过 |
| worker 与 review coordinator 每次只扫最前 100 项，长期占用的首屏阻挡后续取消/准备 | `packages/domain/bounded_sweep.py` 保存当前轮次的固定最高键，以 `(created_at,id)` / `bid_id` 有界推进，扫完或耗尽即重开新轮。扫描仅提供工作候选；原锁、lease、取消、fence、次数预算和重派逻辑保持 | `test_reconciliation_fairness.py` 执行实际两个循环：首屏持续占用时第 101 项推进；持续有新高位任务时迟到老记录在下一轮重访；同时间戳有稳定 id 次序；上界被删除后仍轮回；每轮最多 100 项；`--once` 一页；研究/正式评分专属 lane 不混入普通 worker。修复前 6 失败、5 通过；修复后 11 通过 |
| 只有 Web import 注册任务评审输入守卫，独立 coordinator 和 task runner 直接启动时拒绝合法任务 | `packages/tasks/review_runtime.py` 提供无资源副作用的显式装配，Web、review coordinator、task runner 各自调用；`reviews.py` 单独导入仍默认拒绝有 task_binding 的输入 | `test_task_guard_entrypoints.py` 在四个全新解释器里验证：domain 默认拒绝保持；三个入口装配同一个 exact guard；独立入口没有 import Web，也没有打开 DB/检查运行角色/启动消费。修复前独立两个入口失败；修复后 4 通过 |

来源的 publication status 只是显示观察，不能替代新使用时的授权、时间窗口和来源完整性门禁。该修复不会把已过期但仍 published 的记录变成新用资格，也不会重写历史引用正文。

游标属于长期运行进程的一轮扫描；重启从头开始。`--once` 保持原有的单页诊断语义，不能把反复启动 `--once` 当成完整数据集扫描证明。本轮没有新增生产容量结论或数据库索引。

## 实际执行结果

环境：Python 3.12；`WORKBENCH_ENV_FILE=review-readonly`、`PYTHONDONTWRITEBYTECODE=1`。专用回归没有使用付费供应商。

```sh
python -m pytest tests/test_evidence_status_projection.py \
  tests/test_reconciliation_fairness.py tests/test_task_guard_entrypoints.py \
  tests/test_application_composition.py tests/test_task_actual_contracts.py \
  tests/test_task_scheduling.py -q --tb=short
```

结果：**51 passed**（包含上述 24 个新用例）。针对 11 个变更 Python 文件的 ruff check、ruff format --check 通过；8 个实现文件 mypy 通过；实现文件 bandit 通过；`git diff --check` 通过。

## 验收边界

- 来源和对账回归使用 SQLite 执行实际 SELECT/JOIN/递归和取消 UPDATE，只适配 PostgreSQL 占位符/类型转换/行锁语法；PG 锁、audit 和 coordinator tick 是明确的观察端口。没有宣称真实 PG/Kafka 并发、租约竞争或吞吐验收通过。
- 独立解释器回归证明装配和默认拒绝边界，不替代实际非 owner 角色下“受理任务→独立进程冻结→worker 完成”的部署集成回归。
- 当前任务输入守卫依旧是旧单正文任务模块的 exact guard。正式整包调度应使用整包冻结输入的独立约束，不能把该修复作为整包正式启动资格。
- 提交前应独立复核此 diff，统一集成过程中若扩展 handler/lane，只复测实际受影响的集成路径，不把尚在开发的模块算入本表通过范围。
