# 固定材料引用的有界自动调度

已复用现有历史 dispatcher、任务目录、游标、原生租约和幂等结果库，将固定 `/3` 训练/最终引用接入自动消费。必须显式提供私有计划和独立摘要；没有修改默认启动、创建任务、派发付费请求或授予正式资格。本次没有启动真实长期进程或执行新 SQL。

## 可用入口与持久闭环

- `deploy/package_history_worker.py --purpose feature-dispatch-method` 无凭据输出完整方法集合：complete、training、final、evaluation、dispatch。最后一项绑定本次实现、runtime 和可选绑定 SQL；漂移必须拒绝。
- 既有 `deploy/package_history_dispatcher.py --purpose train|evaluate --profile …` 增加成对参数 `--feature-plan … --expected-feature-plan-digest …`。仍默认一轮/最多 5 项，保留原有 batch/cycles/poll/停止信号边界；两个用途分别使用原独立非 owner 身份。此说明不是启动指令，本轮未运行真实派发进程。
- 计划是 owner-only 600 文件，版本 `package-history-feature-dispatch-plan/1`，严格字段 `version,purpose,jobs`，最多 64 项/256KiB。每项为 `job_id,cohort_id,membership_digest,reference_digest,candidate_digest,methods,references,material_store,artifact_dir`。后三项是既有私有文件/CAS/index 的绝对路径，不包含凭据或标签。训练 candidate_digest 为 null；最终侧固定到原训练候选摘要。完整 reference 格式继续复用既有原生 `/3` 训练/最终协议。
- 启动后使用固定计划字节；每个任务再次检查当前方法集合、reference 原字节摘要及研究组身份。计划和引用原字节写入既有私有 CAS，能按摘要保存/核对。它们只是请求配置，不能替代原生身份、来源有效性或材料复验。
- 首次 claim 后、材料消费前，以同一原生 lease 调用原 finish 入口保存 `feature_dispatch_bindings`。绑定不含本地路径或 generation，按 job 不可变；恢复可使用新代次/owner/fence，但不能换引用、方法或候选。路径搬迁需要明确的新计划摘要和相同原内容，不改变原生绑定。
- 训练仍调用既有完整材料复验及特征拟合消费者。原生发布检查 complete consumer 引用/方法与特征候选 source/method 全部匹配绑定；不能退回只写常数基线。
- 最终绑定必须关联本研究组已完成且已绑定的原训练任务，采用完全相同的方法集合和真实候选摘要。不能自动接管过去未绑定的手工结果。首次执行只冻结预测并返回 staged；后续轮次才以原预测进入既有曝光和独立评价。不会为了重试重新选择/拟合/校准。
- 原生发布还检查冻结预测的引用/方法/候选，以及最终评价的评价方法/冻结方法/候选。最终标签仍只能通过已提交曝光的独立读取取得。任何计划字段或本地布尔值都不能授权曝光或正式评分。

## 幂等、禁用及失败行为

原生绑定写入、预测冻结或最终结果丢 ACK 后，恢复读取同一 job 原记录；精确相同的绑定重复提交幂等，不同内容冲突。已完成且有匹配绑定的任务返回原结果摘要；已完成但从未绑定的任务拒绝被新计划“认领”。原生过期租约、generation 和 fence 仍由原有检查决定，不强占有效租约。

启用计划后，不在计划内的任务只 deferred，不回退执行基线或推断引用。旧引用/方法漂移拒绝，原生权限/连接故障保持原规则终止派发。缺失存储等配置故障不会补造结果。关闭计划保持旧 dispatcher `/1` 行为，但已绑定任务即使被旧进程领取也不能执行或发布，等待租约自然过期后由正确配置恢复；不得混配长期争抢同一用途队列的进程并据此声称全局公平性。

带计划的摘要回执使用 `package-history-dispatch-cycle/2`，增加 plan_digest、staged 计数；completed 表示核对成功结果，不一定是新增计算。游标推进和空页回绕不变，故一轮命令不保证完成“冻结→评价”两个阶段。日志仅含任务身份、代次、状态和摘要，不含原件、引用内容或私有路径。

## 原生安装及测试边界

新增 `deploy/sql/package-history-feature-dispatch.sql` 是 fresh-only 可选扩展：在 feature-evaluation 之后、exposure bridge 封存之前。既有 `package-history-dispatch.sql` 仍在 bridge 之后。只替换已有 claim/finish，校验原函数体并保留 OID/ACL；新表 append-only，无直接 grants，不改默认 BASE，不新建角色或凭据，不重封存已安装 guard。已安装部署迁移仍需独立编码/评审。

机制测试使用实际合成 `/3` 材料消费者和模拟原生通道，覆盖训练→冻结→评价、重复请求、丢 ACK、新代次恢复、有效租约拒绝、旧绑定/方法/引用漂移、未知任务、停止信号、默认禁用及启动隔离。原生 PG opt-in 覆盖 fresh/guard/权限、绑定幂等/冲突/代次，以及禁止基线绕过，但本环境未执行。没有模拟实际统计独立性或真实精度。

本轮范围限于任务绑定和恢复消费。私有计划/材料由明确操作者准备，UI 不会生成本地 CAS 引用；启动与配置是受控部署工作，未冒充上传后无人值守的整包评分。正式评分装配、已有部署迁移及复杂输出需求仍另列。

## 最终检查点

- 默认完整后端：4182 passed、0 failures、0 errors、2410 skipped，535.13 秒。跳过不计通过；新增 3 项原生 PG 测试未执行。
- 前端全量：187 文件、1895 passed；format、lint、typecheck、build 全部通过。build 保留既有大 chunk 提示。
- 后端 ruff check、format（1109 文件）、mypy（688 文件）、bandit 和 git diff --check 通过。
- 合成机制测试实际接通材料复验、拟合、预测冻结及评价消费者，原生连接/租约通道模拟；不代表真实 SQL 事务、并发或真实效果验收。未启动真实长期调度。
- Compose 沿用缺默认 .env 的已知环境阻塞，本轮未重跑；未新增凭据。PG17/S3、指定 Word03 和真实配对数据验收仍独立未完成。

本阶段基于 `6135d72de6fc87e68a1c7198b55ee406598eb131`；提交前核对远端当前分支仍为该 SHA，fusion 为 `462ec226013b011a40c204fe1c65541c4dbfbc25`。范围仅为任务绑定和恢复消费，不创建 PR、合并、部署或执行生产/付费调用。
