# FR-002 阶段三：/3 门槛冻结与原生 final 报告登记

基线 `cbf9222`。本阶段交付可调用 API、应用用例/事务端口、原生持久化代码和实际指标消费者；**没有签发认证，也没有实现认证过期/撤销接口**。原因不是阈值方向待决，而是 `/3` 影子观察和回退验收尚无对应的原生证据生产链。不能拿旧模型事件替代新 artifact 的证据。

## 确定范围已实现

新协议 `score-business-admission-protocol/2` 只绑定 `registered-package-score-artifact/1`。旧 `/1` 原样保留、不接受新 family。复用既有 BOUNDS 的误差/增益/覆盖语义；所有阈值必填，**不提供默认值**。`/2` 用显式十进制字符串保存数值，防止 SQL/JSON 浮点重编码改变冻结身份；interval_level 只能显式选择现有方法的 `0.8` 或 `0.9`。这不是更改精度门槛，也不替操作者选基线或阈值。

服务器上下文提供 model/artifact/cohort/cohort-membership/candidate/training-method/完整训练材料引用/final-manifest 身份。请求必须完整绑定这一上下文。冻结使用已有 registry/current_cohort/曝光桥的权威与锁；同 cohort 唯一协议，不能换个 model ID 重填。已曝光拒绝补填。保存冻结事务 ID 与时间；原生报告登记同时要求冻结早于曝光、不同事务、曝光已提交。SQL 函数固定 UTC，避免回执摘要因会话时区变化漂移。

报告只能从已有原生 evaluate job 的成功 result、feature_final_inputs、feature_final_predictions、exposure、final_labels 引用中派生。核对模型/候选/输入/预测/标签/来源身份，客户端只提供任务 ID 和保留的 packet digest，不接收指标、origin、verified 或 accepted 标记。报告引用和原生快照 append-only；来源仍有效时重复 key/body 恢复原回执，变化请求拒绝。若来源后来失效，写入复验可拒绝；GET 协议历史回执仍可恢复冻结事实，不授予当前资格。报告 GET 仍要求所保存方法版本可由当前消费者校验。

应用消费者核对评价方法与预测冻结方法版本，然后精确比较 project MAE、所选基线 gain、success coverage 与所选区间 coverage。缺值/非有限值/无样本拒绝，指标不达门槛返回具体 false。即使全部 true，也始终 `formal_eligibility=unavailable`、`certification_issued=false`、`snapshot_only=true`。历史回执不是当前源有效性或正式认证的证明，后续签发仍须重新读取权威。

## 实际入口

统一前缀 `/api/v1/package-model-admission/models/{model_id}`：

- GET `/context`：读取固定绑定和原 artifact。
- POST `/protocol`：`document`、`reason` 与稳定 Idempotency-Key；使用既有登录/Origin/CSRF。
- GET `/protocol`：恢复冻结回执。
- GET `/evaluation-jobs/{job_id}/report-preview`：原生报告及其 packet digest、指标判定。
- POST `/report`：`evaluation_job_id`、`expected_packet_digest`、`reason` 与稳定 Idempotency-Key。
- GET `/report`：读取已登记报告并重新执行版本/门槛校验。

没有增加专用 UI，也没有“点击批准即认证”按钮。六个入口已挂入现有 HTTP 服务、actual OpenAPI 和生成操作清单；不是仅新增工具函数。应用用例不直接依赖数据库或 HTTP，连接由构造器端口注入，每个操作一个拥有连接的事务。

`deploy/sql/package-model-admission.sql` 只适用于已审全新初始化：要求已有 package registry，且 native cohort 为空；不加入默认部署、不执行 DDL、不新增 LOGIN/真实凭据。新表直接写权限不授予 API，只开放受控函数。

## 实测与未验收

最终定向 58 passed（新阶段 34、旧协议 24）。包括每项门槛缺失、decimal 类型/边界、旧新版本隔离、候选/组/曝光/方法漂移、曝光前后时序、原生已有 evaluator 的实际计算输出、API 禁止上传 verified、持久回执消费和固定摘要漂移。所有数据均为合成机制夹具，**不证明真实效果**。Starlette/anyio 有既有弃用提示。

SQL 锁序、提交时序和权限仍只做代码/静态检查，未执行 PG17 的并发、撤回和跨角色验收。既有测试镜像/隔离数据库条件仍缺；未连接生产或通过新凭据绕过。

## 下一有限代码阶段与证据

`deploy/sql/score-execution.sql` 的 persist_shadow 只接受旧 `model_release.registrations`，还明确强制 unavailable/null 数值；`model-governance-release.sql` 的回退事件也绑定旧模型。`package-score-execution.sql` 明确不写旧 shadow/model 表。此次不能将它们当 `/3` 真实影子或回退证明，也不信任任意上传文档或通用 confirmed 决策自行升格。

下一阶段先补 `/3` 有权威输入/方法绑定的影子观察和回退验收生产/登记代码，再完成认证签发、有效期、撤销与恢复；仍仅合成机制测试、不实际签发真实认证。之后接正式预测持久化/API/UI/metrics。没有新产品阈值决策阻塞，剩余属于确定代码及外部验收条件。

FR001–013 有限对照继续见 `fr-audit.md`：FR002/009/011/013 的相关正式正向路径仍未完整；其余已有代码的环境/真实用户验收结论不变。

初轮完整回归发现 1 项失败（4468 passed、2424 skipped）：新 ReportRequest 名称与既有报告契约冲突。已改为 PackageAdmissionReportRequest/PackageAdmissionFreezeRequest 并重新生成 actual 契约；未修改旧契约或放宽断言。组合契约 6 项、OpenAPI 快照 4 项复跑通过，完整回归继续复核最终版本。

前端复跑还暴露 1 项既有异步测试等待问题：PackageAuthoringUI 在按钮出现后立即断言可用，但可用性还等待输入核验。参照同组件已有用例改为 waitFor(toBeEnabled)，未修改产品代码或放宽可用性断言；相关两个测试文件复跑通过，前端完整复跑结果另记。首次前端完整 1944 passed，中间一轮 1943 passed/1 failed 的日志保留。

最终版本完整回归：后端 4469 passed、2424 skipped、0 failures/errors；前端 192 文件、1944 tests passed。ruff/format（1168 文件）、mypy（726 源文件）、bandit 与前端 format/lint/typecheck 均通过。原失败与复跑日志分别保留，跳过项不计验收成功。四个材料执行方法摘要未变。
前端构建通过，只有既有 chunk-size 提示；未部署。
