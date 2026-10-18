# 预算 helper05 / 非 owner 原生硬 Mock 验证

2026-10-18，首切片 `fa31462` 的 `tests/test_assistant_budget_nonowner.py` 在独立 Linux **Python 3.12.15 / PG17.11 + pgvector** 上 **5 passed in 16.71s**，主代理独立复跑 **5 passed in 16.79s**。没有生产代码修改、owner 补权、真实供应商请求或费用。后续 F08-02 增量的 25 项验证独立记录于文末，不改写首切片证据。

## 环境与初始化

- 检查镜像：`sha256:f21edf5853b0c337de05a4b6af7ee16787b5520d8e4101b34fea6ee2a70b25be`，62 个锁定依赖已由独立代理离线检查；本测试使用实际安装结果。
- 临时 PG 镜像：`sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d`。新容器 `tender-fusion-nonowner-pg`，内存上限 1 GiB，数据库仅 tmpfs，无宿主端口。
- 网络 `tender-fusion-nonowner-qa` 使用 Docker `--internal`，只包含检查容器与临时 PG；数据库别名 `fusion-nonowner-postgres`。没有 Docker socket、业务 env、业务服务或外网出口。
- 只读挂载允许的源码目录（packages、deploy、tests、apps/api、apps/worker），复制至容器私有 tmpfs。umask 077，`.local` 0700，profile 0600；直接执行真实 fresh helper，不跳过 POSIX 权限要求。
- 在此全新 cluster 一次创建五个基础 NOLOGIN 能力组及预算管理组。测试前后检查组能力不变，不复用其他 fixture 的全局 LOGIN。helper 创建随机 nonce 的全新库及五个随机 LOGIN，逐个实际登录验证。

实际 SQL 顺序为 BASE_SQL 的十项，再依次 `assistant.sql` → `live-facts.sql` → `intent-budget.sql`。每一项由 helper 在任何数据库变更前冻结实际字节与 SHA。没有 rag/structure/评分/模型治理扩展，也没有资格替身。

| SQL | SHA256（实际 LF 字节） |
| --- | --- |
| contracts/core.sql | `27f249ff5110c914404846d2e14f6d4fd8b85ae51e9f6a3b9caa7c1b9595e5cd` |
| contracts/domain.sql | `b279c9b1c3477feeb28eaa5f6a45adb4493585a1d112d7d7a637cefac1404d96` |
| contracts/bid-packages.sql | `f18cbd9a22cdcb3f1d3229d0e43b3ad4b0ff3568f4b160787e0c4572b6f9c319` |
| identity/stable-lot-identity.sql | `3d4775a72daa3fd1c813aab72212e9aefdf5e5ef5aa22eb0c83db2cd580b3738` |
| contracts/retrieval.sql | `afdfb3d81bc049cedaa45777af3c8aa622b8c3eb465cd6b35e3a37c992991876` |
| contracts/worker-functions.sql | `8f18a20578c010144ed851d0e96753894c86a4147deff95c49aa19ec5faaea4b` |
| contracts/roles.sql | `b1b77fc0d65a95da41b8071475c28d8918f958e3cc479b65ce099e0563fb7ec1` |
| deploy/bid-package-runtime-grants.sql | `1667815c514a455b29230753202876c125ce10e34a0c408b4d50f49f118bd14e` |
| deploy/vector-runtime-grants.sql | `c66ce4615b007706ad690166233aad58053ff38b53eab5f7549583fc7c400619` |
| deploy/research-source-qualification.sql | `0b04ba8dd0ae471d06c45b4c6d36b8570211d248fd60410e15362a2b373ba027` |
| assistant/assistant.sql | `4030b5e6a749aa060956c4039aa0cdd34e057508ea6a4ce9c58100f5a6ca81b0` |
| assistant/live-facts.sql | `42fc9646225a67a8d209822ac9d0e3573e6903b3f5681042e9cb49fa6eeb11a2` |
| assistant/intent-budget.sql | `173078b95a5cd58db9f8f8aa09ff2728bae2c4a1e1b3817a4b593e719b04a6b0` |

相对路径中 contracts、identity、assistant 均位于 `packages/<目录>/sql/`，deploy 位于 `deploy/sql/`。这些指纹对应 [SQL 字节记录](fusion-sql-input-bytes.json) 的 Git/LF 候选；先前 Windows 原始 CRLF 的 199 项验证收据仍保留原指纹，不改写为同一输入。

## 五项实际验收

1. **helper / 权限**：五个非 owner LOGIN 实际连接验证通过；API/Worker 业务子进程各仅收到一个 DSN，既没有 owner，也没有预算管理 DSN。两者不能写价格或限额，也不能直接调用两个内部 live helper。预算管理由独立正向 allowlist 子进程执行真实 CLI，使用单独 0600 profile，写入留存 SHA 的显式合成价格及三 scope 限额。
2. **项目链**：API 身份创建身份/原件记录，Worker 身份创建合成解析页/证据并发布真实 source graph，API 使用原生 fact_sets 确认五事实和 human basis/carryover。真实 ASGI 受理 → 普通 Worker 已注册的 `assistant/1` 原生 acquire/compute/finish → API coordinator 发布 → 历史两条消息。native call 与 dispatch 各一条，冻结 usage 12+20 按合成价格实际结算 32 minor；同任务重放零新增模型请求。
3. **全局链**：真实全局会话 API → global_runtime.handle → API coordinator 发布和历史读回；同样一次 native call/dispatch、结算 32 minor、重复执行与 HTTP 幂等重放不增调用。该例为 general target；项目目标的五事实资格由上一例及 25 项完整来源测试覆盖。
4. **撤回**：项目受理后，用真实 Worker 撤回原件祖先；原生执行没有 native call 或 dispatch，也没有 Mock HTTP。初始 held 2099200 保留，实际非 owner `coordinator.tick([job])` → terminal_tick → settle 将已终态且未发送任务释放为 0；仍无 dispatch/native call。
5. **未知**：全局调用显式 Mock ReadTimeout 一次，状态 unknown，原 held 2099200 保留。重复 Worker 执行零新增请求；实际 API coordinator.tick 后仍 unknown/原额；相同 HTTP 请求复用原 job。

模型端口只替换 `DeepSeekClient.from_env` 为明确构造的客户端，其实际 generate/解析/usage 入账走 `httpx.MockTransport`；API 的传输器遇 HTTP 立即失败。未替换 budget/target/live helper、Worker handler registry、compute、finish、coordinator 或 SQL。对象存储是显式进程内字节适配器；测试原件页/解析数据为合成机制输入，没有宣称实际 PDF 解析质量。

## 证据、清理与复跑

本地原始 XML 和无凭据 JSONL：`.local/nonowner-evidence/nonowner.xml`、`nonowner-receipt.jsonl`；源 allowlist SHA 清单 `.local/nonowner-source-sha.json`。记录包含 SQL 输入、真实调用/事件/账本计数及清理结果，不包含 DSN、口令或业务原文。helper 临时库、五个 LOGIN、所有私有 profile 均在 finally 清理；独立查询确认 nonce 库与 LOGIN 均为 0，能力组不变。

可在同隔离条件下设置 `FUSION_NONOWNER_OWNER_DSN`（专用内部 PG17 的 postgres 库、显式合成 URI）运行 `python -X utf8 -m pytest tests/test_assistant_budget_nonowner.py -q -x -p no:cacheprovider`；可选 `FUSION_NONOWNER_RECEIPT` 保存安全 JSONL。测试刻意要求 Python3.12/POSIX 和固定专用 PG 别名/端口，拒绝业务端点，不能把环境变量指向已有业务库。

ruff/format、mypy（Linux 目标）通过。Bandit 对本测试除 assert 与固定 argv subprocess 的预期 B101/B404/B603 外无发现；没有生产代码新增需扫描。Windows 直接 mypy 还会涉及原有 `authoring.build` 的 POSIX killpg/SIGKILL 属性，正式检查使用 `--platform linux`。

这关闭受限角色完整 fresh/原生助手预算机制这一边界。真实 Kafka broker/消费者传输、对象存储服务、供应商质量/费用、生产部署及浏览器视觉仍未验；不能由本结果授真实模型费用资格。

## F08-02：unknown 恢复与独立意图服务端增量

沿用上述已锁镜像和 SQL 字节，新建相同隔离规则的全新 tmpfs PG17 与内部网络。**25 passed in 121.04s**（原 5 项 + 新增 20 项）；测试源实际字节 SHA256：`3a86e3eb73fceb0af3e02995ffe5d868e5814ebe6390c7b3d0c62836e7f0a1c0`。本增量只改测试和本文，没有修改 SQL、Python 业务机制或前端。

| 实际受限角色场景 | 结果 |
| --- | --- |
| 同一未知项目请求换 nonce、上下文、模型 profile 或 max_tokens | 复用原 job；改问题措辞仍是同对象/用途时返回 `ASSISTANT_INDEPENDENCE_UNPROVEN`；原预算、native、事件及三 scope 责任不变 |
| 新工程/标段/轮次/项目 UUID 壳，重新确认同五个业务事实值 | canonical key 与原项目一致；相同问题复用原 job，不同措辞不能绕过；没有把新 UUID 当独立证据 |
| 显式 retry / continue | 缺原 job 引用拒绝；带原 job 时即使夹带另一个目标标签也优先关联原请求，不重新执行 |
| 同成员、不同已确认业务身份的真实项目 | 无 `new_question` 或仅写“继续”均拒绝；明确新问题且不同 canonical 身份才受理并执行一次；原 unknown 金额继续占额 |
| 同项目中的不同实际 rule 对象/用途 | 把 project 用途随意改为 rule_explanation 拒绝；目标为实际 rule 且用途为 rule_explanation 才允许独立受理一次 |
| global / member / project 各一条有界限额反例 | 将该 scope 新限额设为当前实际 obligation，旧 unknown 占满；即使是已证明独立的 rule 请求也被 `ASSISTANT_BUDGET_EXHAUSTED` 拒绝；无新 call、dispatch、预算事件 |
| project / global × 三种可信核清 | 专用预算管理 CLI 的 confirmed_not_sent/0 → released；confirmed_zero_charge_failure/0 → settled；confirmed_billed/17 → settled/17。只追加一次 reconciled 事件，native 仍为失败，原操作仍失败，不生成回答 |
| 重复核清与冲突金额核清 | 两者都明确拒绝 `ASSISTANT_RECONCILIATION_INVALID`，原核清结果及事件不变。该 CLI 合同是重复拒绝，未称幂等成功；HTTP 原请求仍读回原 job，原 Worker 消息零再发送 |
| 可信核清 17 后，实际 Worker observe_usage 迟到报告 32 | 恢复 unknown 及原 reserved 2099200，置 sticky manual flag；native 仍失败，未增加 dispatch/call。真实 API coordinator.tick 不清除 manual；API 读回要求核清、不授权自动重试 |

新测试全部由真实 API/Worker LOGIN 建立事实依据、调用 ASGI/原生 Worker/预算 RPC，并由独立管理进程核清。rule 是 API 身份按实际领域表/FK建立的合成目标，使用真实证据 ID；并未把此用例冒充原件条款抽取/人工正式确认质量。所有五事实和 live 来源仍走原生 human basis、carryover 与完整 SQL 权威，没有 no-op。

`assistant_budget_obligation` 在 API 身份下读取真实最新 policy 及历史责任，检查旧 unknown 在换限额版本后不消失；新独立对象的 32 合成 minor 与原 held 并存。核清证明地址/摘要为明确合成可信管理输入，不表示拿到了供应商账单。

增量原始证据保存在 `.local/nonowner-recovery-evidence/nonowner.xml` 与 `nonowner-receipt.jsonl`，旧五项及主代理收据保持原目录。实际累计 **25 次离线 Mock HTTP**、重复执行新增 **0 次**、真实供应商 **0 次/0 费用**。finally 凭证确认 nonce 库、五个 LOGIN 及私有 profile 均已清理，能力组不变；专用 PG/内部网络在主代理独立复验窗口暂留，随后单独清理。

ruff/format、mypy（`--platform linux`）通过；既有测试 Bandit 规则口径不变。本增量没有发现需要修正的生产机制。剩余产品缺口是将上述 `request_mode`、可信目标/允许用途及原 job 引用接入 unknown 下的显式 UI 流程；现 UI 的整体 busy gate 不能由后端测试视为已完成。真实 Kafka、外部对象存储/供应商及生产放行仍属于独立验收。
