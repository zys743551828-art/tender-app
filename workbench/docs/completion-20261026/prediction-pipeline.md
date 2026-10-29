# FR-012 项目启动意图与固定预测接线

基线 `86c842a7e185d19366fb5b4419c48983040a7fb1`，独立分支 `render-acceptance-20261026`。复用已有整包冻结范围、scope review、认证、预测任务及统一报告，不新建任务队列、计费链或证据仓库。未运行真实模型、认证签发、数据库或部署。

## 生产者到消费者

1. 现有 `bid_package_technical_scopes` 提供固定材料范围和操作者；`bid_package_review_runs` 提供实际开始核查的命令及冻结输入。项目 `auto_review` 开启时取资料范围冻结命令为触发身份；关闭时取已有同范围核查命令作为明确开始意图。没有实际核查记录时分别显示 waiting_review/waiting_start，不代造核查、准备输入或依赖计划。旧单正文评审记录不能冒充整包范围。
2. 原有核查流水线必须产生同操作者、同 scope 的最新成功结果，输入、结果摘要与既有 report binding 均校验。未完成、失败、取消或缺结果时不提交预测。原 producer 的部分/未测语义覆盖不会被改成完整检测或评分资格；后续仍须独立认证与完整材料准入。
3. 新窄 SQL 选择接口逐一调用既有 `package_prediction.prepare`；API 还使用原 Certificates 规则复验。仅一个合格候选才能继续；零个或多个候选明确阻断，不按时间、分数、模型名或自定门槛排序挑选。未安装接口返回 unavailable。
4. 在已有 bid/advisory 锁内写不可变 audit 意图：固定 actor/bid/scope、唯一 certificate、确定性 command、review/input/result/trigger 及协议方法摘要。原 `Jobs.submit` 负责材料复验、命令、operation/outbox；原 Worker 只计算，不使用 API 凭据。新增 GuardedTransaction 在准备、入队及最终提交时检查同一意图，CPU/对象 I/O 保持在短事务外。
5. 现有 `tasks.runner.cycle` 调用有界恢复扫描，分页游标只优化扫描，持久状态来自原 audit/operations。浏览器关闭不影响推进；进程重启从头扫描只会恢复同一 command。取消与发布共用锁；没有接受回执的中断可恢复。新 SQL BEFORE INSERT 守卫使用同一 audit 意图拒绝取消/版本上下文变化，旧协调器也不能绕过这一最终数据库边界。
6. 项目完整材料工作区挂载自动推进状态；读取与恢复接口不接收客户端证书、verified 标记或输入材料。ready 状态要求原预测仍有效且同范围统一报告元数据通过原读取/组件复验；UI 自动带入冻结评审编号，仍使用原四部分 JSON/Word 路由做完整材料、隐藏、最终快照复验。ready 表示可请求报告，不表示 PDF 转换或独立质量验收已通过。

## 宿主及数据库接线（本轮未执行）

使用 `packages.package_prediction_pipeline.composition.api(app, predictions)` 和 `.coordinator(predictions)` 组合原生依赖；它们复用原任务配置并安装意图守卫，不读取/保存/发现凭据。Worker 保持上阶段 `package_prediction_tasks.composition.compute(executor)`。未配置时 UI/API unavailable，扫描 no-op，不启动长期进程或真实调用。

可选新库扩展 `deploy/sql/package-prediction-selection.sql` 位于原 `package-formal-prediction.sql` 后；只增加现有 tender_api 的受控函数入口及结果表触发器，不给 Worker 认证读取权限，不增加外部账户权限，不修改旧 SQL 文件或方法摘要。本环境没有应用 DDL，原生 SQL 权限、事务和竞争属于未验收。

新协议 `package-prediction-pipeline/1` 固定自身 Python/SQL 方法摘要；已保存意图不随方法或上下文漂移重新解释。原任务协议、四项材料执行冻结方法及旧模型版本不变。取消/固定失败后不能悄悄选择另一模型或把新输入塞进旧 scope；需要正常的新冻结上下文。

## 验证与有限边界

定向机制覆盖：既有意图→接受→原 Worker 计算→发布→报告 readiness，重复/丢 ACK、等待开始/核查、零/多个认证、取消前后和对象写入竞态、撤销/上下文/方法变化、发布中迟到变化、跨成员、错误取消编号、关闭配置、分页恢复、HTTP 封闭请求、数据库守卫结构、显示开关不阻断计算。额外使用真实本地私有 CAS 和现有 Executor 消费合成材料，验证报告证据与隐藏投影；不是真实认证或质量结论。

前端首次定向出现 6 项材料申请测试调用次数失败：新状态子组件会在挂载时读取 API。原材料命令单元测试隔离该子组件，保留原请求/幂等断言；独立组合测试验证它确实挂载于同一工作区，另测迟到响应、伪造 ready/跨成员、取消固定身份以及同范围统一报告消费。修复后 38 项定向通过。没有为通过测试删除资格或隐藏约束。

本轮没有新产品策略等待。已声明完整范围和现有核查流程中的自动预测接线有实现；新材料必须形成正常的新冻结范围，缺真实合格认证时仍明确不可用。没有为旧单正文版本静默制造整包身份，没有声称原生环境、真实评分精度或整个用户交付验收完成。

首轮前端全量：1979 passed、1 failed。失败位于旧技术范围 ACK 恢复测试的总调用次数断言：恢复成功挂载新状态组件后多出只读请求。新断言明确保持原 POST 的 body/etag/key，验证其后唯一 GET 仅查询已保存 scope 的 pipeline，且完全没有重新请求 technical-scope-context；没有简单取消次数或顺序约束。该测试定向复验通过，前端全量再跑；后端仍保持同一轮完整回归，没有并行重复启动。

全量期间审查补充了实质正确性修复：仅 package/revision/inventory 相同不能证明核查与技术范围使用完全相同的文档集合。自动准入和数据库最终发布现同样核对 document_version_id/parse_run_id/file_digest 集合、重复/缺失成员及核查结果摘要；这是将既有统一报告的校验提前到自动路径，未改变认证门槛。增加缺项、额外成员、重复、解析漂移、字节漂移、畸形集合反例。原生 SQL 仅代码/结构检查，未执行。保留修复前全量日志，最终后端回归顺序复跑，不并行启动第二轮全量。

同一固定 command 不能经旧手动入口替换另一张认证：API 事务准备阶段检查计划中的 certificate，最终 SQL 守卫也检查同一绑定。定向反例验证拒绝发生在原准备/入队/写入之前。未新增资格规则或选择阈值。

首轮后端完整回归：4648 passed、2 failed、2424 skipped，977.96 秒。两个失败为运行中已收集的旧 `test_native_guard_precedes_original_prepare_enqueue_and_commit` 和 `test_native_context_binds_existing_start_and_ignores_score_visibility`：前者原先用空参数测试 prepare，新增认证身份检查后须使用真实调用参数并验证错证书；后者原先省略文档集合，新增完整绑定后补明确文档/解析/摘要及漂移反例。冻结修复版定向 26 项、单独错证书反例均通过；首轮日志和 JUnit 保留，后续从头重新收集并执行最终全量。

最终冻结版完整回归：**4656 passed、0 failed、0 errors、2424 skipped**（957.12 秒）；前端 **196 文件、1980 tests passed**。Ruff/格式检查 1226 文件、mypy 775 源文件、Bandit、前端 format/lint/typecheck 均通过。2424 skip 不是成功验收，逐项依赖原因见归档 summary；本轮新增 SQL 只做了结构检查，未在 PG 执行，不能将已有 skip 数量当作新 SQL 原生覆盖。

证据目录：`/workspace/scratch/tender-prediction-pipeline-validation/`，分别保留首轮与最终日志/JUnit/summary、定向失败与复验、冻结摘要。提交补丁为 `/workspace/scratch/tender-prediction-pipeline.patch`，文件清单为证据目录 `files.txt`。

前端构建通过（保留已有大 chunk 提示）；最终流水线源摘要与测试时记录一致。没有 PR、合并、部署、真实模型或原生数据库操作。
