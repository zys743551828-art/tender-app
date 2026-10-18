# 预算硬 Mock 链路剩余阻塞与验证设计

本记录承接 RPC 边界修复；不修改冻结交接，不批准执行完整预算初始化。叶 RPC 的 122 项 PG 检查不能替代这里的原生 API/Worker、来源、并发与恢复验证。

## 初始化依赖

纯助手与知识来源选择的最小候选 SQL 顺序：

1. `packages/contracts/sql/core.sql`
2. `packages/contracts/sql/domain.sql`
3. `packages/contracts/sql/retrieval.sql`
4. `packages/contracts/sql/worker-functions.sql`
5. `packages/contracts/sql/roles.sql`
6. `deploy/sql/vector-runtime-grants.sql`
7. `deploy/sql/research-source-qualification.sql`
8. `packages/knowledge/sql/rag.sql`
9. `packages/assistant/sql/assistant.sql`
10. `packages/assistant/sql/intent-budget.sql`

前七项来自 fresh helper 的 BASE_SQL，后续知识/助手原件存在组合02的历史审查记录；这不授当前新组合资格。章节树/计划/双模板生成加入 `packages/authoring/sql/structure.sql`；测试覆盖上传闭合时再加入 lifecycle/batch_closures。无需为纯助手初始化评分、分母、模型治理、历史回测或回溯 SQL。PG17 必须具有 pgvector；缺扩展时停止该候选，不改字段类型绕过。

`intent-budget.sql` 的核清和发送身份已有叶 RPC 实测，五事实 live 来源、预算/业务锁顺序及完整组合仍未审。完整初始化前应固定每个输入 SHA、核验依赖对象、明确受限 LOGIN 与管理 DSN，先新空库而非修补既有业务库。

## 五事实资格反例

当前 `intent_identity.project_identity` 在 API 路径调用 `knowledge.bridge.confirmed_fact`，会核不可变 decision basis、fact identity、当前 evidence_basis 和 carryover。但保存到 intent proof 的只有 fact ID/name/value/decision/evidence IDs，没有完整 basis 与来源闭包。

SQL `assistant_check_target` 仅查询 identity.bound、profile/round、fact_heads、fact_items、decision_heads/decisions及目标对象；没有读取 retrieval.source_heads/source_ancestors、证据页、最新解析或 human.decision_recorded 的 basis。因此最小反例是：

1. 用一个真实原件解析及原页证据，确认五 typed facts，绑定工程/轮次/投标人，保存目标 proof。
2. 首次 `assistant_check_target` 成功。
3. 只撤回其中一个 parse source 或它的原件祖先，保持五 fact IDs、values、heads、decision IDs、evidence IDs 不变。
4. 相同 RPC 读集仍完全一样，无法拒绝该变化；原 Python `confirmed_fact` 应拒绝。这是精确的读集反模型，尚未执行完整 schema 的该反例。

最小修复设计：API 受理先持实际 bid 锁及 graph/source 锁，冻结原生确认 basis、fact identity、完整证据/祖先 authority manifest；Worker 不补业务读权，由受限 SECURITY DEFINER helper 对同一 bid/current fact set/decision audit/carryover/证据角色/当前解析及 live 来源闭包逐项核验。发送前短事务再次核验且锁至 dispatch 提交。不能只把 API 签名或一份历史 true 布尔值当 live 权威；也不能新造自由填写五编号表。

跨项目 global 对话须从不可变 job 推导完整关联 bid 集合并排序，不能只锁当前界面项目。canonical JSON/hash 必须复用现有 Python 字节约定，缺 basis 的既有 WIP intent 保守暂停而非反推伪造。

## 已定位锁反序与修复顺序

约定偏序：已知关联 bids（排序）→项目 operation/receipt 或 global run 执行锁→graph 90127 与来源头（排序）→预算 90129→预算/native call 写行。同级并发仍需实际证明；不可在持预算锁后补取 bid/graph/run 锁。

| 实际入口 | 修前反序 | 最小修复 |
| --- | --- | --- |
| global_runtime.reserve | before_native_reserve 取90129，再 locked_execution(run)；发送路径先run再90129 | reserve 先锁run、核来源，再取预算锁；原调用重放仍复用原 call |
| global_runtime.failure / 成功保存 | native call UPDATE后同事务 settle取90129；observe RPC先90129后UPDATE同call | native写账先提交；独立事务settle。保留 usage，异常不补发 |
| paid_execution成功保存 | 同上 | 同上；初次native预留前先核来源，保持执行→graph→预算 |
| queue_generation / budget.prepare | 已锁bid后 budget.prepare先90129，resolve/confirmed_fact可能再取90127 | queue_generation 在 prepare前调用 context.lock_scope(c,[bid])，先完成当前入口实际bid/graph锁，不在SQL持预算后补取graph。该入口freeze_generation_plan当前仅接受本bid资料 |

queue_answer 已在 budget.prepare 前调用 context.lock_scope，不能笼统声称全部 API 都倒序；global reserve 与 native写账的上述两个具体反例成立。

## 有界真实并发与崩溃恢复验收

- 两真实连接分别取 run 行/90129，再反向请求，修前应得到 PG deadlock/有界 lock timeout；修后以相同重放实际调用 reserve，两个线程在固定超时内完成，没有新增 call、没有 provider I/O，unknown不释放。
- 两真实连接分别取 native call 写锁/90129，再反向请求，修前复现环；修后 actual failure 的 native事务提交后再settle，与 observe 并发完成，不改变原unknown责任。
- 在 native提交与settle之间模拟进程消失：已有 sent/unknown 预留继续全额占用；coordinator.tick→budget.terminal_tick 在后续短事务运行实际 settle RPC。not_sent且确已终态才释放；完整 usage按原价格结算；unknown保持原预留，不能默认0。
- native调用仍 reserved且账不明时不能自动重发或释放；terminal_tick未能核清应明确等待可信reconcile，而不是将“无永久held”误解为必须清零。
- 三scope限额：用两个成员、两个真实对象并行受理，预留总额恰好达限仅允许所能容纳的请求；取消/旧窗口unknown仍占额；冲突迟到usage恢复sticky manual flag。使用实际 reserve/obligation，不用0替身。API hardMock发送计数应等于获准dispatch数，拒绝路径0次。

已执行 `tests/test_assistant_budget_lock_order.py` 的 8 项真实 PG 检查：旧 run/预算、native行/预算两个环各触发一次 DeadlockDetected；修后实际 global reserve 重放及 failure 与并发写账有界完成，原 unknown 2148 保留且原 call 不增；新 call 冻结真实 owner/fence；实际 terminal_tick→settle 覆盖 not_sent/usage_reported/unknown 三种崩溃窗口。此测试使用独立 `fusion_budget_lock` 最小合成 schema，显式建就绪用 reserve 替身，仅调用实际 reserve Python 和 settle SQL，不代表三scope受理或整个 Worker 完成。加既有助手 11 项与叶 RPC 122 项合计 141 项通过。

测试夹具中每个独立问题使用不同 intent digest。曾复用同一 digest 的 fresh-call 用例被真实 unresolved 守卫正确拒绝；只修正夹具身份，没有放宽生产守卫。

编制入口补充 `tests/test_assistant_generation_lock_order.py` 三项真实 PG 检查通过：旧 graph/预算逆序实际 DeadlockDetected；实际 queue_generation 到 budget.prepare 前已持 graph锁，与合法 graph→预算竞争有界完成并复用原job；closed项目仍在预算受理前拒绝。这里对 require_schema 及 reuse-only prepare/view 使用显式测试替身，不执行完整新job受理、模型、五事实资格或三scope聚合。与8项锁/恢复及11项原助手合计22项通过。

## 仍保留的边界

global dispatch 已补 call 初建时的 reservation owner/fence 冻结，不变 RPC 两参签名，SQL 与当前 run 比较，不给旧 call 补造租约。普通Python locked_execution 的原守卫继续保留。项目分支保持既有 reservation fence/owner 校验。此边界的实际 RPC 用例覆盖移交后旧 call 和缺/错误类型的 lease 证明；完整受限 Worker INSERT usage 权限仍须全schema角色链验证。

上述来源/跨项目资格与三scope并发未通过前，只允许独立合成反例和受控硬Mock开发验证，不授完整预算生产或真实模型费用资格。
