# 预算硬 Mock 链路状态与剩余验证

本记录承接 RPC 边界修复与 live 来源切片。当前独立 PG17 合成验证合计 **199 项通过**，覆盖真实来源资格、三 scope 聚合、锁序及恢复机制；尚未证明 helper05 完整 fresh 初始化后的真实非 owner API/Worker 链路、真实 Kafka 或供应商调用。所有收费消费者继续关闭。

## 已验证机制

- API proof 冻结原生 human decision basis、fact identity 和 source closure；SQL 内部 helper 对当前身份、事实头、决策审计、carryover、证据页、最新解析、当前资料角色与来源祖先逐项核验。缺 basis 的旧 proof 拒绝，不推算或补造。
- reserve/dispatch 在预算锁前取得目标 bid、执行 run/operation、graph/source 锁，并在写入前重新核验。五事实全部核验后，以同一次最终 clock 检查所有已锁来源头的时间资格，覆盖处理后续事实时第一事实过期。
- document/prebid 的来源资格沿用原生 authoring.assert_sources 及 confirmed_fact 契约；没有另造自由确认表或扩大 Worker 原事实权限。内部 SECURITY DEFINER helper 创建同事务撤销 PUBLIC EXECUTE，API/Worker 不直接调用。
- READ COMMITTED 是 reserve/dispatch 自身契约；general/project 在 RR 或 SERIALIZABLE 拒绝且没有预算副作用。
- 三 scope 的真实 reserve/obligation 聚合覆盖竞争受理、旧窗口 unknown 占额及 sticky manual flag；未知账单不默认零、不自动释放或补发。
- global call 初建冻结 reservation.owner/fence，SQL 与当前 run 比较；旧 call 不补造新租约。

协议、来源规范 JSON/时间表示及验证边界见 [live 协议](assistant-live-facts-protocol.md) 与 [live 验证记录](assistant-live-facts-checks.md)。

## 当前初始化依赖

fresh helper 的 BASE_SQL 顺序：

1. `packages/contracts/sql/core.sql`
2. `packages/contracts/sql/domain.sql`
3. `packages/contracts/sql/bid-packages.sql`
4. `packages/identity/sql/stable-lot-identity.sql`
5. `packages/contracts/sql/retrieval.sql`
6. `packages/contracts/sql/worker-functions.sql`
7. `packages/contracts/sql/roles.sql`
8. `deploy/sql/bid-package-runtime-grants.sql`
9. `deploy/sql/vector-runtime-grants.sql`
10. `deploy/sql/research-source-qualification.sql`

纯助手预算组合再按顺序加载 `packages/assistant/sql/assistant.sql`、`packages/assistant/sql/live-facts.sql`、`packages/assistant/sql/intent-budget.sql`。使用知识来源选择时在助手 SQL 前加入 `packages/knowledge/sql/rag.sql`；章节树/生成需要 `packages/authoring/sql/structure.sql`。不为本切片加载评分、模型治理或历史回测 SQL。PG17 必须具有 pgvector，不改字段类型绕过。

25 项 live 测试已执行完整 BASE_SQL 与上述三个助手 SQL，固定实际文件输入，未使用资格 no-op；这些测试目前使用 owner 连接执行，不能替代受限角色完整 fresh 验收。

## 原反例及闭合情况

原 proof 只有 fact/decision/evidence IDs、name/value；撤回 parse source 或原件祖先后，旧 SQL 读集不变。现已用真实原件、原生确认与等价沿用、完整 target/reserve/dispatch 重放证明撤回、到期、当前角色移除、最新解析变化、缺/坏 basis 或闭包均拒绝，held 预算与 dispatch 事件保持原状。

约定锁偏序为：目标 bid → operation/receipt 或 global run → graph 90127 与来源头 → 预算 90129 → 预算/native call 写行。同级对象按既有顺序取得，不在持预算锁后补取前级锁。当前 global 目标资格从不可变 job 推导 target bid；本结论不外推为任意跨项目上下文完整原子闭包。

| 实际入口 | 原反序 | 当前修复与验证 |
| --- | --- | --- |
| global reserve | 预算→run，发送 run→预算 | 目标 bid→run→来源→预算；旧 call 重放不新增调用 |
| global/native 成功或失败保存 | native 行→预算，与 observe 的预算→native 行成环 | native 写账先提交再 settle；有界竞争通过 |
| queue_generation | 预算→graph，与合法 graph→预算成环 | prepare 前取得 bid/graph；有界竞争通过 |

三类旧反序均已有真实双连接死锁反例及修后有界完成验证。native 提交与 settle 之间的崩溃窗口由 terminal_tick 调用实际 settle 回收：not_sent 且终态才释放，usage_reported 按冻结价格结算，unknown 全额保持等待可信 reconcile。不会把等待核清责任误解为必须清零。

## 测试层次与剩余边界

合计 199 项：25 项完整 schema live、14 项 identity/2 target、16 项三 scope/隔离级别、67 项 reconcile、55 项 dispatch、8 项预算锁/恢复、3 项 generation 锁、11 项原助手。部分叶测试显式隔离非目标资格依赖，不能单独宣称完整链路；25 项 live 使用真实资格。

剩余下一切片是 helper05 完整 fresh 的受限 LOGIN 组合：独立预算管理身份配置、API 受理、Worker 原生执行、结果发布与重放，并以显式离线 MockTransport 证明没有真实费用。须实际验证 Worker INSERT usage、内部 helper 权限与管理 DSN 隔离，不由 owner 补权掩盖。

尚未验证真实 Kafka 传输/消费者、真实供应商、生产部署及浏览器视觉验收。这些边界不影响已通过机制的结论，也不授生产收费资格。
