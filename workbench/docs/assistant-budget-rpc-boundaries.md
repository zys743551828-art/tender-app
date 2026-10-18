# 助手预算核清与发送身份守卫

本修订关闭归档预算 SQL02 的 AB01 NULL 核清漏洞及 AB02 预留与原生输出/模型身份脱钩。原候选、失败记录和 handoff 文件保留原字节；本修订不表示整份预算 SQL 或助手组合已经可部署。

## 核清契约

`assistant_reconcile_budget` 在修改 native 调用、预算或事件前显式拒绝 NULL decision/amount/proof_reference/proof_sha、空或全空白证明、短证明、非法决策、负金额、超过原预留以及非 billed 决策配非零金额。保留既有 billed 可为零的语义；不自动推断免费或未发送。

仅 sent/unknown 预算且真实执行为 failed/cancelled 才能核清；缺 job、scope、native 或 NULL state 均拒绝。核清成功写一次证明事件与精确金额；重复核清拒绝。失败必须保留原 unknown 占额、manual flag 和 native usage，不把 unknown 洗成 settled/0。

## 发送身份契约

`before_native_reserve` 原有 Python 校验继续保留。SQL 发送门新增独立核验：

1. job、intent、actor、scope/kind 身份吻合，预算仍 held 且未 dispatch。
2. 冻结 profile 完整等于价格版本和当前用途所确定的五字段对象：provider/model/port/purpose/formal_scoring_eligible，不接受缺字段或额外字段。只针对当前封闭 ASCII 模型/profile 枚举，使用与 `runtime.sha` 完全相同的排序紧凑 JSON 字节计算摘要。
3. 冻结 price ID、输入硬上界、输出上界、币种、按冻结单价向上取整的预留金额一致；价格仍有效。manifest 缺 max_tokens 时沿用原约定 2048；显式 NULL/字符串不接受。
4. global native call 的 profile/intent/max_tokens 及 run 的 input_digest/max_tokens 必须匹配。新建 call 在 usage.reservation 冻结当次真实 lease owner/fence，SQL 与当前 run 比较；租约移交或旧 call 缺证明均拒绝，禁止从当前 run 倒填旧 call。Worker INSERT usage 列权限在 assistant.sql 显式同步。原反例“预留 2048，run 与 call 合法一起设置 8192”在改变预算状态前拒绝。
5. project native call 必须属于真实 operation/bid，普通调用 attempt=1、非研究，不冒用其他 logical_call_key；输出上限和 usage.reservation 的 step/input_digest/generation/fence/owner 必须匹配原助手 job 推导的唯一步骤、真实计划及当前有效 receipt。操作和步骤 handler 也必须精确匹配 answer/authoring 用途。

任一身份或原生执行守卫失败，保持 held 和原金额，不产生 dispatched 事件。单次成功后重复 dispatch 拒绝。

## 验证范围

新测试通过显式 `FUSION_RECONCILIATION_TEST_DSN` 在限定名称的独立临时 PG17 库运行。只创建最小合成表与从源码提取的真实 RPC；所有 fixture 在事务中回滚，不执行完整归档 DDL，不使用业务数据库或供应商调用。

- `tests/test_assistant_budget_reconciliation.py`：两 scope 的四 NULL、空白/短/非法证明、金额决策组合、非终态/缺 native、重复核清，67 项实际检查。
- `tests/test_assistant_budget_dispatch.py`：正常 global/project answer/project authoring 的 Python 摘要一致与一次发送；模型/用途/价格/金额/max_tokens/原生步骤/attempt/租约污染，以及合法同时提高 global run/call 输出上限的原始 AB02 反例，55 项实际检查。两份测试合计 122 项通过，包含新 SQL 身份错误向 DomainError 409 的映射。

dispatch 测试对 `assistant_check_target` 使用明确 no-op，对 `assistant_budget_obligation` 使用 0 合成替身；因此本测试不证明五事实 live 来源资格、三层并发预算聚合或撤回窗口正确。也不证明真实角色 ACL、ASGI/Worker 到供应商的完整接线、真实费用/模型效果。

原交接中的来源确认 basis/祖先闭包、业务与预算锁序、native 写账与预算 settle 潜在反序仍未解决。预算 SQL 整体禁止部署的阻塞继续保留，不能以本片成功替代它们。
