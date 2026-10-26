# 认证消费前的来源缺口复核

本检查点只核查现有权威，不实现虚假的正向签发分支。最新代码 78ce2b1。

## 已有记录不能被改名为真实线上验收

- `packages/package_model_observation/execution.py` 生成的事件 mode 固定为 `retrospective_internal`。
- `deploy/sql/package-model-observation.sql` 的 `record` 明确拒绝其他 mode。其 `source` 来自历史 admission/proof，包含已提交材料与历史标签排除身份，不是线上预投标输入来源。
- `deploy/sql/package-model-route.sql` 引用上述观察事件，仅切换独立内部路由；回执明确 `business_route_changed=false`。回退动作机制已实现，但未生产真实线上验收证据。
- `score-business-admission-protocol/2` 当前封闭字段是 artifact_family/binding/baseline/thresholds；没有线上影子/回退 producer 版本与证据类型绑定。不能偷偷给冻结 /2 加字段或更新已曝光门槛。
- `packages/model_governance/RELEASE-DEVELOPMENT.md` 要求真实用途来源、报告、观察和回退验收，并明确候选推断/对象可读不等于正式资格。

现有证据可直接作为受控机制记录消费，但不得通过客户端 verified、人工复制回执或新增假定的 online 标志获得真实资格。仅在模拟 channel 构造不存在的 online packet，不能证明原生签发正向闭环已接通。

## 有限必需代码顺序的修正

此前将剩余概括为“认证生命周期、正式预测”遗漏了一个尚未实现的代码依赖，需要更正：

1. 在既有 /3 权威及事件链上实现真实用途的线上影子输入/执行与回退验收 producer 版本。原件/输入身份与用途必须来自受控原生来源，沿用现有角色、执行/事件机制；测试只用隔离合成输入，不实际运行真实影子。冻结协议需显式版本化绑定这些来源，旧 /2 继续只读且不事后升级。不是另建平行 verified 证明系统。
2. 认证生命周期直接读取这些事件和已有原生报告，提供签发/读取/有效期/终态撤销/恢复；当前 retrospective 事件明确不能满足真实线上验收要求。
3. 正式预测消费与持久化/API/UI，在执行关键边界再次复验认证与输入。

这是已授权目标内的**缺失代码依赖**，不是要求用户重批协议方向、填写默认阈值或提供真实数据，也不是权限拒绝。原生 PG17 未就绪及真实效果缺数据，仍是另外的环境/数据验收项。

## 本检查点状态

仅只读核对工作区、远端和源文件并修正文档；未编写认证接口、未签发认证、未改生产路由。没有运行测试或把上一阶段 4518/1944 通过结果算成本轮认证验收。没有自动审核拒绝、待授权操作或结果不确定的外部写入。
