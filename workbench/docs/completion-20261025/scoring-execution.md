# 完整材料评分：隔离执行、费用占用与原始回执

## 本阶段范围

在 `material_request_preflight` 的完整材料预检之后，本阶段接通一条可运行、可回读的垂直路径：原始完整材料 serializer → 独立原生执行账号 → 整单预算占用与单次发送事实 → 原 `/3` HTTP 客户端 → 原始响应、引用校验和费用估算持久化。全部纳入条款的三个独立槽位均有效后，原生账本释放未使用的剩余占用。

这条路径目前只接受 `synthetic_mechanism` 原生 job，且 Python 可运行入口严格要求显式 `httpx.MockTransport`。真正的生产入口 `execute_attempt` 在任何预留或发送前返回 `MATERIAL_EXECUTION_LIVE_QUALIFICATION_UNAVAILABLE`。测试供应商没有使用真实模型凭据，没有发生付费模型调用。新增能力不承接旧 `scoring_runtime` 的方法资格，也没有改写原 serializer、provider、预检或准备租约协议。

## 实际调用链

`execute_mechanism_attempt` 接收前一阶段恢复出的完整 `MaterialInput`、完整预检回执、一个规则/槽位引用，以及相互独立且空闲的 preparation/execution 两个连接。

1. 调用原 `preflight.prepare_rule_request`：重新核对当前准备租约、原 PDF、完整上下文和每份 PNG 的字节，然后重建与原预检相同的完整请求。
2. 调用原生 `material_execution.begin_attempt`：在当前治理、来源、档案和租约锁之下验证完整预检及全部规则；按当前 quote 一次性占用整单最坏预算；为指定槽位持久记录一次发送事实和 token。
3. 数据库事务成功提交后才调用原 `DeepSeekCompleteVisionClient.generate_async`，请求字节与原 serializer 完全一致。调用期间两个连接保持空闲；关闭自动重试、重定向和环境凭据发现的行为沿用原客户端。
4. 从响应的原始字节重新提取 usage，独立验证数字和响应身份；调用原 `/3` judgment checker 核验规则、档位、必要部分和引用。失败判断不抹去已报告的费用。
5. 调用原生 `material_execution.settle` 保存有界原始响应和不可变回执。原生端再将 usage 与原始 JSON 比较，使用冻结报价的整数费率重新计算费用；对于自报有效的判断，还独立核验响应正文、判断摘要、档位、全部必要部分、冻结 catalog 引用和区域边界。`read` 和 `response` 允许该独立执行账号重新打开自身回执和原始字节。

调用方可以把 `restore_and_preflight` 的两个返回值直接传入这一入口；不需要将 native JSON 伪装为材料对象，也不需要扩展准备账号读取原件的权限。

## 账本与幂等性

新增可选 SQL 安装文件 `deploy/sql/material-execution-attempts.sql`。执行账号只属于 `tender_material_execution_worker`，不获得表级读写或上游读用途权限。原生调用前仍审计精确 RPC、函数正文、owner、LOGIN/OID、角色成员关系和有效权限。SQL 不加入默认生产 bootstrap；owner 只负责隔离数据库初始化、合成钱包和短期不可变执行 profile 发布。

`accounts` 保存合成币种和额度；`balances` 保存占用和已估算费用。每个 job 的 `reservations` 是不可变整单预留事实，`job_balances` 保存当前占用、估算、释放额和状态。不会按一个可用规则或一个槽位缩减整单报价。

每次结算会显式累计该次预留超过实际估算费用的差额，最后再释放未使用的尝试容量。在没有费用超预留的情况下，`初始预留 = 剩余占用 + 已估算费用 + 已释放金额`。费用超预留时仍计入实际估算额并暂停，不将金额裁剪成报价上限。

每个原生槽位最多建立一条 `attempts` 记录。唯一约束覆盖 `slot_id`，因此换 command、换准备租约或重放相同请求都不能产生第二次发送授权。新的发送返回 `new_send=true`，回读返回 `false`；只有前者进入 HTTP 客户端。提交回执丢失时，原生事实仍是 `in_flight`，重放只观察旧事实。进程退出、取消或结算失败不会释放已占用费用，也不会触发补发。

一个 job 同时只允许一个未结算调用。当前阶段没有重试 API；报价中预留的多次尝试容量不会自动成为重试授权。结算本身按原始响应和提交回执幂等，同一调用收到矛盾结算会拒绝。持久原始响应使用 `bytea`、最多 1 MiB；正文、token、供应商消息及临时凭据不写日志或 Git。Python 包装对象关闭正文 `repr`。

## 费用与失效行为

| 结果 | 原生账本行为 | 后续发送 |
|---|---|---|
| 完整 usage，判断有效，来源仍当前 | 用整数微币单位计算估算费用，移除该次预留 | 可显式执行下一个未使用槽位 |
| 完整 usage，JSON/引用/必要部分判断失败 | 费用照常计入，状态 `paused_invalid` | 拒绝 |
| HTTP 错误、网络错误、截断或 usage 无法核验 | `unknown`，费用为 `null`，保留整单剩余占用 | 拒绝 |
| 已持久 grant 后取消、进程丢失或结算失败 | 保留 `in_flight` 与完整剩余占用 | 重放不补发 |
| 发送前租约过期、撤销、来源/报价失效 | 拒绝 grant，不创建新预留或外部请求 | 拒绝 |
| 发送后租约到期、被接管或撤销 | 仍记录真实收到的费用；判断不再计为有效，`paused_stale` | 拒绝 |
| 实际 usage 估算超过单次预留 | 按收到的 usage 记入未截断金额，`paused_overrun` | 拒绝 |
| 同一个供应商 response ID 被用于另一槽位 | 第二次费用仍计入，第二槽无效，`paused_invalid` | 拒绝 |
| 全部 3 × 纳入规则槽位有效 | `completed`，释放剩余未使用占用 | 不会重新打开已用槽位 |

费用使用 `ceil((input_tokens × input_rate + output_tokens × output_rate) / 1_000_000)`，不使用浮点，也不预设缓存折扣。原生端独立核算，拒绝将 `bool`、负数、不相等的 total、伪造 usage 或超出安全整数范围的金额作为已知费用。超预留不会被裁剪成报价上限。

原生回执验证不会把 caller 自报的 `valid_slot=true` 或任意摘要当作判断证明。外层响应及内层 JSON 判断均拒绝重复键；响应 fingerprint 和消息结构遵守原 codec。原始 `json` 数字词法会保留到整数校验完成，避免 `1.0` / `1e0` 被 PostgreSQL `jsonb` 归一化为整数后越过原严格 codec。未知费用同时保存可验证的请求 ID 和有界原始响应，支持后续有权对账追溯。

这里的金额是合成账户中的 `usage_price_estimate`；`invoice_reconciled=false`。未知费用的后续有权对账、发票校验和释放协议仍需实现；本阶段不会通过“失败退款”或新 nonce 绕过它。

## 资格边界与后续缺口

前一阶段回执中的 false 资格保持原样。新增协议使用明确的 `mechanism_fee_ledger_reserved` / `mechanism_send_once_granted` 字段，仅说明隔离机制事实。`execution_authorized`、真实账户价格、模型 token fit、实际图文可读性、原子快照、正式预测资格仍为 false。给 Python live 入口传入凭据或自称已验证的布尔值不能使它开启。

原生发送前检查与外部 HTTP 之间没有跨系统原子事务，因此仍保留 `atomic_snapshot_verified=false`；费用回执允许迟到，结果资格会重新检查当前来源和租约。结算在相同的治理、来源、档案和租约锁顺序下检查并写入，避免数据库内“检查时仍有效，撤销已提交后才写出有效判断”的竞争。已发送请求不能撤回，失效不会伪造零费用。

尚未完成的具体环节：真实账户价格/余额来源和账单对账、完整图文 token fit 证明与实际可读性资格、生产发送 admission、新 worker/Kafka/API 装配、失败后受控新尝试协议、正式三槽特征聚合及模型校准/预测结果。当前没有承诺这些条件已经成立。

## 验收证据

- 纯行为套件 `tests/test_material_execution_attempts.py`：31 项。与原预检、准备租约和完整材料 serializer 套件合跑，最终 **124 passed / 0 skipped / 0 failed，39.45 秒**。覆盖原完整 serializer 和实际 HTTP 客户端调用、成功及无效 JSON/引用的收费、HTTP/网络未知费用、取消/结算失败不补发、旧 grant 重放、真实入口拒绝及资格篡改。
- Ruff check / format、mypy、Bandit：最终新增执行模块及两个测试文件的适用检查全部通过。
- 原生执行 16 项与原预检 4 项在独立 PG 17 集群合跑：**20 passed / 0 skipped / 0 failed，587.79 秒**。最后对原始响应 ID 严格字符串类型，以及原 codec 接受的空 `tool_calls` 表示补齐一致性后，针对全规则成功路径和 16 种伪造回执反例再次验收：**2 passed，76.09 秒**。仅有已有 Starlette / AnyIO 弃用提示。
- 验收结束只读确认合成 `fusion_*` 测试数据库和 LOGIN 均已清理。全程使用真实非 owner PG 连接、原窄 RPC、原 5 秒语句时限和 120 秒以内准备租约；长任务通过原 heartbeat 续租。模型端仅显式合成适配器，付费调用数为 0。

原生开关为 `FUSION_MATERIAL_EXECUTION_PG=1`；旧预检组合同时设置 `FUSION_MATERIAL_REQUEST_PREFLIGHT_PG=1`。使用 `FUSION_REQUIREMENTS_ADMIN_DSN` 所指的专用测试集群，夹具会创建并删除固定 `fusion_package_requirements_api` 数据库和合成 LOGIN，不得与同一集群的其它固定库夹具并发。

原生通过的断言覆盖：事务提交后才进入 HTTP、全部纳入规则的各三个独立槽位具有相同请求字节且原始响应可重开、完整预算占用与释放守恒、并发 command 仅一次授权、未知费用保持占用、新 nonce 无法补发、租约撤销/接管或执行 profile 修订后的迟到费用、发送前过期、余额不足、无效输出照常收费、超预留金额、不重复使用响应、伪造 usage 和矛盾结算拒绝，以及独立角色/无表权限边界。另有 16 种直接提交伪造原始判断的原生反例，以及用表锁强制延迟结果写入、并行撤销 profile 的竞争测试。
