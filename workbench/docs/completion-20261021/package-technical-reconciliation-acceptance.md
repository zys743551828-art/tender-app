# F06 未知发送状态的独立回执对账

日期：2026-10-21。本增量接在 `package-technical-execution-acceptance.md` 之后；不改已冻结的范围、资格、正式执行 API、前端协议或专用 Worker。它补齐了此前明确列出的“unknown 取得有据响应后如何安全结算并恢复”软件路径。

## 已完成的实际路径

在新的 PostgreSQL 17.11 临时库中，实际独立对账 LOGIN 和 `-I` 子进程已执行以下路径：原调用预留 → 发送／费用未知，任务暂停且预留保留 → owner 在测试库登记精确绑定原调用的合成 provider 回执 → 独立对账进程核验并结算 → 原 unknown 行完整追加存档 → 显式恢复原 job → Worker 只发送尚未发生的另外五次模拟 HTTP 请求 → 两条款各取得三次有效独立判断。

对账本身的 provider 请求数和付费均为零。已迟到确认的原调用仍只有一个 call ID 和原 replicate；它没有变成新独立判断，也没有重复发送。结算仍使用原冻结的价格快照及原保守预留，恢复 job 的预算和 generation 继续由既有账本控制。

所有 provider 回执、原文、评分规则、使用量和价格均为显式合成。没有配置真实 provider 回执验证器，没有真实效果验收、正式分数、训练资格或历史样本资格。

## 权威与权限

新扩展 `deploy/sql/package-score-reconciliation.sql` 仅安装于新的独立临时机制库，并且位于 `package-score-execution.sql` 之后。原执行基础及其依赖顺序不变；本扩展不进入 BASE，不开放 HTTP 入口，不安装默认业务账号。

新增 NOLOGIN 组 `tender_package_score_test_reconciler`。实际 LOGIN 必须只具备这一用途，不能同时属于 API、普通 Worker、研究 Worker、旧评分、整包测试 API 或整包 Worker 组；不能读取 design 原表，不能具备 superuser、bypass RLS、创建数据库／角色或复制权限。SQL 和 Python 运行连接各自检查一次。数据库的物理名称、OID 仍须在 owner-only 的机制环境表中准确登记。

`reconciliation_receipts` 为 owner-only、不可变的合成 provider 回执登记。它绑定数据库 OID、call ID、原调用整个快照的摘要、原请求／方法摘要、provider／模型、provider receipt ID、原始 provider 记录及其字节摘要、完整迟到响应及字节摘要、观察／登记／失效时间。资格最长八小时。普通 API、两类 Worker 和对账账号都不能读取或写入此表；它不是上传 JSON 或勾选“已确认”即可获得的权限。

对账 RPC `package_score_execution.reconcile_call(receipt_id, command_key, reason)` 只接受已登记回执的 ID、幂等键与理由。它不接受模型响应、账目数值、状态覆盖、正式／训练资格字段或新的模型调用参数。真实 provider 回执验证器未来需要独立可信验证和专门的生产资格，不能把此合成登记表直接改成生产授权。

## 账目、审计与恢复行为

| 情况 | 实际处理 |
| --- | --- |
| unknown + 确切迟到成功响应 | 独立核验原调用及回执，按原 usage／价格结算，释放原预留，追加原状态与完整结算后状态；任务保持暂停并递增 generation |
| unknown + 有据未发送回执 | 释放原预留，费用为零，保存原未知状态；任务保持暂停，不授权再次发送 |
| reserved + lease 仍有效 | 拒绝对账，避免介入仍持有执行权的 Worker |
| reserved + lease 已过期 | 可用确切已登记回执结算；清除旧 owner／lease，递增 generation，等待显式恢复 |
| 来源已经撤回 | 已发生费用仍可如实结算；不得恢复生成结果，原 source gate 继续生效 |
| 同一命令重复执行 | 同一 principal、回执和理由返回原成功回执，不再次结算或写审计；来源随后变化也不改写旧成功结果 |
| 同键换参数，或换键重复对同一 call 对账 | 拒绝；不能二次释放预留、覆盖原回执或改变原费用 |
| 错 call 摘要／请求／方法／模型／usage／超原预留 | 原子拒绝，原未知状态、预留、费用、generation 都保持不变 |
| 对账审计写入失败 | 整笔事务回滚；账目和回执不能出现一边成功、一边失败 |

`reconciliations` 是不可变追加记录，保存 `previous_call`、`settled_call`、provider 回执摘要、命令摘要、服务 principal、理由及原结果。服务审计使用明确的 service principal，未冒用发起成员身份。核心调用表仍使用原结算协议；原 unknown → 临时 reserved → 最终结算的转换只发生在同一事务中，外部看不到中间状态，任何失败都会整体回滚。

当前范围仍不允许根据 not_sent、无效但已计费的回答或普通人工确认直接新建重试。安全的“新增 attempt”需要保留原 attempt、独立授权、预算重算和最多三个有效独立判断的专门协议；本增量没有通过删除原调用、重置 replicate 或更换 nonce 绕过这一要求。

## 运行入口

独立入口为 `deploy/package_scoring_reconcile.py`，参数为 `--profile`、`--receipt-id`、`--command-key` 和 `--reason`。profile 为权限 0600 的普通文件，只包含 `PACKAGE_SCORE_RECONCILIATION_DSN`。它不能携带 API、存储桶、模型凭据或其他环境变量；文件符号链接、宽权限、重复键、其他用途 DSN 和含糊值都会在连接前拒绝。

父进程只运行固定解释器和固定本文件，参数不经过 shell；子进程以 `-I` 启动、使用用途专属环境。`packages/model_governance/package_scoring_recovery.py` 只调用固定对账 RPC，无 provider 客户端、原件读取器或普通 API 连接。标准输出仅包含安全的结果摘要或错误码，不输出口令和原始模型／证据内容。

SQL 成功后仍须通过已有 `change_job(..., 'resume', ...)` 明确恢复，并使用返回的最新 generation 启动原 `package_scoring_worker.py`。此前未知调用的成功响应会被读取复用；只有尚无调用记录的其他 replicate 会申请新预留并发送。

## 验证与可复现范围

| 检查 | 结果 |
| --- | --- |
| `tests/test_package_scoring_recovery_pg.py` | 17 passed，58.82 秒；独立真实 LOGIN、真实对账子进程和原 Worker 恢复正向 |
| `tests/test_package_scoring_recovery.py` | 9 passed，0.05 秒；用途 profile 的权限、符号链接、重复／额外变量和含糊值拒绝 |
| Ruff + format | 4 个新增 Python 源／测试文件通过 |
| mypy | 两个新增源文件，`--follow-imports=silent` 通过 |
| Bandit | 两个新增源文件通过；仅固定子进程 import／固定调用作具名说明 |

原生反例包括：live lease、过期凭证、错原调用摘要、错原请求、错方法、错模型、总 usage 不一致、负 usage、超出原预留、跨用途账号、混合权限账号、来源撤回及强制审计失败。没有外部 provider 连接；五次发送仅是恢复时尚未发生的 MockTransport 调用。正式／训练／指标字段仍全部 false，数值预测为 null。

测试要求 `FUSION_PACKAGE_SCORE_RECOVERY_PG=1`，并由 `FUSION_REQUIREMENTS_ADMIN_DSN` 指向新的独立临时 PG17 集群。测试库和专用账号在 fixture 中创建、清理；owner 只初始化和登记合成回执。不要将测试指向业务库。每套 PG suite 使用各自新集群，避免复用权限未知的角色。

原测试回执：`/tmp/tender-review-f06/reconciliation-pg-a81qhnmw/test-receipt.json`。SQL 的验收 SHA256：`62eb152aa95cd8019e585290bab586cde32be1868566e7ebc9f80932de21222b`。可持久核对的结果与源文件指纹见 `package-technical-reconciliation-checks.json`。唯一第三方告警为 Starlette／AnyIO 弃用提示。

本增量解决了有据迟到响应的账目恢复和安全续跑。完整图文／必要范围权威、真实 provider 与方法资格、官方聚合、严格整包历史时间证明及正式样本准入仍按执行验收文档明确保留，不由机制对账授予。
