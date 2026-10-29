# 同一冻结范围的四部分统一报告

基线 `64534b394f3adc851f54b5a1188be1a6a8ef8552`。遵循原方案 4.8：报告汇总已有事实，不产生判断；Word 四部分为否决/强制项、分类问题、评分预测、报价。报告导出为同步接口；FR-012 的预测持久任务是另一执行链，不能把报告同步请求冒充队列任务。

## 有限实施范围和生产者核查

| 部分 | 既有生产者 | 本次组合与消费 |
|---|---|---|
| 否决/强制项 | `bid_package_review_run_repository` 的冻结 matrix | 取 disqualification/mandatory；保留机器判断、适用性来源与引用；不由报告自行判定满足 |
| 问题清单 | 同一 run 的 violated/not_found/unable_to_judge 行；`bid_package_review_decision_repository.current` | 同一结果摘要与逐行摘要核验人工处置，处置不覆盖机器原结论。原整包 producer 未测的矛盾/范围检查明确列为未测，不补假零 |
| 评分预测 | 原认证 `/3` prediction、原材料复验与 `MaterialProjection` | 认证/固定输入再读，原始材料复验，隐藏时不投影估计、区间、误差或档位差额 |
| 报价 | 既有 `pricing.repository.simulation_view` 和原生 applicability | 明确选择已有模拟；要求包、修订、权威修订、清单、身份摘要相同；过期拒绝，未选写不可用，关闭模块不输出第四部分 |

实际链路：`PackageFormalPrediction` → `PackageUnifiedReport` → 同一预测 command 下的 `/unified-report` 或 `/unified-report.docx` → `UnifiedReports` → `NativeUnifiedTransaction` → 既有三类读取器 → 无 SQL 连接的原件复验/四部分组合/原 `assemble_report` → 最终事务重读全部身份 → 返回。

UI 统一入口替代原配套报告入口，避免一份报告刷新后另一份报告仍显示旧分数。原配套 API 仍独立兼容，没有把它的 schema 改成统一报告。UI/Word 从同一 `sections` 投影消费；JSON 另含完整响应矩阵、各原文引用及文档身份，复用原页查看组件。人工处置明确独立显示。报价未知是未知，不按零分展示。

## 快照和拒绝条件

- `package-unified-review-report/1` 是组合投影版本。`snapshot_id` 为统一权威快照的摘要，覆盖认证回执、模型/输入、所选成功评审、人工 heads、项目展示设置、所选报价及组合方法摘要。
- 原 run/result、预测和报价记录继续保存在既有不可变系统；没有另建平行证据表。本同步快照 ID 是响应内容身份，不是新的持久任务 ID，也没有声称支持按这个摘要恢复一条不存在的任务。
- 只允许同一 scope 的最近完成成功评审，按完成时间排序核验调用者选择，不暗选新输入。无完成评审为 404；取消/失败评审不能组合。
- 对比全部原件的文档、解析、文件摘要集合，并校验原结果 digest 与既有人工作用域/逐行摘要。报价不得从其他修订或旧单正文公式借用。
- 两次短事务外执行材料读/CPU/Word 序列化。生成期间隐藏、撤销、报价、人工处置、输入或最近完成评审发生变化，最终摘要不同即拒绝输出。
- 成功响应 `private, no-store`；Word 是本次资格复验后的字节，不给旧对象授权。已下载字节不可远程撤回。当前读快照与未来真实环境并发事务验收有区别。
- 默认消费者未装配时 503，沿现有 API 身份/私有 CAS 注入，不读取或新增任何真实凭据。无模型调用、认证签发、生产路由变化或新数据库权限。

## 原需求边界

四部分现在是一个组合出口，不再仅是独立预测附件。完整 matrix 附录与原页引用共用同一输入。统一报告保留原整包核查 `partial`、未测检查和不具备提交资格的限制；不能用“有四个标题”授予质量/完整性资格。真实 Word→PDF、全部用户验收和原生并发未运行。

FR-012 仍是确定编码项：将预测授权/固定输入接既有 operation/outbox/Worker，Worker 仅计算，API 控制面复验发布；任务回执不能携带绕过隐藏的数字。取消、过期租约、重复投递与丢 ACK 必须在该真实任务链测试，**本次没有把同步报告反例当作这些测试通过**。不需要等待真实数据或新增产品决策即可继续写这项代码。

## 验证记录

定向后端 18 通过；前端 17 通过。覆盖四部分 OOXML、隐藏/禁用报价、共同快照、重复请求字节一致、原件/报价/输入/人工摘要漂移、生成中撤销/隐藏/取消结果、默认关闭、原生适配器顺序及 HTTP 缓存策略。首轮 1 个反例失败：夹具共享对象使“文档变化”同时改变预期集合，暴露纯组合缺少原结果摘要校验；已增加该校验，未删除反例。初始 Ruff 单行语句格式问题亦已修复。

完整回归、构建与提交证据将在终态后补入；运行中不记为通过。

### 下一阶段任务接线的已确认边界

`packages/tasks/runs.dispatch` 的旧 `scoring_review` 分支仍明确拒绝，不能直接删除这一守卫。新增明确固定 scope/certificate/input 的选择模式后，才可路由到受控预测用例；旧 current_project/selected_versions 保持拒绝。复用 `runtime.enqueue_plan` 的 operation_steps/outbox 与 `apps/worker/engine` 的 fence、generation、取消和 effect_receipts，不再建立第二套队列。

API 接受时将授权来源与私有计算输入引用固定；消息/通用进度只传引用和摘要，不传分数或完整权威材料。Worker 消费固定原件并以私有结果引用发布，原 engine 保证过期执行者不能提交。API 控制面只从成功的受控 operation 读取结果，再复验当前资格/输入/展示与取消状态后调用原预测持久化。该链仍未实施/测试，不能将本阶段 HTTP 重读测试作为任务恢复证明。

### 最终验证终态

- 后端默认完整 aggregate：4,604 通过，0 失败，0 错误，2,424 跳过，791.47 秒。原生隔离环境未就绪的跳过不是验收通过，完整原因见 `summary.json`。
- 前端全量：195 文件、1,968 测试通过；format/lint/typecheck 通过。
- Ruff check/format：1,209 文件通过；mypy：760 源文件无错误；Bandit 通过。四个既有执行/派发/资格守卫/材料任务方法摘要与基线相同。
- 首轮定向失败及修复后结果分开保留。可审查补丁 `/workspace/scratch/tender-unified-report.patch`；日志/JUnit/摘要/文件清单 `/workspace/scratch/tender-unified-report-validation/`。

没有执行原生 PG/S3/Kafka、真实模型、认证签发、生产路由或 Word03 转换；这些是独立验收边界。下一阶段仍需实际任务接线代码，不是等待新授权或真实数据。

最终前端构建通过（保留既有大 chunk 警告）；`git diff --check` 通过。
