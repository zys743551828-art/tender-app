# /3 内部路由与受控回退动作

## 实际闭环

`deploy/package_model_route.py` 是显式内部 CLI，复用安全私有请求读取、已有 API-role 连接注入和上阶段 `LocalExecutor`。不启动常驻调度、不配置凭据、不调用 provider，也不挂到正式业务路由。请求不能提交 verified、数值、回退结果，消费/回退命令不能临时指定模型或改配置。

`package-internal-route-command/1` 使用 UUID command/route、显式 expected_revision 与方法摘要。首次 activate 固定候选、不同的明确回退模型、两者 artifact 摘要、历史材料 admission、完整 /3 引用与观察方法；必须实际消费候选后才创建路由。consume 总是从权威路由选择当前模型。rollback 从既定配置选择回退目标，复验其原生来源和原件并实际推断，提交时重新读取路由/来源、校验版本与完整准备包摘要，原子写入观察事件、切换内部路由、写入不可变动作事件。旧候选、选择结果和消费摘要都可追溯。

回退后 consume 只选择回退模型；本协议不允许重新激活已有 route 或再次回退，也没有客户端指定目标的入口。回退目标失效/撤销时拒绝切换和后续消费；旧候选失效时允许回退到仍有效的固定目标，不要求旧候选继续具备新消费资格。新命令的过期版本、材料/模型/方法漂移和执行中撤销不会留下部分成功事件。历史同一命令丢 ACK 可恢复原回执，但回执明确不是当前资格。

## 权威和事务边界

应用用例依赖事务端口与执行器，CPU/文件读取在两个短事务之间。可选新库 SQL `package-model-route.sql` 安装于 observation SQL 后、首次观察前；不修改旧 release 或 observation 源码，不重封存旧方法。新方法绑定应用源码、SQL 和既有观察方法。复用旧 release 的固定回退目标、revision CAS、候选/当前/回退关联 bid 并集先加锁的语义；SQL 只写独立 `package_model_route` 状态/事件和既有内部观察事件，绝不写 `design.model_routes`、`model_release.routes` 或 certifications。

沿用既有活跃成员/创建者与非 owner API-role 权威，不新增角色或账号；API-role 是受控执行信任边界，SQL 不独立重算 Python。不可变动作事件引用真正执行产生的观察事件，且校验 result/source 摘要，不能把一条客户端验收标志变成成功证据。所有路由修订（包括消费）产生有序事件，竞争动作必须以新的 revision 重新开始；同一 command 只恢复一次提交。

回执仅展示选择身份、revision、动作、摘要、历史回执状态，明确 `business_route_changed=false/formal_eligibility=unavailable/certification_issued=false`，不展示候选数值给业务用户。

## 验证及真实边界

合成测试使用真实私有 /3 CAS 和实际岭模型计算，经模拟 native channel 切换内部路由，断言回退前后的模型选择和数值不同、回退后持续选择回退目标、旧目标覆盖/再激活/再次回退被拒绝。还覆盖重复/丢 ACK、两个用例交错提交的版本冲突与去重、撤销、源漂移、篡改结果、CPU 异常/取消、跨成员、闭合版本和 CLI 脱敏。SQL 源码约束检查覆盖锁顺序、提交复验、事件原子写入顺序和业务路由隔离。

**这不是原生 PG 并发验收或真实在线影子/生产回退演练。** 本环境缺隔离 PG17，新增 SQL 未执行；模拟权威不能证明数据库角色/锁/回滚真实正确。也没有真实模型认证、部署、付费调用。内部 retrospective 动作不能被下一认证阶段静默解释为真实线上回退验收。

剩余有限代码：认证生命周期及明确证据资格消费、正式预测持久化/API/UI。真实用途的影子/回退记录是否满足认证条件必须遵循已批准协议和权威来源，本阶段不填写阈值、不批准任何模型。

后续认证应直接引用本阶段 `package_model_route.events.command_id` 及其 `observation_id`，由受控 SQL 读取原始动作/来源/结果绑定并复验，不能接受客户端复制的回执或另建 verified 证明。事件的 retrospective 模式、材料 origin、固定模型及输入身份仍是资格判断条件，事件存在本身不授予真实用途资格。

最终后端全量：4518 passed、2424 skipped、0 failures/errors（673.49 秒）；初轮路由 19 passed，相关观察＋路由 47 passed，新增两个交错用例已纳入全量。前端 192 文件/1944 tests 通过；Ruff/format（1179 文件）、mypy（735 源文件）、Bandit 及前端 format/lint/typecheck 通过。初始测试夹具命名 Lint 问题已修复，无测试失败。既有观察源码/SQL、execution/dispatch/qualification/jobs 冻结方法摘要未变。

前端 build 通过，保留既有 chunk-size 提示；无 HTTP/UI 契约变更。补丁 `/workspace/scratch/tender-package-route.patch`，日志/完整跳过原因/文件清单位于 `/workspace/scratch/tender-package-route-validation/`。新增原生 SQL 仍未执行，不能以 2424 项历史 skip 或模拟测试替代它的数据库验收。

当前全新原生安装改用`package-model-route-v2.sql`，修复两处CASE解析歧义，显式native SQL版本/2纳入方法摘要；旧/1文件字节保留。本记录原先的机制通过不能作为原/1SQL安装通过证据。
