# FR-012 固定预测持久任务检查点

本阶段基于 `e5a01dc9a870594d6371dace8b624268c444b1e9`，沿用 `render-acceptance-20261026`。原执行环境断连后已恢复同一 checkout，保留未提交文件；未从旧 head 重建。远端核对时本分支未变化，fusion/bid-workbench 为 `462ec226013b011a40c204fe1c65541c4dbfbc25`。

## 实际调用链

`PackageFormalPrediction` → `/prediction-tasks` POST → `Jobs.submit` → 原认证/材料 prepare → 私有 CAS 固定输入 → 再次权威检查 → 原 Command/operation/operation_steps/outbox。POST 只接受 certificate_id 和 command_id，操作者来自会话。

现有 review lane Worker 接收 `package-prediction/1` → 原 acquire/lease/fence/retry → 私有输入复验及原 Executor 计算 → 原 finish 写仅含两个私有摘要的 effect。Worker 不使用 API 连接，不调用认证/预测写入 SQL，不发模型请求；Executor 的 store/index 仅接受本地路径。计算和对象 I/O 在数据库连接作用域之外。

现有 API-role `tasks.runner.cycle` → 显式配置的 `runtime.drain` → `Jobs.advance` → 资格/输入/方法及私有结果复验 → 原 Predictions 的结果检查 → 短事务再次复验并写原预测结果及发布审计。协调器不依赖浏览器且不要求已有 task_definition；未注入时无操作。API `/advance` 提供相同恢复入口。私有对象不登记公共文档、不授予下载链接。

UI 在提交前保存命令，丢 ACK 重用同一命令；可查询排队/运行/重试/待发布/已发布/阻断/取消状态，恢复发布和取消。发布后通过原预测读取接口展示当前有效结果，并进入原统一报告选择与 JSON/Word 出口。`prediction_ready` 不是统一报告已经 ready；报告仍须选择同冻结范围核查及可选报价，并通过最终快照复验。

## 并发与失败边界

- 复用 bid 行锁及专用 advisory lock；不同 nonce 不能为同 scope 叠加有效任务。同命令跨成员/范围/认证拒绝。
- 原 Worker 校验 owner/fence/dispatch generation/租约；取消使未结束计算失去发布资格；即使计算已完成，API 发布仍检查取消标记。
- 原结果写入与 published 审计同事务；提交 ACK 丢失可重读。认证撤销、输入或方法漂移、篡改结果均不能写预测；不可恢复失败记 blocked，避免协调器无限重试。
- 认证过期/撤销及设置隐藏仍由原读取/报告出口重新判断。任务回执不包含分数；已下载字节无法追溯撤回。
- 该 CPU 预测消费已完成的固定材料，不产生新 provider 费用，也不替代上游调用预算/资格/未知费用门禁。
- 不增加数据库表、角色或权限；原生 SQL/role/并发行为本环境未联合验收。使用既有 audit/commands/operations/effects，不能将模拟连接说成 PG17 验收。

## 有限剩余代码（不是外部环境）

本检查点完成**已授权固定预测请求的持久执行及自动发布**。原 FR 4.12/4.13 还要求“资料齐了自动开始/开始评审标记推进”：当前新 UI 仍明确选择证书并提交预测，尚未将项目自动评审的输入冻结事件绑定到唯一合格证书并调用本持久入口。`packages/tasks/runs.py` 的旧 scoring_review 仍拒绝正式资格，不能把它当已接新任务。因此 FR-012 项目自动发起这一接线仍未完成，应复用本入口和既有启动意图，不另建队列，不猜测跨输入证书资格。这是下一有限编码项，不是要求真实数据或重新批准协议。

四部分统一报告代码保持原阶段范围；Word03 真实转换、PG17/S3/Kafka、真实认证/质量、用户组合验收及主文档仓同步另列未验收。未实际配置宿主、启动长期调度、创建模型认证或调用外部模型。

## 验证记录

恢复前第三轮定向：24 passed、2 failed（取消和篡改已返回终态，旧测试仍期待异常）。恢复后修复终态断言并补不写结果检查，同时使方法漂移进入 blocked：26 passed。没有删除反例以换取全绿。静态检查首次发现缺少 `publishing` 属性声明，已补类型声明；随后 mypy 768 源文件通过，Ruff 1218 文件检查/格式通过，Bandit 通过。最终完整回归与构建结果见本节后续记录；skip 不算通过。

执行策略补齐：新增 `apps/worker/execution-policy-11.json` 登记固定预测 handler，并更新现有初始化/编排默认策略路径。保留协议 10 及目标契约；沿用 review topic/lane，不增加 topic 或外部访问权限。原策略覆盖测试发现遗漏后补实现，没有放松测试断言。四个既有材料执行/调度/资格/任务方法摘要均保持原值。

首轮完整回归：4628 passed、2 failed、2424 skipped。两项失败为执行策略 handler 清单遗漏及实际 OpenAPI/前端生成契约不一致；已新增策略 11 并重新生成真实 API/前端契约，保留原测试。首轮日志及 JUnit/summary 独立归档，不覆盖。最终轮使用修正后的冻结代码。

最终完整后端：**4630 passed、0 failed、0 errors、2424 skipped**，905.21 秒。策略及契约定向 9 passed，任务定向 26 passed。前端最终完整回归：195 文件、1971 测试 passed；格式/lint/typecheck 通过。2424 skip 包含需显式临时原生 PG17/非 owner 角色、S3/Kafka/Word 及历史外部恢复输入的用例，逐项原因保存在 summary.json；不将其计入成功验收。原生服务/真实流量没有运行。

可审查证据：`/workspace/scratch/tender-prediction-tasks-validation/` 保留首轮与最终日志、JUnit、summary；`/workspace/scratch/tender-prediction-tasks.patch` 为提交补丁，文件清单同证据目录 `files.txt`。未创建 PR、合并或部署。

前端生产构建通过，保留现有大 chunk 提示，不为本轮扩大打包重构范围。四项既有冻结方法摘要最终复检一致。
