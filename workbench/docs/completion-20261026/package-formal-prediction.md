# /3 正式预测消费检查点

本阶段接通手动消费闭环，未声称 FR-002 或整个项目已全部完成。原始需求复核仍有报告投影/任务接线代码，见 `fr-audit.md` 最新有限清单。

## 真实代码调用链

`PackageMaterialExecution` → `PackageFormalPrediction` →
`POST /api/v1/bids/{bid}/technical-scopes/{scope}/formal-predictions` →
`Predictions.execute` → 短事务 `package_prediction.prepare` / 现有 `read_certificate` →
事务外 `package_model_live.producer.Executor` → 原件、原始响应、请求/槽位身份复验与既有 ridge 推断 →
第二短事务重新 prepare/认证复检 → `package_prediction.commit` → 不可变结果 → 当前资格复检后的回执。

请求只包含认证 ID 和命令 UUID；不接受数值、verified、来源种类、模型路径或替换输入。认证绑定的原生业务 scope/bid、完整输入、模型/artifact、私有交接引用、认证方法和预测方法均固定。此阶段只消费证书明确绑定的输入，不扩展到另一项目或版本；不是跨范围模型自动推广。

使用现有非 owner API 身份和私有存储注入，不配置真实账号或发任何外部请求。服务端可信装配示例（本轮没有执行）：

```python
app.state.package_prediction_service = Predictions(
    NativeTransactions(connection),
    producer.Executor(private_store, artifact_index),
)
```

未装配时 POST 返回 503。GET 历史回执不需要消费者装配。私有路径与 index 只能由现有宿主注入，HTTP 不接受此配置；默认不启用消费。可选新库脚本 `deploy/sql/package-formal-prediction.sql` 安装于认证脚本之后，未在本环境执行。

## 不可变、撤销与恢复

每个技术 scope 最多固定一个结果，不能通过多模型/多次请求择优。命令 UUID 在浏览器成员/bid/scope 隔离的本地存储中先保存再发送；断网、丢 ACK、重新加载以同一请求恢复，不创建新命令。首次明确的应用拒绝可清除未执行命令以更正认证编号；未知网络结果或已恢复请求不会清除。重复 CPU 计算不产生模型调用或第二个结果。

推断前、落库前和数据库原子写入边界复验认证；资格撤销/过期、源或方法漂移、跨成员、synthetic/retrospective、已知成绩/已提交状态拒绝。推断过程不持有 SQL 连接；计算输入被修改也拒绝。数据库终态撤销锁与证据锁沿用原机制。

GET 回执区分 valid / hidden / stale；有效结果包含候选冻结的约 80% 校准区间、拟合/开发/校准项目组数和原生 final 报告的项目 MAE，SQL 对区间边界和来源再次比较，不根据合成效果选择区间。失效或隐藏时所有这些数值均不返回。UI 区分未获得有效结果、处理中、有效结果及失效历史；旧选择的迟到响应丢弃，畸形恢复记录拒绝继续。已配置但无合格证据仍不可用，不以测试 fixture 认证真实模型。

## FR-009/011/013 接线

`package_prediction.submission_pair` 从不可变预测、整包提交绑定及 scope 身份匹配中读取唯一配对：预测严格早于提交，模型/方法一致，认证在时间范围有效且未撤销，包修订、规则依据、身份和清单匹配，多候选拒绝而非挑选。不会将单正文结果借给整包。

`packages/package_prediction/metrics.py` 接入现有 `metrics.predictions.eligible_pairs`，复用官方结果已核实、成绩类型/满分、知晓时点、官方来源与提交身份校验。没有生成新标签或合成官方分。显示分数开关只隐藏数值，不阻止新 /3 路径内部形成配对，符合原始 FR-013；历史单正文路径保持兼容。

证书只适用于已冻结输入，UI 明确该范围。

### 隐藏与配对修正的需求依据

原文依据：`/workspace/tender-docs/02-业务与产品/一期方案与验证计划.md` 第 4.3 节（约第 213 行）：

> 项目关闭“显示预测分数”（`show_score`）时，报告与 Word 报告只列可能的失分点（条款、评估、正文证据），不出现估计值、区间与估计失分；预测照常进行，照样形成配对。

本工作台当前设置字段为 `show_prediction`，未改名冻结契约。具体修正：删除新 `/3` `submission_pair` 和 `eligible_pair` 对隐藏设置的配对排除，保留预测读取 API 对 value/maximum/low/high/训练组数/误差的隐藏，以及 UI 隐藏状态。度量仍必须满足唯一事前预测、提交绑定、合格认证、官方成绩及来源/身份校验；关闭展示不是资格捷径。

测试原先错误地期待新整包隐藏项返回 `prediction_hidden`，与上述明确需求冲突。改后同一合法固定预测在隐藏时仍可内部配对，并另测 UI/API 的数值隐藏和无资格拒绝，不是为了全绿移除安全校验。`test_package_submission_consumers.py` 的旧单正文隔离断言保持：未安装新 producer 时依然不可配对；只补新原生 readiness 查询的测试替身，没有把旧正文记录升格。旧单正文路径的既有行为本轮未改写。

旧 `review_views.py` 和旧 scoring/registry API 的 unavailable 仍描述单正文/旧 artifact，不把 `/3` 正式结果塞入不兼容的旧对象。本阶段新增有真实正向代码的 scope API 和 UI；正式报告/Word 的统一投影仍待下一阶段，不能据此宣称全界面完成。

## 验证与剩余边界

最终冻结版本后端全量 **4576 passed / 2424 skipped / 0 failures / 0 errors**（803.14 秒）；前端 **193 文件 / 1952 tests 通过**。Ruff check/format（1198 文件）、mypy（751 源文件）、Bandit、前端 format/lint/typecheck 全部通过。前端 build 通过，保留既有 chunk-size 提示。旧执行/派发/资格/任务四个方法摘要保持不变。

失败与修正记录：首轮后端全量 4575 通过 / 1 失败 / 2424 跳过（785.55 秒），在运行过程中修正了隐藏设置语义，已加载的旧隐藏排除断言与新实现冲突；该轮不是冻结快照，不作为最终通过依据。最终轮使用完整冻结代码重新执行并通过。后端定向最终 19 项通过；前端初轮 3 项失败/2 个未捕获错误来自测试 mock 漏导出 ApiError，修复后通过；后续补首次明确拒绝的恢复测试，全部包含在 1952 项最终回归内。

跳过不计通过，完整 skip 原因与首轮/最终轮日志分别归档。补丁位置 `/workspace/scratch/tender-prediction.patch`；测试摘要、日志和文件清单位于 `/workspace/scratch/tender-prediction-validation/`。

未实际运行：原生 PG17 脚本/并发/权限/完整提交配对、真实模型认证/付费/线上流量、Word03 转换和真实效果验收。没有生产连接、部署、PR、合并或新权限。
